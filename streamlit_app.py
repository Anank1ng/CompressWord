import streamlit as st
import zipfile
import tempfile
import shutil
import os
import io
import copy
from pathlib import Path

from PIL import Image, ImageOps


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="Word Compressor",
    page_icon="📄",
    layout="centered"
)


# =========================================================
# CONSTANT
# =========================================================

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".webp",
    ".emf",
    ".wmf",
    ".svg",
}


# =========================================================
# UTILITIES
# =========================================================

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"

    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.2f} KB"

    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.2f} MB"

    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


def reduction_percentage(original, compressed):
    if original <= 0:
        return 0

    return max(
        0,
        ((original - compressed) / original) * 100
    )


def is_word_media(filename):
    return filename.startswith("word/media/")


def is_image(filename):
    extension = Path(filename).suffix.lower()

    return (
        is_word_media(filename)
        and extension in IMAGE_EXTENSIONS
    )


# =========================================================
# FILE ANALYSIS
# =========================================================

def analyze_docx(file_path):
    total_images = 0
    image_size = 0

    jpg_count = 0
    png_count = 0
    other_count = 0

    largest_images = []

    with zipfile.ZipFile(file_path, "r") as zf:

        for info in zf.infolist():

            if not is_image(info.filename):
                continue

            total_images += 1
            image_size += info.file_size

            ext = Path(info.filename).suffix.lower()

            if ext in [".jpg", ".jpeg"]:
                jpg_count += 1

            elif ext == ".png":
                png_count += 1

            else:
                other_count += 1

            largest_images.append(
                (
                    info.filename,
                    info.file_size
                )
            )

    largest_images.sort(
        key=lambda x: x[1],
        reverse=True
    )

    return {
        "total_images": total_images,
        "image_size": image_size,
        "jpg_count": jpg_count,
        "png_count": png_count,
        "other_count": other_count,
        "largest_images": largest_images[:10]
    }


# =========================================================
# IMAGE RESIZE
# =========================================================

def resize_image(image, max_dimension):
    if not max_dimension:
        return image

    width, height = image.size

    largest_side = max(width, height)

    if largest_side <= max_dimension:
        return image

    ratio = max_dimension / largest_side

    new_width = max(
        1,
        int(width * ratio)
    )

    new_height = max(
        1,
        int(height * ratio)
    )

    return image.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS
    )


# =========================================================
# JPEG COMPRESSION
# =========================================================

def optimize_jpeg(
    image_bytes,
    quality=85,
    max_dimension=None,
    remove_metadata=False
):

    try:
        source = io.BytesIO(image_bytes)

        with Image.open(source) as img:

            img.load()

            exif = img.info.get("exif")
            icc_profile = img.info.get(
                "icc_profile"
            )

            # Kalau metadata dibuang, pastikan orientasi
            # gambar tetap benar.
            if remove_metadata:
                img = ImageOps.exif_transpose(img)
                exif = None
                icc_profile = None

            img = resize_image(
                img,
                max_dimension
            )

            # JPEG tidak menerima alpha
            if img.mode in ("RGBA", "LA"):
                background = Image.new(
                    "RGB",
                    img.size,
                    "white"
                )

                alpha = img.getchannel("A")

                background.paste(
                    img.convert("RGB"),
                    mask=alpha
                )

                img = background

            elif img.mode not in ("RGB", "L", "CMYK"):
                img = img.convert("RGB")

            output = io.BytesIO()

            save_args = {
                "format": "JPEG",
                "quality": quality,
                "optimize": True,
                "progressive": True,
            }

            if exif and not remove_metadata:
                save_args["exif"] = exif

            if icc_profile and not remove_metadata:
                save_args[
                    "icc_profile"
                ] = icc_profile

            img.save(
                output,
                **save_args
            )

            optimized = output.getvalue()

            # Jangan gunakan hasil kalau justru membesar
            if len(optimized) >= len(image_bytes):
                return image_bytes

            return optimized

    except Exception:
        return image_bytes


