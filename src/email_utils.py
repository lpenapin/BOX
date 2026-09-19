import os
import time
import glob
import shutil
import logging
import tempfile
import subprocess
import gc
from pathlib import Path
from datetime import datetime
from email import policy
from email.parser import BytesParser
from PIL import Image, ImageOps

try:
    import extract_msg
except ImportError:
    extract_msg = None

from utils_phase2 import (
    sanitize_and_truncate_filename, 
    ensure_unique_filename, 
    is_likely_logo, 
    _wait_stable,
    _find_claim_dir_for_path,
    _latest_metadata_file
)
from converters import (
    convert_heic_to_jpg_for_pdf, 
    convert_images_to_pdf,
    unzip_files,
    convert_doc_to_pdf
)
from __init__ import (
    IMAGE_EXTS, 
    MIN_IMAGE_SIZE, 
    FINAL_META, 
    ZIP_EXTS,
    EMAIL_EXTS,
    DOC_EXTS,
    CSHARP_EXE_PATH,
    ASPOSE_LIC_PATH
)
from email_to_pdf_converter import convert_email_to_pdf


# ── Hierarchical naming helpers ──────────────────────────────────────────────

def _build_prefix(level: int, att_idx: int, parent_chain: str) -> str:
    """
    Compose a hierarchical file-name prefix.

    Examples
    --------
    (0, 0, "")                  → "L0_A00"           ← body/images of root email
    (0, 2, "")                  → "L0_A02"           ← 2nd attachment of root email
    (1, 0, "L0_A02")            → "L1_A00_L0_A02"   ← body of email nested at L0_A02
    (1, 3, "L0_A03")            → "L1_A03_L0_A03"   ← 3rd att of email nested at L0_A03
    (2, 0, "L1_A03_L0_A03")     → "L2_A00_L1_A03_L0_A03"
    """
    base = f"L{level}_A{att_idx:02d}"
    return f"{base}_{parent_chain}" if parent_chain else base


# ── convert_extr_img_to_jpg – unchanged ──────────────────────────────────────

def convert_extr_img_to_jpg(images):
    final_jpgs = []
    for raw_img in sorted(images, key=lambda p: os.path.basename(p).lower()):
        t0 = time.time()
        raw_path = Path(raw_img)
        out_path = raw_path.with_stem(raw_path.stem + "_converted").with_suffix(".jpg")

        try:
            processed_path = None

            if raw_path.suffix.lower() == ".heic":
                processed_path = convert_heic_to_jpg_for_pdf(
                    str(raw_path), str(out_path), max_size=(1500, 1500)
                )
                if processed_path:
                    try:
                        raw_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                with Image.open(raw_path) as im:
                    im = ImageOps.exif_transpose(im)
                    if im.mode != "RGB":
                        im = im.convert("RGB")
                    im.thumbnail((1500, 1500), Image.LANCZOS)
                    im.save(out_path, "JPEG", quality=75, optimize=True)
                processed_path = str(out_path)

            if processed_path and _wait_stable(processed_path):
                final_jpgs.append(processed_path)
                logging.info(f"✅[IMG] Prepared image: {processed_path}")
                FINAL_META.record(
                    action="image->jpg", status="Success",
                    source_path=str(raw_path), target_path=processed_path,
                    t_start=t0, t_end=time.time()
                )

        except Exception as e:
            logging.error(f"❌[IMG] convert image failed {raw_img}: {e}")

    return final_jpgs


# ── nested_email ──────────────────────────────────────────────────────────────

