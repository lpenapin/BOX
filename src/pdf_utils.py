from pypdf import PdfReader, PdfWriter
from pathlib import Path
import tempfile
import shutil
import logging
import os
import io
import pikepdf
import time

from utils_phase2 import _run, _safe_slug, _longpath, _ensure_short_enough
from __init__ import MAX_PDF_MB, MAX_PDF_PAGES, FINAL_META


def normalize_pdf_for_split(src_path: str) -> tuple[str, list[str], str]:
    temps: list[str] = []
    try:
        r = PdfReader(src_path, strict=False)
        if getattr(r, "is_encrypted", False):
            try:
                ok = r.decrypt("")
                if not ok:
                    return src_path, temps, "encrypted (decrypt failed)"
            except Exception:
                return src_path, temps, "encrypted (exception)"
        _ = len(r.pages)
        return src_path, temps, "ok"
    except Exception:
        pass

    # pikepdf
    try:
        tmp = Path(tempfile.gettempdir()) / \
            (Path(src_path).stem + ".__norm_pike.pdf")
        with pikepdf.open(src_path) as pdf:
            pdf.save(str(tmp), linearize=False)
        temps.append(str(tmp))
        _ = len(PdfReader(str(tmp), strict=False).pages)
        return str(tmp), temps, "pikepdf"
    except Exception:
        pass

    # qpdf
    qpdf = shutil.which("qpdf")
    if qpdf:
        tmp = Path(tempfile.gettempdir()) / \
            (Path(src_path).stem + ".__norm_qpdf.pdf")
        rc, _, _ = _run([qpdf, "--warning-exit-0", "--qdf",
                        "--object-streams=disable", src_path, str(tmp)])
        if rc == 0 and tmp.exists() and tmp.stat().st_size > 0:
            temps.append(str(tmp))
            try:
                _ = len(PdfReader(str(tmp), strict=False).pages)
                return str(tmp), temps, "qpdf"
            except Exception:
                pass

    # Ghostscript
    gs = shutil.which("gswin64c") or shutil.which(
        "gswin32c") or shutil.which("gs")
    if gs:
        tmp = Path(tempfile.gettempdir()) / \
            (Path(src_path).stem + ".__norm_gs.pdf")
        rc, _, _ = _run([gs, "-dBATCH", "-dNOPAUSE", "-dSAFER",
                        "-sDEVICE=pdfwrite", "-dPDFSETTINGS=/prepress",
                        f"-sOutputFile={str(tmp)}", src_path])
        if rc == 0 and tmp.exists() and tmp.stat().st_size > 0:
            temps.append(str(tmp))
            try:
                _ = len(PdfReader(str(tmp), strict=False).pages)
                return str(tmp), temps, "ghostscript"
            except Exception:
                pass

    # MuPDF
    mutool = shutil.which("mutool")
    if mutool:
        tmp = Path(tempfile.gettempdir()) / \
            (Path(src_path).stem + ".__norm_mu.pdf")
        rc, _, _ = _run([mutool, "clean", "-gg", src_path, str(tmp)])
        if rc == 0 and tmp.exists() and tmp.stat().st_size > 0:
            temps.append(str(tmp))
            try:
                _ = len(PdfReader(str(tmp), strict=False).pages)
                return str(tmp), temps, "mutool"
            except Exception:
                pass

    return src_path, temps, "open failed (raw)"