# =========================================================
# PNG LOSSLESS OPTIMIZATION
# =========================================================

def optimize_png(
    image_bytes,
    max_dimension=None,
    remove_metadata=False
):

    try:
        source = io.BytesIO(image_bytes)

        with Image.open(source) as img:

            # Hindari animasi / multi-frame
            if getattr(
                img,
                "is_animated",
                False
            ):
                return image_bytes

            img.load()

            icc_profile = img.info.get(
                "icc_profile"
            )

            img = resize_image(
                img,
                max_dimension
            )

            output = io.BytesIO()

            save_args = {
                "format": "PNG",
                "optimize": True,
                "compress_level": 9,
            }

            if (
                icc_profile
                and not remove_metadata
            ):
                save_args[
                    "icc_profile"
                ] = icc_profile

            img.save(
                output,
                **save_args
            )

            optimized = output.getvalue()

            # Jangan pakai jika lebih besar
            if len(optimized) >= len(image_bytes):
                return image_bytes

            return optimized

    except Exception:
        return image_bytes


# =========================================================
# STREAM ZIP ENTRY
# =========================================================

def copy_zip_entry(
    source_zip,
    target_zip,
    info
):
    new_info = copy.copy(info)

    # Recompress struktur ZIP
    new_info.compress_type = (
        zipfile.ZIP_DEFLATED
    )

    with source_zip.open(
        info.filename,
        "r"
    ) as src:

        with target_zip.open(
            new_info,
            "w",
            force_zip64=True
        ) as dst:

            shutil.copyfileobj(
                src,
                dst,
                length=1024 * 1024
            )


# =========================================================
# DOCX COMPRESSOR
# =========================================================

def compress_docx(
    input_path,
    output_path,
    jpeg_quality=85,
    optimize_jpeg_enabled=True,
    optimize_png_enabled=True,
    max_dimension=None,
    remove_image_metadata=False,
    remove_thumbnail=False,
    progress_callback=None
):

    with zipfile.ZipFile(
        input_path,
        "r"
    ) as source_zip:

        names = source_zip.namelist()

        required = [
            "[Content_Types].xml",
            "_rels/.rels",
        ]

        for required_file in required:

            if required_file not in names:
                raise ValueError(
                    "File bukan DOCX yang valid."
                )

        entries = source_zip.infolist()

        total_entries = len(entries)

        with zipfile.ZipFile(
            output_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True
        ) as target_zip:

            for index, info in enumerate(entries):

                filename = info.filename

                # -----------------------------------------
                # Optional: remove document thumbnail
                # -----------------------------------------

                if (
                    remove_thumbnail
                    and filename.lower()
                    == "docprops/thumbnail.jpeg"
                ):
                    continue

                extension = (
                    Path(filename)
                    .suffix
                    .lower()
                )

                # -----------------------------------------
                # JPEG
                # -----------------------------------------

                if (
                    is_word_media(filename)
                    and extension
                    in [".jpg", ".jpeg"]
                    and optimize_jpeg_enabled
                ):

                    original = (
                        source_zip.read(filename)
                    )

                    optimized = optimize_jpeg(
                        original,
                        quality=jpeg_quality,
                        max_dimension=max_dimension,
                        remove_metadata=(
                            remove_image_metadata
                        )
                    )

                    new_info = copy.copy(info)

                    new_info.compress_type = (
                        zipfile.ZIP_DEFLATED
                    )

                    target_zip.writestr(
                        new_info,
                        optimized,
                        compress_type=(
                            zipfile.ZIP_DEFLATED
                        ),
                        compresslevel=9
                    )

                # -----------------------------------------
                # PNG
                # -----------------------------------------

                elif (
                    is_word_media(filename)
                    and extension == ".png"
                    and optimize_png_enabled
                ):

                    original = (
                        source_zip.read(filename)
                    )

                    optimized = optimize_png(
                        original,
                        max_dimension=max_dimension,
                        remove_metadata=(
                            remove_image_metadata
                        )
                    )

                    new_info = copy.copy(info)

                    new_info.compress_type = (
                        zipfile.ZIP_DEFLATED
                    )

                    target_zip.writestr(
                        new_info,
                        optimized,
                        compress_type=(
                            zipfile.ZIP_DEFLATED
                        ),
                        compresslevel=9
                    )

                # -----------------------------------------
                # Everything else
                # -----------------------------------------

                else:

                    copy_zip_entry(
                        source_zip,
                        target_zip,
                        info
                    )

                if progress_callback:

                    progress_callback(
                        (index + 1)
                        / total_entries
                    )