def nested_email(file_path, output_folder, att_idx, level, parent_chain, email_idx):
    """
    Process a nested email attachment recursively.

    The file has already been saved with its hierarchical prefix by Phase B,
    so no renaming is needed here.  We only ensure the .eml extension is present,
    then recurse into process_email_file with an incremented level and the
    updated parent chain.

    New parent_chain for the child level:
        e.g. att_idx=2, level=0, parent_chain=""  →  new_parent_chain="L0_A02"
            att_idx=3, level=1, parent_chain="L0_A03"  →  "L1_A03_L0_A03"
    """
    t0 = time.time()
    src_path = Path(file_path)

    try:
        # Guarantee a recognisable extension
        if not src_path.suffix:
            new_path = src_path.with_suffix(".eml")
            src_path.rename(new_path)
            src_path = new_path

        logging.info(f"✅[Nested Email] Processing: {src_path}")
        FINAL_META.record(
            action="Extract attached email", status="Success",
            source_path=file_path, target_path=str(src_path),
            t_start=t0, t_end=time.time()
        )

        # Build the parent-chain string that child files will inherit
        new_parent_chain = _build_prefix(level, att_idx, parent_chain)
        # e.g. "L0_A02"  →  children will be  "L1_A00_L0_A02", "L1_A01_L0_A02", …

        process_email_file(
            str(src_path), output_folder,
            level=level + 1,
            parent_chain=new_parent_chain,
            email_idx = email_idx
        )

        gc.collect()
        src_path.unlink(missing_ok=True)
        logging.info(f"✅[Nested Email] Deleted processed attach → {src_path}")

    except Exception as e:
        logging.error(f"❌[Nested Email] Failed {src_path}: {e}")
        FINAL_META.record(
            action="Extract attached email", status="Failure",
            reason=f"Reason: {e}", t_start=t0, t_end=time.time()
        )


# ── handle_attachment_file ────────────────────────────────────────────────────

def handle_attachment_file(file_path, original_filename, output_folder,
                            att_idx, level, parent_chain, collections, email_idx):
    """
    Route an already-extracted (and already-prefixed) attachment to the
    appropriate handler.

    Parameters
    ----------
    att_idx      : int  – index assigned to this attachment (A01, A02, …)
    level        : int  – current nesting depth
    parent_chain : str  – hierarchical suffix inherited from the parent email
    """
    file_path = Path(file_path)
    ext = file_path.suffix.lower()

    # NESTED EMAIL
    if not ext or ext in EMAIL_EXTS:
        nested_email(str(file_path), output_folder, att_idx, level, parent_chain, email_idx)
        return True

    # ZIP
    elif ext in ZIP_EXTS:
        unzip_files(str(file_path), output_folder, ext, delete=True)
        return False

    # DOCUMENT → PDF  (input file is already prefixed, so the output PDF
    #                   inherits the prefix from the stem automatically)
    elif ext in DOC_EXTS:
        convert_doc_to_pdf(str(file_path), output_folder, delete=True)
        return False

    # IMAGE
    elif ext in IMAGE_EXTS:
        try:
            file_size = file_path.stat().st_size
            with open(file_path, "rb") as f:
                data = f.read()

            if file_size > MIN_IMAGE_SIZE and not is_likely_logo(original_filename, data):
                collections['extracted_images'].append(str(file_path))
            elif is_likely_logo(original_filename, data):
                collections['logo_images'].append(str(file_path))
            else:
                collections['other_files'].append(str(file_path))
        except Exception:
            collections['other_files'].append(str(file_path))
        return False

    # OTHER
    else:
        collections['other_files'].append(str(file_path))
        return False


# ── cleanup helper – unchanged ────────────────────────────────────────────────

def cleanup_outlook_temp_files():
    temp_dir = tempfile.gettempdir()
    for path in glob.glob(os.path.join(temp_dir, "Outlook-*")):
        try:
            os.remove(path)
        except Exception:
            pass


# ── process_email_file ────────────────────────────────────────────────────────

