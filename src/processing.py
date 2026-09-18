import mimetypes
import os
import logging
import re
import time
from PIL import Image
import shutil
from pypdf import PdfReader
from pathlib import Path
from PIL import ImageOps
import gc

from __init__ import (EMAIL_EXTS, 
                    IMAGE_EXTS, 
                    FINAL_META,
                    ZIP_EXTS, 
                    DOC_EXTS,
                    AUDIO_EXTS,
                    EXC_EXTS,
                    MAX_PDF_MB,
                    MAX_PDF_PAGES,
                    backup_root
)
from utils_phase2 import (
    sanitize_and_truncate_filename, 
    ensure_unique_filename,is_likely_logo, 
    _find_claim_dir_for_path, 
    _latest_metadata_file,
    _wait_stable,
    _safe_slug
)
from email_utils import process_email_file
#from metadata import FINAL_META
from converters import (convert_heic_to_jpg_for_pdf, 
                        unzip_files, 
                        convert_doc_to_pdf,
                        convert_video_to_mp4,
                        convert_audio_to_mp3,
                        compress_video
)
from pdf_utils import split_pdf_by_size_and_pages, pdf_split_or_copy
from notifications import send_email_alert


def process_file(file_path, folder_output, delete=False, claim_num=None, max_archive_depth=6, current_depth=0, prefix = 1):

    mime_type, encoding = mimetypes.guess_type(file_path)
    orig_filename = os.path.basename(file_path)
    filename = sanitize_and_truncate_filename(folder_output, orig_filename)
    filename = ensure_unique_filename(folder_output, filename)
    file_out_path = os.path.join(folder_output, filename)
    ext = os.path.splitext(filename)[1].lower()

    # --- locate original metadata once (for actor columns) ---
    claim_folder = _find_claim_dir_for_path(FINAL_META.root, file_path)
    actor_source_meta = _latest_metadata_file(
        claim_folder)  # skips Final_Metadata.xlsx
    

    # --- FOLDER FILES ---
    if os.path.isdir(file_path):
        for file in os.scandir(file_path):
            _path, _ext = os.path.splitext(file)
            src = _path + _ext
            process_file(src, file_path, delete = delete, prefix = prefix)
            prefix += 1
    

    # --- ZIP FILES ---
    elif ext in ZIP_EXTS:
        t0 = time.time()
        try:
            unzip_files(file_path, folder_output, ext)
            return file_out_path
            #batch_process(folder_output,folder_output)
        except Exception as e:
            logging.error(f"❌[ZIP] Zip file NO extracted {file_path}: {e}")
    

    # --- EMAIL ---
    elif ext in EMAIL_EXTS:
        try:
            process_email_file(file_path, folder_output, prefix = prefix)
            if delete:
                try:
                    gc.collect()
                    os.remove(file_path)
                    logging.info(f'File {file_path} removed')
                except Exception as e:
                    logging.error(f"File {file_path} couldn't deleted: {e}")
                    pass
            return file_out_path
        except Exception as e:
            logging.error(f"❌Email process failed: {e}")
        return None
    

    # --- IMAGES ---
    elif ext in IMAGE_EXTS:
        base = os.path.splitext(filename)[0]
        dst_path = os.path.join(folder_output, base + "_converted.jpg")

        # --- Tiny/logo filter ---
        try:
            with open(file_path, "rb") as f:
                img_bytes = f.read()
            if is_likely_logo(os.path.basename(file_path), img_bytes):
                logging.info(f"✅ Tyni image {file_path} skipped")
                FINAL_META.record(action="image->jpg",status= "Skipped",
                    source_path=file_path, reason="tiny-image", 
                    t_start=time.time(),actor_source_meta=actor_source_meta)
                return None
        except Exception as e:
            logging.error(f"❌ Tyni image {file_path} error {e}")
            FINAL_META.record(action="image->jpg",status= "Skipped",
                source_path=file_path, reason=f"tiny-check-error {e}",
                t_start= time.time(),actor_source_meta=actor_source_meta)
            return None

        try:
            t0 = time.time()
            if ext == ".heic":
                dst_path = os.path.join(folder_output, base + "_converted.jpg")
                #dst_path = os.path.splitext(file_path)[0] + "_converted.jpg"
                out = convert_heic_to_jpg_for_pdf(
                    file_path, dst_path, max_size=(1500, 1500))
                return out if out and _wait_stable(out) else None

            with Image.open(file_path) as im:
                im.load()

                try:
                    im = ImageOps.exif_transpose(im)
                except Exception as e:
                    logging.warning(f"⚠️Could not apply EXIF orientation for {file_path}: {e}")

                if im.mode == "P" and "transparency" in im.info:
                    im = im.convert("RGBA")

                if im.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    alpha = im.split()[-1]
                    bg.paste(im.convert("RGB"), mask=alpha)
                    im = bg
                if im.mode != "RGB":
                    im = im.convert("RGB")

                if im.width > 1500 or im.height > 1500:
                    im.thumbnail((1500, 1500), Image.LANCZOS)

                im.save(dst_path, format="JPEG", quality=75, optimize=True)
            
            if delete:
                os.remove(file_path)
                logging.info(f'File {file_path} removed')

            FINAL_META.record(action= "image->jpg", status= "Success",
                source_path=file_path, target_path=dst_path, 
                t_start=t0, t_end=time.time(),actor_source_meta=actor_source_meta)
            return dst_path if _wait_stable(dst_path) else None

        except Exception as e:
            logging.error(f"❌Image handling failed: {e}")
            FINAL_META.record(action="image->jpg",status= "Failure",
                source_path=file_path, reason=str(e),
                t_start=time.time(),actor_source_meta=actor_source_meta)
            return None
        

    # --- DOCS -> PDF ---
    elif ext in DOC_EXTS:
        try:
            convert_doc_to_pdf(file_path, folder_output)
            if delete:
                os.remove(file_path)
                logging.info(f'File {file_path} removed')
            return file_out_path
        except Exception as e:
            logging.error(f"Doc conversion failed: {e}")
        return None
    
    
    # --- EXCEL copy ---
    elif ext in EXC_EXTS:
        t0 = time.time()
        try:
            shutil.copy(file_path, file_out_path)
            if delete:
                os.remove(file_path)
                logging.info(f'File {file_path} removed')
            logging.info(f"✅ File {file_path} successfully copied")
            FINAL_META.record(action = "copy",status = "Success",source_path=file_path, target_path=file_out_path, t_start=t0, t_end = time.time())
            return file_out_path
        except Exception as e:
            logging.error(f"❌ File copy failed: {e}")
            FINAL_META.record(action="copy",status= "Failure", reason=str(e), t_start=t0, t_end = time.time())
        return None
    

    # --- VIDEO -> MP4 ---
    elif mime_type and mime_type.startswith('video') and ext not in ('.mp4', '.mov'):
        try:
            convert_video_to_mp4(file_path, folder_output)
            if delete:
                os.remove(file_path)
                logging.info(f'File {file_path} removed')
            return file_out_path
        except Exception as e:
            logging.error(f"❌Video conversion failed: {e}")
        return None
    

    # --- COMPRESS VIDEO -> MP4 - MOV---
    elif mime_type and mime_type.startswith('video') and ext in ('.mp4', '.mov'):
        try:
            compress_video(file_path, file_out_path)
            if delete:
                os.remove(file_path)
                logging.info(f'File {file_path} removed')
            return file_out_path
        except Exception as e:
            logging.error(f"❌Video compress failed: {e}")
        return None
    
    
    # --- AUDIO -> MP3 ---
    elif (mime_type and mime_type.startswith('audio')) or (ext in AUDIO_EXTS):
        try:
            convert_audio_to_mp3(file_path, folder_output)
            if delete:
                os.remove(file_path)
                logging.info(f'File {file_path} removed')
            return file_out_path
        except Exception as e:
            logging.error(f"❌Audio conversion failed: {e}")
        return None
    

    # --- PDF: split or copy using robust splitter (works for scanned too) ---
    elif ext == '.pdf':
        try:
            pdf_split_or_copy(file_path, folder_output, file_out_path, delete = delete)
            return file_out_path

        except Exception as e:
            logging.error(f'❌ PDF split failed: {e}')
            #logging.error(str(parts_dir))
            #logging.error(len(str(parts_dir)))
            FINAL_META.record(action="pdf",status= "Failure", reason=str(e), t_start=time.time())
        return None


    # --- DEFAULT: copy unknown ---
    else:
        t0 = time.time()
        try:
            shutil.copy(file_path, file_out_path)
            logging.info(f'✅Unknown file copied {file_path}')
            if delete:
                os.remove(file_path)
                logging.info(f'File {file_path} removed')
            FINAL_META.record(action="copy",status= "Success",source_path=file_path, target_path=file_out_path, t_start=t0, t_end=time.time())
            return file_out_path
        except Exception as e:
            logging.error(f'❌Unknown file to copi: {e}')
            FINAL_META.record(action="copy",status= "Failure", reason=str(e),source_path=file_path, t_start=t0, t_end=time.time())
        return None