def split_pdf_by_size_and_pages(
    input_pdf_path: str,
    parts_folder: Path,
    max_size_mb: float,
    max_pages_per_part: int
    ) -> list[str]:
    """
    Robust splitter that normalizes the PDF first (pikepdf/qpdf/GS/mutool),
    then writes parts capped by both size and page count.
    """
    outputs: list[str] = []
    src = Path(input_pdf_path)

    parts_folder.mkdir(parents=True, exist_ok=True)
    safe_base = _safe_slug(src.stem, limit=60)
    

    # 1) normalize first (this is what made the test succeed)
    norm_path, temp_files, norm_reason = normalize_pdf_for_split(str(src))
    logging.info(f"✅[SPLIT] Using '{norm_reason}' normalized file: {norm_path}")

    def _cleanup_temps():
        for t in temp_files:
            try:
                if os.path.exists(t):
                    os.remove(t)
            except Exception:
                pass

    # 2) open reader
    try:
        reader = PdfReader(norm_path, strict=False)
    except Exception as e:
        logging.error(f"❌[SPLIT] PdfReader failed: {e}")
        # fallback copy
        dst = parts_folder / f"{safe_base}.pdf"
        try:
            with open(_longpath(dst), "wb") as f_out, open(_longpath(src), "rb") as f_in:
                shutil.copyfileobj(f_in, f_out)
            outputs.append(str(dst))
            logging.warning(f"⚠️[SPLIT] Fallback copy -> {dst}")
        except Exception as ee:
            logging.error(f"❌[SPLIT] Fallback copy failed: {ee}")
        _cleanup_temps()
        return outputs

    if getattr(reader, "is_encrypted", False):
        try:
            ok = reader.decrypt("")
            if not ok:
                logging.error("❌[SPLIT] Encrypted PDF; cannot decrypt.")
                _cleanup_temps()
                return outputs
        except Exception as e:
            logging.error(f"❌[SPLIT] Decrypt error: {e}")
            _cleanup_temps()
            return outputs

    total = len(reader.pages)
    logging.info(f"✅[SPLIT] Total pages: {total}")
    if total == 0:
        out = parts_folder / f"{safe_base}.pdf"
        with open(_longpath(out), "wb") as f_out, open(_longpath(src), "rb") as f_in:
            shutil.copyfileobj(f_in, f_out)
        outputs.append(str(out))
        logging.warning("⚠️[SPLIT] Zero pages/portfolio; copied original.")
        _cleanup_temps()
        return outputs

    max_bytes = int(max_size_mb * 1024 * 1024)

    current_writer = PdfWriter()
    current_start = 0   # 0-based page index of current part
    current_count = 0

    def flush_part(end_idx_inclusive: int):
        nonlocal current_writer, current_count
        part_path = _ensure_short_enough(
            parts_folder / safe_base, safe_base,
            current_start + 1, end_idx_inclusive + 1
        )
        #logging.error(str(part_path))
        #logging.error(len(str(part_path)))

        #with open(_longpath(part_path), "wb") as f:
        with open(part_path, "wb") as f:
            current_writer.write(f)
        outputs.append(str(part_path))
        try:
            size_mb = os.path.getsize(part_path) / (1024 * 1024)
        except Exception:
            size_mb = -1
        logging.info(
            f"✅[SPLIT] Wrote {part_path}  pages={current_count}  size={size_mb:.2f} MB")
        current_writer = PdfWriter()
        current_count = 0

    for i in range(total):
        # read page robustly
        try:
            page = reader.pages[i]
        except Exception as e:
            logging.error(f"❌[SPLIT] Read page {i+1} failed: {e}")
            if current_count > 0:
                flush_part(i - 1)
            current_start = i + 1
            continue

        # add page to current writer
        try:
            current_writer.add_page(page)
        except Exception as e:
            logging.error(f"❌[SPLIT] add_page failed @ {i+1}: {e}")
            if current_count > 0:
                flush_part(i - 1)

            # attempt single-page part for this page
            single_writer = PdfWriter()
            try:
                single_writer.add_page(page)
                single_path = _ensure_short_enough(
                    parts_folder / safe_base, safe_base, i + 1, i + 1
                )
                with open(_longpath(single_path), "wb") as f:
                    single_writer.write(f)
                outputs.append(str(single_path))
                logging.warning(
                    f"⚠️[SPLIT] Wrote single-page part for page {i+1}")
            except Exception as ee:
                logging.error(f"❌[SPLIT] Failed single-page part @ {i+1}: {ee}")

            current_start = i + 1
            current_writer = PdfWriter()
            current_count = 0
            continue

        current_count += 1

        # Decide flush by page limit or size
        need_flush = current_count >= max_pages_per_part
        if not need_flush:
            try:
                buf = io.BytesIO()
                current_writer.write(buf)
                if buf.tell() >= max_bytes:
                    need_flush = True
            except Exception as e:
                logging.warning(f"⚠️[SPLIT] size check failed @ page {i+1}: {e}")
                # fall back to page-cap rule only

        if need_flush:
            flush_part(i)
            current_start = i + 1

    # leftover pages
    if current_count > 0:
        flush_part(total - 1)

    _cleanup_temps()

    # If nothing was produced, copy the original so the folder isn't empty
    if not outputs:
        safe_base = _safe_slug(Path(input_pdf_path).stem, limit=60)
    dst = parts_folder / f"{safe_base}.pdf"
    try:
        with open(_longpath(dst), "wb") as f_out, open(_longpath(input_pdf_path), "rb") as f_in:
            shutil.copyfileobj(f_in, f_out)
        outputs.append(str(dst))
        logging.warning(f"⚠️[SPLIT] No parts written; copied original -> {dst}")
    except Exception as e:
        logging.error(f"❌[SPLIT] Fallback copy also failed: {e}")

    # CLEANUP: remove any empty PDFs (0 KB) left behind 
    for z in Path(parts_folder).glob("*.pdf"):
        try:
            if os.path.getsize(z) == 0:
                logging.warning(f"⚠️[CLEANUP] Removing empty PDF: {z}")
                z.unlink()
        except Exception:
            pass

    return outputs

def pdf_split_or_copy(file_path,folder_output,file_out_path, delete = False):
    MAX_MB = MAX_PDF_MB   # adjust as you like (e.g., 12–15 for scans)
    MAX_PAGES = MAX_PDF_PAGES  # e.g., 100 for very large files; use 15–30 for smaller parts

    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    try:
        pages = len(PdfReader(file_path, strict=False).pages)
    except Exception:
        pages = MAX_PAGES + 1  # force split if unreadable

    need_split = (size_mb > MAX_MB) or (pages > MAX_PAGES)

    if need_split:
        logging.info(f'spliting into {Path(folder_output) / _safe_slug(Path(file_path).stem)}')
        parts_dir = Path(folder_output) / _safe_slug(Path(file_path).stem)
        parts = split_pdf_by_size_and_pages(
            file_path, parts_dir, max_size_mb=MAX_MB, max_pages_per_part=MAX_PAGES
        )
        FINAL_META.record(action= "pdf_split",status= "Success",
            source_path=file_path, target_path=folder_output, #str(parts_dir),
            t_start=time.time(), pages_out=pages)
    elif file_path == file_out_path:
        t0 = time.time()
        logging.info(f'✅ PDF {file_path} no splited')
        return
    else:
        t0 = time.time()
        shutil.copy(file_path, file_out_path)
        logging.info(f'✅ PDF {file_path} copied, no split')
        FINAL_META.record(action= "copy",status= "Success",source_path=file_path, target_path=file_out_path,
            t_start=t0, t_end=time.time())
    
    if delete:
        os.remove(file_path)
        #print(f'File {file_path} removed')