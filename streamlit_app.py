import streamlit as st
import zipfile
import tempfile
import os
import shutil
from pathlib import Path
from io import BytesIO


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Word Compressor",
    page_icon="📄",
    layout="centered"
)


# =========================================================
# FUNCTIONS
# =========================================================
def format_size(size_bytes):
    """
    Mengubah ukuran byte menjadi format yang mudah dibaca.
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


def get_image_info(docx_bytes):
    """
    Menghitung jumlah dan ukuran gambar di dalam DOCX.

    Fungsi ini TIDAK menghapus gambar.
    Hanya membaca informasi.
    """
    image_files = []
    total_image_size = 0

    try:
        with zipfile.ZipFile(BytesIO(docx_bytes), "r") as zf:
            for info in zf.infolist():
                if info.filename.startswith("word/media/"):
                    # Abaikan folder jika ada
                    if not info.is_dir():
                        image_files.append(info.filename)
                        total_image_size += info.file_size

    except Exception:
        pass

    return len(image_files), total_image_size


def compress_docx(uploaded_bytes):
    """
    Melakukan lossless repack terhadap file DOCX.

    Prinsip:
    - Tidak mengubah XML Word
    - Tidak mengubah gambar
    - Tidak menghapus gambar duplikat
    - Tidak resize gambar
    - Tidak recompress JPEG
    - Tidak menghapus metadata dokumen
    - Hanya membuat ulang ZIP dengan DEFLATE level maksimum
    """

    input_buffer = BytesIO(uploaded_bytes)
    output_buffer = BytesIO()

    with zipfile.ZipFile(input_buffer, "r") as input_zip:

        # Pastikan file adalah DOCX yang valid
        required_files = [
            "[Content_Types].xml",
            "_rels/.rels"
        ]

        zip_names = input_zip.namelist()

        for required_file in required_files:
            if required_file not in zip_names:
                raise ValueError(
                    "File tidak terdeteksi sebagai DOCX yang valid."
                )

        # DOCX kompatibel dengan ZIP_DEFLATED
        with zipfile.ZipFile(
            output_buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True
        ) as output_zip:

            for item in input_zip.infolist():

                # Baca data ASLI
                data = input_zip.read(item.filename)

                # Buat metadata ZIP baru
                new_info = zipfile.ZipInfo(
                    filename=item.filename,
                    date_time=item.date_time
                )

                # Pertahankan informasi file yang relevan
                new_info.comment = item.comment
                new_info.extra = item.extra
                new_info.internal_attr = item.internal_attr
                new_info.external_attr = item.external_attr
                new_info.create_system = item.create_system

                # Direktori
                if item.is_dir():
                    new_info.compress_type = zipfile.ZIP_STORED
                    output_zip.writestr(new_info, data)
                    continue

                # Semua file dikompresi maksimum.
                #
                # Gambar tetap menggunakan byte ASLI.
                # Jadi JPEG/PNG TIDAK di-encode ulang.
                new_info.compress_type = zipfile.ZIP_DEFLATED

                output_zip.writestr(
                    new_info,
                    data,
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9
                )

    output_buffer.seek(0)

    return output_buffer.getvalue()


# =========================================================
# UI
# =========================================================
st.title("📄 Word Compressor")

st.write(
    """
    Mengecilkan ukuran file **Microsoft Word (.docx)** tanpa menurunkan
    kualitas gambar dan tanpa menghapus gambar duplikat.
    """
)

st.info(
    """
    🔒 **Mode Lossless**

    Aplikasi tidak melakukan resize, recompress, atau penghapusan gambar.
    Isi dokumen dipertahankan apa adanya.
    """
)

uploaded_file = st.file_uploader(
    "Upload file Word",
    type=["docx"],
    help="Saat ini hanya mendukung format .docx"
)


# =========================================================
# PROCESS FILE
# =========================================================
if uploaded_file is not None:

    try:
        original_bytes = uploaded_file.getvalue()

        original_size = len(original_bytes)

        image_count, image_size = get_image_info(original_bytes)

        st.divider()

        st.subheader("Informasi File")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                label="Ukuran File",
                value=format_size(original_size)
            )

        with col2:
            st.metric(
                label="Jumlah Gambar",
                value=image_count
            )

        with col3:
            st.metric(
                label="Ukuran Gambar",
                value=format_size(image_size)
            )

        st.caption(
            "Jumlah gambar termasuk gambar yang identik/duplikat. "
            "Tidak ada gambar yang akan dihapus."
        )

        st.divider()

        if st.button(
            "🗜️ Kompres File Word",
            type="primary",
            use_container_width=True
        ):

            with st.spinner("Mengompresi file tanpa mengubah gambar..."):

                compressed_bytes = compress_docx(original_bytes)

                compressed_size = len(compressed_bytes)

                difference = original_size - compressed_size

                if original_size > 0:
                    reduction_percent = (
                        difference / original_size
                    ) * 100
                else:
                    reduction_percent = 0

            st.success("✅ Proses selesai.")

            st.subheader("Hasil Kompresi")

            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric(
                    "Sebelum",
                    format_size(original_size)
                )

            with col2:
                st.metric(
                    "Sesudah",
                    format_size(compressed_size),
                    delta=(
                        f"-{format_size(difference)}"
                        if difference > 0
                        else "Tidak berkurang"
                    )
                )

            with col3:
                st.metric(
                    "Pengurangan",
                    (
                        f"{reduction_percent:.2f}%"
                        if reduction_percent > 0
                        else "0%"
                    )
                )

            # Nama file output
            original_name = Path(uploaded_file.name).stem

            output_name = (
                f"{original_name}_compressed.docx"
            )

            st.download_button(
                label="⬇️ Download Word Hasil Kompresi",
                data=compressed_bytes,
                file_name=output_name,
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                use_container_width=True,
                type="primary"
            )

            # =====================================================
            # NOTICE
            # =====================================================
            if compressed_size >= original_size:

                st.warning(
                    """
                    Ukuran file tidak berkurang secara signifikan.

                    Ini normal jika sebagian besar isi dokumen adalah
                    gambar JPG/PNG karena format tersebut sudah
                    terkompresi.

                    File tetap diproses secara **lossless** dan tidak ada
                    gambar yang dihapus atau diturunkan kualitasnya.
                    """
                )

            elif reduction_percent < 5:

                st.info(
                    """
                    Pengurangan ukuran relatif kecil karena dokumen
                    kemungkinan besar didominasi oleh JPG/PNG yang
                    sudah terkompresi.

                    Ini merupakan konsekuensi dari mempertahankan
                    gambar 100% tanpa recompress.
                    """
                )


    except zipfile.BadZipFile:
        st.error(
            "❌ File tidak dapat dibaca. Pastikan file benar-benar "
            "berformat .docx."
        )

    except ValueError as e:
        st.error(f"❌ {str(e)}")

    except Exception as e:
        st.error(
            f"❌ Terjadi kesalahan saat memproses file:\n\n{str(e)}"
        )


# =========================================================
# EXPLANATION
# =========================================================
st.divider()

with st.expander("ℹ️ Apa yang dilakukan aplikasi?"):

    st.markdown(
        """
        **Yang dilakukan:**

        - Membaca struktur internal `.docx`
        - Mengemas ulang file DOCX
        - Menggunakan ZIP Deflate level maksimum
        - Mempertahankan seluruh gambar
        - Mempertahankan gambar duplikat
        - Mempertahankan XML Word
        - Mempertahankan style dan layout dokumen

        **Yang TIDAK dilakukan:**

        - ❌ Resize gambar
        - ❌ Menurunkan resolusi
        - ❌ Mengubah JPEG quality
        - ❌ Mengubah PNG quality
        - ❌ Menghapus gambar duplikat
        - ❌ Menghapus gambar tersembunyi
        - ❌ Mengubah teks
        - ❌ Mengubah tabel
        - ❌ Mengubah header/footer
        """
    )


st.caption(
    "Word Compressor • Lossless DOCX compression"
)
