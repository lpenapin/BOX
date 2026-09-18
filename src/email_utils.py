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

# Librerías de terceros
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

def convert_extr_img_to_jpg(images):
    final_jpgs = []
    # Usamos Path para facilitar manejo de nombres
    for raw_img in sorted(images, key=lambda p: os.path.basename(p).lower()):
        t0 = time.time()
        raw_path = Path(raw_img)
        out_path = raw_path.with_stem(raw_path.stem + "_converted").with_suffix(".jpg")
        
        try:
            processed_path = None
            
            # Case HEIC
            if raw_path.suffix.lower() == ".heic":
                processed_path = convert_heic_to_jpg_for_pdf(str(raw_path), str(out_path), max_size=(1500, 1500))
                
                if processed_path:
                    try:
                        raw_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            
            # Case Others (JPG, PNG, etc)
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

def nested_email(file_path, output_folder, att_prefix, global_prefix):
    t0 = time.time()
    src_path = Path(file_path)

    try:
        original_name = src_path.name
        new_name = f"Attachment_{att_prefix:02d}_{original_name}"
        dest_path = src_path.with_name(new_name)
        src_path.rename(dest_path)
        src_path = dest_path

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

        process_email_file(str(src_path), output_folder, global_prefix)
        
        gc.collect()
        src_path.unlink(missing_ok=True)
        logging.info(f"✅[Nested Email] Deleted processed attach -> {src_path}")

    except Exception as e:
        logging.error(f"❌[Nested Email] Failed {src_path}: {e}")
        FINAL_META.record(
            action="Extract attached email", status="Failure",
            reason=f"Reason: {e}", t_start=t0, t_end=time.time()
        )

def handle_attachment_file(file_path, original_filename, output_folder, att_prefix, global_prefix, collections):

    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    
    # NESTED EMAIL
    if not ext or ext in EMAIL_EXTS:
        nested_email(str(file_path), output_folder, att_prefix, global_prefix)
        return True 

    # ZIP FILES
    elif ext in ZIP_EXTS:
        unzip_files(str(file_path), output_folder, ext, delete=True)
        return False

    # DOC
    elif ext in DOC_EXTS:
        convert_doc_to_pdf(str(file_path), output_folder, delete=True)
        return False

    # IMG
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

    # OTHERS
    else:
        collections['other_files'].append(str(file_path))
        return False

def cleanup_outlook_temp_files():
    temp_dir = tempfile.gettempdir()
    for path in glob.glob(os.path.join(temp_dir, "Outlook-*")):
        try:
            os.remove(path)
        except Exception:
            pass

def process_email_file(email_path, output_folder, prefix):
    """
    Phases:
    A. Convert Body to PDF.
    B. Extract adj EML o MSG.
    C. Proccess/Short adj.
    D. Convert images to PDF.
    E. clean up.
    """
    t0_func = time.time()
    
    # Files names
    email_path = Path(email_path)
    base_name = email_path.stem
    
    email_pdf_name = ensure_unique_filename(output_folder, sanitize_and_truncate_filename(output_folder, f"{prefix:03d}_EmailBody_{base_name}.pdf"))
    images_pdf_name = ensure_unique_filename(output_folder, sanitize_and_truncate_filename(output_folder, f"{prefix:03d}_Image_{base_name}.pdf"))
    
    email_pdf_path = os.path.join(output_folder, email_pdf_name)
    images_pdf_path = os.path.join(output_folder, images_pdf_name)

    # collections to agroup files
    collections = {
        'extracted_images': [],
        'logo_images': [],
        'other_files': []
    }

    try:
        # --- PHASE A: Convert Body to PDF ---
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

        # --- FASE B: Extract adj EML o MSG. ---
        raw_attachments = []
        
        # LOGIC EML
        if email_path.suffix.lower() == ".eml":
            with open(email_path, 'rb') as f:
                msg = BytesParser(policy=policy.default).parse(f)
            
            att_counter = 0
            for part in msg.iter_attachments():
                fname = part.get_filename()
                data = part.get_payload(decode=True)
                
                if not data: continue
                
                if not fname:
                    ctype = part.get_content_type()
                    ext_guess = ctype.split('/')[-1] if '/' in ctype else "bin"
                    fname = f"att_{att_counter}.{ext_guess}"
                
                if fname.lower().endswith(".hei"): fname = fname[:-4] + ".heic"

                if fname.lower().endswith(".pdf"):
                        safe_name = fname
                else:
                    safe_name = ensure_unique_filename(output_folder, sanitize_and_truncate_filename(output_folder, fname, prefix))
                out_path = os.path.join(output_folder, safe_name)
                
                with open(out_path, "wb") as w:
                    w.write(data)
                
                raw_attachments.append((out_path, fname))
                att_counter += 1

        # LOGIC MSG (Via C#)
        elif email_path.suffix.lower() == ".msg":
            if not os.path.exists(CSHARP_EXE_PATH):
                logging.error("❌[EMAIL] C# Tool not found.")
                return

            with tempfile.TemporaryDirectory() as temp_att_dir:
                try:
                    subprocess.run([CSHARP_EXE_PATH, str(email_path), temp_att_dir, ASPOSE_LIC_PATH], check=True)
                    
                    # Move files from C# temp to final folder
                    for fname in os.listdir(temp_att_dir):
                        clean_fname = fname.replace('\x00', '')
                        if clean_fname.lower().endswith(".hei"): clean_fname = clean_fname[:-4] + ".heic"
                        
                        temp_file_path = os.path.join(temp_att_dir, fname)
                        
                        if fname.lower().endswith(".pdf"):
                            safe_name = fname
                        else:
                            safe_name = ensure_unique_filename(output_folder, sanitize_and_truncate_filename(output_folder, fname, prefix))
                        final_out_path = os.path.join(output_folder, safe_name)
                        
                        shutil.copy2(temp_file_path, final_out_path)
                        raw_attachments.append((final_out_path, clean_fname))
                        
                except subprocess.CalledProcessError as e:
                    logging.error(f"❌[EMAIL] MSG Extraction failed: {e}")

        else:
            logging.warning(f"Skipping unsupported email format: {email_path}")
            return

        # --- FASE C: Proccess/Short adj. ---
        att_idx = 1
        for saved_path, original_name in raw_attachments:
            is_nested = handle_attachment_file(
                saved_path, original_name, output_folder, att_idx, prefix, collections
            )
            if is_nested:
                att_idx += 1

        # --- FASE D: Convert images to PDF. ---
        final_jpgs = convert_extr_img_to_jpg(collections['extracted_images'])

        if final_jpgs:
            if convert_images_to_pdf(final_jpgs, images_pdf_path):
                logging.info(f"✅[EMAIL] Images merged -> {images_pdf_path}")
        else:
            logging.info(f"ℹ️[EMAIL] No usable images found for {base_name}")

        # --- FASE E: clean up. ---
        for f in collections['extracted_images']:
            try: os.remove(f) 
            except: pass
            
        # logos
        for f in collections['logo_images']:
            try: os.remove(f) 
            except: pass
            logging.info(f"🗑️[EMAIL] Deleted logo: {os.path.basename(f)}")
            
        # JPGs intermedios
        for f in final_jpgs:
            try: os.remove(f)
            except: pass

    except Exception as outer:
        logging.critical(f"❌[EMAIL] Fatal error processing {email_path}: {outer}", exc_info=True)
    finally:
        cleanup_outlook_temp_files()