# =========================================================
# SESSION STATE
# =========================================================

if "result_path" not in st.session_state:
    st.session_state.result_path = None

if "original_size" not in st.session_state:
    st.session_state.original_size = None

if "result_size" not in st.session_state:
    st.session_state.result_size = None

if "output_name" not in st.session_state:
    st.session_state.output_name = None


# =========================================================
# HEADER
# =========================================================

st.title("📄 Word Compressor")

st.write(
    """
    Kompres file **Microsoft Word (.docx)** dengan beberapa
    tingkat kompresi.

    **Gambar duplikat tidak dihapus.**
    """
)


# =========================================================
# UPLOAD
# =========================================================

uploaded_file = st.file_uploader(
    "Upload file Word",
    type=["docx"],
    help="Mendukung file DOCX berukuran besar."
)


if uploaded_file is not None:

    # =====================================================
    # SAVE UPLOAD TO TEMPORARY DISK
    # =====================================================

    temp_input = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".docx"
    )

    try:

        uploaded_file.seek(0)

        shutil.copyfileobj(
            uploaded_file,
            temp_input,
            length=1024 * 1024
        )

        temp_input.close()

        input_path = temp_input.name

        original_size = os.path.getsize(
            input_path
        )

        # =================================================
        # ANALYSIS
        # =================================================

        try:

            analysis = analyze_docx(
                input_path
            )

        except zipfile.BadZipFile:

            st.error(
                "File tidak dapat dibaca sebagai DOCX."
            )

            st.stop()

        st.divider()

        st.subheader("Informasi Dokumen")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Ukuran File",
                format_size(original_size)
            )

        with col2:
            st.metric(
                "File Gambar",
                analysis["total_images"]
            )

        with col3:
            st.metric(
                "Total Media",
                format_size(
                    analysis["image_size"]
                )
            )

        st.caption(
            f"JPEG: {analysis['jpg_count']} • "
            f"PNG: {analysis['png_count']} • "
            f"Lainnya: {analysis['other_count']}"
        )

        # =================================================
        # MODE
        # =================================================

        st.divider()

        st.subheader("Mode Kompresi")

        mode = st.radio(
            "Pilih tingkat kompresi",
            [
                "🔒 Lossless",
                "⚖️ Balanced",
                "🔥 Strong",
                "⚙️ Custom"
            ],
            horizontal=True
        )

        # Default
        jpeg_quality = 100
        max_dimension = None
        optimize_jpeg_enabled = False
        optimize_png_enabled = True
        remove_metadata = False
        remove_thumbnail = True

        # =================================================
        # LOSSLESS
        # =================================================

        if mode == "🔒 Lossless":

            st.info(
                """
                **Kualitas maksimal.**

                Gambar JPEG tidak dikompres ulang.
                PNG dioptimasi tanpa menurunkan kualitas visual.
                Struktur DOCX dikompres ulang.
                """
            )

            jpeg_quality = 100
            max_dimension = None
            optimize_jpeg_enabled = False
            optimize_png_enabled = True
            remove_metadata = False

        # =================================================
        # BALANCED
        # =================================================

        elif mode == "⚖️ Balanced":

            st.info(
                """
                **Direkomendasikan.**

                Kompresi gambar ringan dengan kualitas visual
                yang biasanya masih sangat sulit dibedakan
                dari gambar asli.
                """
            )

            jpeg_quality = 88
            max_dimension = 3000
            optimize_jpeg_enabled = True
            optimize_png_enabled = True
            remove_metadata = True

        # =================================================
        # STRONG
        # =================================================

        elif mode == "🔥 Strong":

            st.warning(
                """
                **Kompresi lebih agresif.**

                Cocok untuk dokumen sangat besar yang berisi
                banyak foto resolusi tinggi.
                """
            )

            jpeg_quality = 78
            max_dimension = 2200
            optimize_jpeg_enabled = True
            optimize_png_enabled = True
            remove_metadata = True

        # =================================================
        # CUSTOM
        # =================================================

        else:

            st.write(
                "Atur kompresi sesuai kebutuhan."
            )

            optimize_jpeg_enabled = st.checkbox(
                "Kompres gambar JPEG",
                value=True
            )

            jpeg_quality = st.slider(
                "JPEG Quality",
                min_value=50,
                max_value=100,
                value=85,
                step=1
            )

            st.caption(
                """
                90–95 = sangat tinggi •
                80–89 = seimbang •
                65–79 = kompresi kuat
                """
            )

            optimize_png_enabled = st.checkbox(
                "Optimasi PNG",
                value=True
            )

            resolution_choice = st.selectbox(
                "Maksimum sisi gambar",
                [
                    "Tidak resize",
                    "4000 px",
                    "3000 px",
                    "2500 px",
                    "2200 px",
                    "2000 px",
                    "1600 px"
                ]
            )

            resolution_map = {
                "Tidak resize": None,
                "4000 px": 4000,
                "3000 px": 3000,
                "2500 px": 2500,
                "2200 px": 2200,
                "2000 px": 2000,
                "1600 px": 1600
            }

            max_dimension = (
                resolution_map[
                    resolution_choice
                ]
            )

            remove_metadata = st.checkbox(
                "Hapus metadata gambar",
                value=True,
                help=(
                    "Menghapus metadata EXIF/ICC "
                    "yang tidak terlihat di halaman."
                )
            )

        # =================================================
        # EXTRA OPTIONS
        # =================================================

        with st.expander(
            "🧰 Pengaturan tambahan"
        ):

            remove_thumbnail = st.checkbox(
                "Hapus thumbnail preview DOCX",
                value=True,
                help=(
                    "Hanya menghapus thumbnail preview "
                    "dokumen, bukan gambar yang ada "
                    "di halaman Word."
                )
            )

            st.success(
                """
                ✅ Gambar yang sama/duplikat tidak akan dicari
                atau dihapus.

                ✅ Relasi dan posisi gambar di dokumen tetap
                dipertahankan.
                """
            )

        # =================================================
        # COMPRESS BUTTON
        # =================================================

        st.divider()

        if st.button(
            "🗜️ Kompres File Word",
            type="primary",
            use_container_width=True
        ):

            progress = st.progress(
                0,
                text="Menyiapkan kompresi..."
            )

            output_file = (
                tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=".docx"
                )
            )

            output_file.close()

            output_path = output_file.name

            def update_progress(value):

                percentage = int(
                    value * 100
                )

                progress.progress(
                    percentage,
                    text=(
                        f"Mengompresi dokumen... "
                        f"{percentage}%"
                    )
                )

            try:

                compress_docx(
                    input_path=input_path,
                    output_path=output_path,
                    jpeg_quality=jpeg_quality,
                    optimize_jpeg_enabled=(
                        optimize_jpeg_enabled
                    ),
                    optimize_png_enabled=(
                        optimize_png_enabled
                    ),
                    max_dimension=max_dimension,
                    remove_image_metadata=(
                        remove_metadata
                    ),
                    remove_thumbnail=(
                        remove_thumbnail
                    ),
                    progress_callback=(
                        update_progress
                    )
                )

                progress.progress(
                    100,
                    text="Selesai!"
                )

                result_size = os.path.getsize(
                    output_path
                )

                # Jangan menawarkan hasil jika justru
                # lebih besar.
                if result_size >= original_size:

                    st.warning(
                        """
                        Hasil optimasi tidak lebih kecil dari
                        file asli.

                        Coba gunakan mode **Balanced** atau
                        **Strong**.
                        """
                    )

                else:

                    output_name = (
                        f"{Path(uploaded_file.name).stem}"
                        f"_compressed.docx"
                    )

                    st.session_state.result_path = (
                        output_path
                    )

                    st.session_state.original_size = (
                        original_size
                    )

                    st.session_state.result_size = (
                        result_size
                    )

                    st.session_state.output_name = (
                        output_name
                    )

                    st.success(
                        "✅ Kompresi selesai."
                    )

            except Exception as e:

                st.error(
                    f"Terjadi kesalahan: {e}"
                )


        # =================================================
        # RESULT
        # =================================================

        if (
            st.session_state.result_path
            and os.path.exists(
                st.session_state.result_path
            )
        ):

            before = (
                st.session_state.original_size
            )

            after = (
                st.session_state.result_size
            )

            reduction = before - after

            percent = reduction_percentage(
                before,
                after
            )

            st.divider()

            st.subheader("Hasil Kompresi")

            col1, col2, col3 = st.columns(3)

            with col1:

                st.metric(
                    "Sebelum",
                    format_size(before)
                )

            with col2:

                st.metric(
                    "Sesudah",
                    format_size(after),
                    delta=(
                        f"-{format_size(reduction)}"
                    )
                )

            with col3:

                st.metric(
                    "Pengurangan",
                    f"{percent:.2f}%"
                )

            with open(
                st.session_state.result_path,
                "rb"
            ) as result_file:

                st.download_button(
                    label=(
                        "⬇️ Download Word "
                        "Hasil Kompresi"
                    ),
                    data=result_file,
                    file_name=(
                        st.session_state.output_name
                    ),
                    mime=(
                        "application/vnd."
                        "openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    type="primary",
                    use_container_width=True
                )

    finally:

        try:

            if os.path.exists(
                temp_input.name
            ):
                os.remove(
                    temp_input.name
                )

        except Exception:
            pass


# =========================================================
# INFO
# =========================================================

st.divider()

with st.expander(
    "ℹ️ Perbedaan mode kompresi"
):

    st.markdown(
        """
        ### 🔒 Lossless

        - Tidak recompress JPEG
        - Tidak resize gambar
        - Optimasi PNG
        - ZIP DOCX level maksimum
        - Kualitas gambar dipertahankan

        **Cocok jika file harus benar-benar mendekati original.**

        ---

        ### ⚖️ Balanced

        - JPEG Quality 88
        - Gambar maksimal 3000 px
        - PNG dioptimasi
        - Metadata gambar dibersihkan
        - ZIP level maksimum

        **Biasanya pilihan terbaik untuk dokumen kantor,
        laporan, tesis, dokumentasi, dan laporan kegiatan.**

        ---

        ### 🔥 Strong

        - JPEG Quality 78
        - Gambar maksimal 2200 px
        - PNG dioptimasi
        - Metadata dibersihkan
        - ZIP level maksimum

        **Cocok untuk Word berukuran ratusan MB.**

        ---

        ### ⚙️ Custom

        Kamu bisa mengatur sendiri JPEG Quality,
        resolusi maksimum, optimasi PNG, dan metadata.

        ---

        ### Gambar duplikat

        Aplikasi **tidak melakukan deduplikasi gambar**.
        Gambar yang digunakan berulang tetap dipertahankan.
        """
    )


st.caption(
    "Word Compressor • Advanced DOCX Compression"
)