def batch_process(input_root, output_root, backup_root):

    produced = []
    result = ''
    for dirpath, dirnames, filenames in os.walk(input_root):
        rel_dir = os.path.relpath(dirpath, input_root)
        out_dir = os.path.join(output_root, rel_dir)
        os.makedirs(out_dir, exist_ok=True)
        backup_dir = os.path.join(backup_root, rel_dir)
        os.makedirs(backup_dir, exist_ok=True)

        
        claim_match = re.search(r'\d{8,}', dirpath)
        claim_num = claim_match.group() if claim_match else None
        prefix = 1
        # A) run the single-file pipeline (returns a produced JPG path when applicable)
        for fn in filenames:
            src = os.path.join(dirpath, fn)
            ext = os.path.splitext(src)[1].lower()
            #src_backup = os.path.join(backup_dir,fn)
            logging.info(
                f"✅Processing file {src}, to {out_dir}")
            result = process_file(src, out_dir, claim_num=claim_num, prefix=prefix)
            if ext in EMAIL_EXTS:
                prefix += 1
            if result:# and os.path.exists(result):
                produced.append(result)
            
            move_single_file(src, backup_dir)
    cleanup_empty_dirs(input_root)

    return len(produced)


def move_single_file(src_file_path, dest_folder_path):
    """
    Moves a single file to the destination folder with retry logic and copy fallback.
    """
    import gc
    gc.collect()
    src_path = Path(src_file_path)
    dst_folder = Path(dest_folder_path)
    dst_path = dst_folder / src_path.name # Full destination path including filename

    if not src_path.exists():
        logging.warning(f"⚠️ Source file not found (already moved?): {src_path}")
        return

    moved_success = False
    max_retries = 5
    
    for attempt in range(max_retries):
        try:
            shutil.move(str(src_path), str(dst_path))
            logging.info(f'✅ [MOVED] {src_path.name} -> {dst_path}')
            moved_success = True
            break
        except (PermissionError, OSError) as e:
            if attempt < max_retries - 1:
                logging.info(f"🔄 File locked, retry {attempt + 1} for {src_path.name}...")
                time.sleep(5)
                gc.collect()
            else:
                # Fallback: Copy and try to delete
                try:
                    shutil.copy2(src_path, dst_path)
                    os.remove(src_path)
                    logging.info(f"⚠️ Copied {src_path.name} and deleted source (Move failed).")
                    moved_success = True
                except Exception as copy_err:
                    logging.error(f"❌ Critical failure moving {src_path.name}: {copy_err}")
                    

    if not moved_success:
        
        subject = "🚨 Fail to move one file"
        body = f'🚨 File {src_path} failed to move to {dst_path}\n'
        body += f'#️⃣ Please check and manually move it if need.\n'
        body += f'\nLogs: Skipped locked file: {src_path} \n'
        body += f'\nAction to take (Support team):\n'
        body += f'  - Go to File Share Server \n'
        body += f'  - Computer manager. \n'
        body += f'  - Share Folders > Open Files.\n'
        body += f'  - Look for the file {src_path}, rigth click, close.\n'
        body += f'  - Go to 03_Converted > [Same BOT] > [Same LOB] and check if the claim number folder exist there. \n'
        body += f'\n      -If NOT exist leave it in the Original folder waiting for the next loop. \n'
        body += f'\n      -If EXIST move (cut and paste) the claim folder from "01_Original > [BOT] > [LOB]" to "02_Converted_Complete > [BOT] > [LOB]"  \n'
        send_email_alert(body, subject)
        logging.warning(f"Skipped locked file: {src_path}")