def process_email_file(email_path, output_folder, level=0, parent_chain="", email_idx=1):
    """
    Convert one email (EML or MSG) to a set of PDFs with hierarchical names.

    Naming convention
    -----------------
    A00  → Body PDF  + Images PDF  (always index 0 for the email's own content)
    A01+ → attachments, numbered in extraction order

    Full prefix examples for a 3-level chain:
        Root email body      → L0_A00_EmailBody_….pdf
        Root att #1 (PDF)    → L0_A01_….pdf
        Root att #2 (email)  → L0_A02_….eml          [input to next recursion]
          ↳ L1 body          → L1_A00_L0_A02_EmailBody_….pdf
          ↳ L1 att #1        → L1_A01_L0_A02_….pdf

    Parameters
    ----------
    level        : int  – nesting depth (0 = root email)
    parent_chain : str  – prefix chain of the parent email attachment, e.g.
                          "L0_A02" or "L1_A03_L0_A03".  Empty string at root.

    Phases
    ------
    A. Convert body to PDF.
    B. Extract attachments; assign A01, A02, … and save with hierarchical prefix.
    C. Route / process each attachment.
    D. Convert collected images to a single PDF.
    E. Clean up temp files.
    """
    t0_func = time.time()

    email_path = Path(email_path)
    base_name  = email_path.stem

    start_with = f'E{email_idx}_{parent_chain}'
    if parent_chain and base_name.startswith(start_with):
        # Remove the prefix and the following underscore
        base_name = base_name[len(start_with):].lstrip('_')

    # Create the prefix starting with En_
    # level=0, email_idx=1 -> E1_L0_A00
    # level=1 (nested), email_idx=1 -> E1_L1_A01_L0_A02...
    current_prefix = f"E{email_idx}_L{level}_A00"

    # Apply the full chain if it's a nested email
    if parent_chain:
        body_prefix = f"E{email_idx}_L{level}_A00_{parent_chain}"
    else:
        body_prefix = current_prefix

    # A00 is always reserved for this email's own body and images
    #body_prefix   = _build_prefix(level, 0, parent_chain)   # e.g. "L1_A00_L0_A02"
    #images_prefix = _build_prefix(level, 0, parent_chain)

    email_pdf_name = ensure_unique_filename(
        output_folder,
        sanitize_and_truncate_filename(
            output_folder, f"{body_prefix}_Body_{base_name}.pdf"
        )
    )
    images_pdf_name = ensure_unique_filename(
        output_folder,
        sanitize_and_truncate_filename(
            output_folder, f"{body_prefix}_Images_{base_name}.pdf"
        )
    )

    email_pdf_path  = os.path.join(output_folder, email_pdf_name)
    images_pdf_path = os.path.join(output_folder, images_pdf_name)

    collections = {'extracted_images': [], 'logo_images': [], 'other_files': []}

    try:
        # ── PHASE A: Body → PDF ───────────────────────────────────────────────
        t0 = time.time()
        try:
            num_pages = convert_email_to_pdf(str(email_path), email_pdf_path)
            logging.info(f"✅[EMAIL] Created email PDF: {email_pdf_path}")
            FINAL_META.record(
                action="email->pdf", status="Success",
                source_path=str(email_path), target_path=email_pdf_path,
                pages_out=num_pages, t_start=t0, t_end=time.time()
            )
        except Exception as e:
            logging.error(f"❌[EMAIL] Body to PDF failed: {e}")
            FINAL_META.record(
                action="email->pdf", status="Failure",
                source_path=str(email_path), reason=f"Error: {e}",
                t_start=t0, t_end=time.time()
            )

        # ── PHASE B: Extract attachments with hierarchical prefix ─────────────
        #
        # att_idx starts at 1 (0 is reserved for body/images).
        # Each attachment is saved immediately with its full prefix so that all
        # downstream processing (doc→pdf, image conversion, …) inherits the name.
        #
        raw_attachments = []   # [(saved_path, original_filename, att_idx), …]
        att_idx = 1

        def _save_attachment(data: bytes, fname: str) -> tuple:
            """Write `data` to disk with the correct hierarchical prefix and return
            (saved_path, original_fname, att_idx)."""
            nonlocal att_idx
            # Format: E1_L0_A01, E1_L0_A02...
            hier_prefix = f"E{email_idx}_L{level}_A{att_idx:02d}"
            if parent_chain:
                hier_prefix = f"{hier_prefix}_{parent_chain}"
            prefixed_fname = f"{hier_prefix}_{fname}"

            #hier_prefix   = _build_prefix(level, att_idx, parent_chain)
            #prefixed_fname = f"{hier_prefix}_{fname}"

            safe_name = ensure_unique_filename(
                output_folder,
                sanitize_and_truncate_filename(output_folder, prefixed_fname)
            )
            out_path = os.path.join(output_folder, safe_name)
            with open(out_path, "wb") as w:
                w.write(data)
            entry = (out_path, fname, att_idx)
            att_idx += 1
            return entry

        # ── EML ──
        if email_path.suffix.lower() == ".eml":
            with open(email_path, "rb") as f:
                msg = BytesParser(policy=policy.default).parse(f)

            ctr = 0
            for part in msg.iter_attachments():
                fname = part.get_filename()
                data  = part.get_payload(decode=True)
                if not data:
                    continue
                if not fname:
                    ctype     = part.get_content_type()
                    ext_guess = ctype.split("/")[-1] if "/" in ctype else "bin"
                    fname     = f"att_{ctr}.{ext_guess}"
                if fname.lower().endswith(".hei"):
                    fname = fname[:-4] + ".heic"
                raw_attachments.append(_save_attachment(data, fname))
                ctr += 1

        # ── MSG (via C#) ──
        elif email_path.suffix.lower() == ".msg":
            if not os.path.exists(CSHARP_EXE_PATH):
                logging.error("❌[EMAIL] C# Tool not found.")
                return

            with tempfile.TemporaryDirectory() as temp_att_dir:
                try:
                    subprocess.run(
                        [CSHARP_EXE_PATH, str(email_path), temp_att_dir, ASPOSE_LIC_PATH],
                        check=True
                    )
                    for fname in os.listdir(temp_att_dir):
                        clean_fname = fname.replace("\x00", "")
                        if clean_fname.lower().endswith(".hei"):
                            clean_fname = clean_fname[:-4] + ".heic"
                        with open(os.path.join(temp_att_dir, fname), "rb") as f:
                            data = f.read()
                        raw_attachments.append(_save_attachment(data, clean_fname))

                except subprocess.CalledProcessError as e:
                    logging.error(f"❌[EMAIL] MSG Extraction failed: {e}")
        else:
            logging.warning(f"Skipping unsupported email format: {email_path}")
            return

        # ── PHASE C: Route / process each attachment ──────────────────────────
        for saved_path, original_name, a_idx in raw_attachments:
            handle_attachment_file(
                saved_path, original_name, output_folder,
                a_idx, level, parent_chain, collections, email_idx
            )

        # ── PHASE D: Images → PDF ─────────────────────────────────────────────
        final_jpgs = convert_extr_img_to_jpg(collections['extracted_images'])
        if final_jpgs:
            if convert_images_to_pdf(final_jpgs, images_pdf_path):
                logging.info(f"✅[EMAIL] Images merged → {images_pdf_path}")
        else:
            logging.info(f"ℹ️[EMAIL] No usable images for {base_name}")

        # ── PHASE E: Clean up ─────────────────────────────────────────────────
        for f in collections['extracted_images']:
            try: os.remove(f)
            except: pass

        for f in collections['logo_images']:
            try: os.remove(f)
            except: pass
            logging.info(f"🗑️[EMAIL] Deleted logo: {os.path.basename(f)}")

        for f in final_jpgs:
            try: os.remove(f)
            except: pass

    except Exception as outer:
        logging.critical(
            f"❌[EMAIL] Fatal error processing {email_path}: {outer}", exc_info=True
        )
    finally:
        cleanup_outlook_temp_files()