def cleanup_empty_dirs(root_path):
    """
    Walks bottom-up to delete empty directories.
    """
    for root, dirs, files in os.walk(root_path, topdown=False):
        for name in dirs:
            dir_to_check = Path(root) / name
            try:
                dir_to_check.rmdir() # Only removes if empty
                logging.info(f"🗑️ Deleted empty folder: {dir_to_check}")
            except OSError:
                pass # Folder not empty

def moving_files(input_root,backup_root):
    import gc
    gc.collect()
    try:
        input_path = Path(input_root)
        output_path = Path(backup_root)
        for src_path in input_path.rglob("*"):
            if not src_path.is_file():
                continue
            # Preserve relative path inside backup_root
            rel_path = src_path.relative_to(input_path)
            dst_path = output_path / rel_path

            # Ensure destination subfolder exists
            dst_path.parent.mkdir(parents=True, exist_ok=True)

            moved_success = False
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    shutil.move(str(src_path), str(dst_path))
                    logging.info(f'✅[MOVING]Folder {src_path} moved to {dst_path}')
                    moved_success = True
                    break
                except (PermissionError, OSError) as e:
                    if attempt < max_retries - 1:
                        logging.info(f"🔄 File locked, retry {attempt + 1} for {src_path.name}...")
                        time.sleep(5)
                    else:
                        try:
                            shutil.copy2(src_path, dst_path)
                            logging.warning(f"⚠️ Copied {src_path.name} but couldn't delete source (Locked).")
                        except Exception as copy_err:
                            logging.error(f"❌ Critical failure on {src_path}: {copy_err}")
            
            if not moved_success:
                #print(f"Skipped locked file: {src_path} - {e}")
                #send a email
                subject = "🚨 Fail to move one file"
                body = f'🚨 File {src_path} failed to move to {dst_path}\n'
                body += f'#️⃣ Please check and manually move it if need.\n'
                body += f'\nLogs: Skipped locked file: {src_path} - {e} \n'
                body += f'\nAction to take (Support team):\n'
                body += f'  - Go to File Share Server \n'
                body += f'  - Computer manager. \n'
                body += f'  - Share Folders > Open Files.\n'
                body += f'  - Look for the file {src_path}, rigth click, close.\n'
                body += f'  - Go to {src_path} and delete the file.\n'
                send_email_alert(body, subject)
                logging.warning(f"Skipped locked file: {src_path}")

        # Clean up empty folders (bottom-up)
        for root, dirs, files in os.walk(input_path, topdown=False):
            for name in dirs:
                dir_to_check = Path(root) / name
                try:
                    # Only removes if empty
                    dir_to_check.rmdir()
                    logging.info(f"🗑️ Deleted empty folder: {dir_to_check}")
                except OSError:
                    pass # Folder not empty, which is expected if files were locked
    except Exception as e:
        print(f'Error moving - {e}')
        logging.error(f'❌[MOVING]Error moving - {e}')
        subject = "🚨 Fail to move one file"
        body = f'🚨 File {src_path} failed to move to {dst_path}\n'
        body += f'#️⃣ Please check and manually move it if need.\n'
        body += f'\nLogs: Skipped locked file: {src_path} - {e} \n'
        body += f'\nAction to take (Support team):\n'
        body += f'  - Go to File Share Server \n'
        body += f'  - Computer manager. \n'
        body += f'  - Share Folders > Open Files.\n'
        body += f'  - Look for the file {src_path}, rigth click, close.\n'
        body += f'  - Go to {src_path} and delete the file.\n'
        send_email_alert(body, subject)
