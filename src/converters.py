import time
from PIL import Image
import logging
import os
import shutil
import ffmpeg
from fpdf import FPDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import textwrap
from pydub import AudioSegment
import matplotlib.pyplot as plt

from utils_phase2 import sanitize_and_truncate_filename, ensure_unique_filename, unZip
from __init__ import FINAL_META, ZIP_EXTS
from pdf_utils import split_pdf_by_size_and_pages


def convert_audio_to_mp3(audio_path, output_folder):
    """
    Converts any audio file to MP3, saves in output_folder.
    Appends a row to Final_Metadata.xlsx (per-claim).
    Returns the MP3 path, or None on failure.
    """
    import time

    t0 = time.time()

    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    mp3_filename = sanitize_and_truncate_filename(
        output_folder, base_name + '.mp3')
    mp3_filename = ensure_unique_filename(output_folder, mp3_filename)
    mp3_path = os.path.join(output_folder, mp3_filename)

    try:
        audio = AudioSegment.from_file(audio_path)
        audio.export(mp3_path, format="mp3", bitrate="128k")
        logging.info(f"✅[AUDIO] Converted to MP3: {mp3_path}")

        # ✅ record success
        FINAL_META.record(
            action="audio->mp3",
            status="Success",
            source_path=audio_path,
            target_path=mp3_path,
            t_start=t0, t_end=time.time()
        )
        return mp3_path

    except Exception as e:
        logging.error(f"❌[AUDIO ERROR] Failed to convert {audio_path}: {e}")

        # ❌ record failure
        FINAL_META.record(
            action="audio->mp3",
            status="Failure",
            source_path=audio_path,
            reason=str(e),
            t_start=t0, t_end=time.time()
        )
        return None


def convert_video_to_mp4(video_path, output_folder):

    def get_codecs(file_path):
        import json
        import subprocess
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)

        video_codec = None
        audio_codec = None

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and not video_codec:
                video_codec = stream.get("codec_name")
            elif stream.get("codec_type") == "audio" and not audio_codec:
                audio_codec = stream.get("codec_name")

        return video_codec, audio_codec

    
    """
    Convert any video to H.264/AAC MP4 via ffmpeg.
    Writes a row to Final_Metadata.xlsx (per-claim).
    """
    import subprocess
    from subprocess import PIPE
    import time

    t0 = time.time()

    base_name = os.path.splitext(os.path.basename(video_path))[0]
    mp4_filename = sanitize_and_truncate_filename(
        output_folder, base_name + '.mp4')
    mp4_filename = ensure_unique_filename(output_folder, mp4_filename)
    out_path = os.path.join(output_folder, mp4_filename)

    video_codec, audio_codec = get_codecs(video_path)
    logging.info(f"-->Video Codec:{video_codec}")
    logging.info(f'-->Audio Codec:{audio_codec}')
    if video_codec == "hevc" and audio_codec == None:
        # Lossless remux (instant, no size increase)
        cmd = ["ffmpeg", "-y", "-i", video_path, "-c:v", "copy", out_path]
        logging.info('>>>Video already uses standard codecs')
    else:
        logging.info('>>>Video NOT uses standard codecs')
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            out_path
        ]

    try:
        subprocess.run(cmd, check=True, stdout=PIPE, stderr=PIPE, text=True)
        logging.info(f"✅Converted video {video_path} to {out_path}")

        # ✅ record success (no 'tool' column)
        FINAL_META.record(
            action="video->mp4",
            status="Success",
            source_path=video_path,
            target_path=out_path,
            t_start=t0, t_end=time.time()
        )

    except subprocess.CalledProcessError as e:
        msg = e.stderr.strip() or e.stdout.strip() or str(e)
        logging.error(f"❌Error converting video: {msg}")

        # ❌ record failure
        FINAL_META.record(
            action="video->mp4",
            status="Failure",
            source_path=video_path,
            reason=msg,
            t_start=t0, t_end=time.time()
        )

    except Exception as e:
        logging.error(f"❌Error converting video: {e}")

        # ❌ record failure
        FINAL_META.record(
            action="video->mp4",
            status="Failure",
            source_path=video_path,
            reason=str(e),
            t_start=t0, t_end=time.time()
        )


def compress_video(input_path, output_path, crf=24):
    def get_video_info(input_path):
        """Probes the file to get codec and bitrate information."""
        probe = ffmpeg.probe(input_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        return {
            'codec': video_stream['codec_name'],
            'bitrate': int(video_stream.get('bit_rate', 0)),
            'width': int(video_stream.get('width', 0))
        }
    """
    Compresses MOV or MP4 files using H.264.
    :param input_path: Path to the source video
    :param output_path: Path to save the compressed video
    :param crf: Quality setting (18-28 is recommended; higher = smaller file)
    """
    try:
        t0 = time.time()
        if not os.path.exists(input_path):
            print(f"Error: {input_path} not found.")
            return

        print(f"Processing: {input_path}...")

        info = get_video_info(input_path)
        # it's already very compressed. Don't convert.
        if info['codec'] == 'hevc' and info['bitrate'] < 2500000 and info['bitrate'] > 0:
            print(f"Skipping {input_path}: Already highly compressed (HEVC @ {info['bitrate']//1000}kbps).")
            logging.info(f"✅[CONVERT-VIDEO]Skipping {input_path}: Already highly compressed (HEVC @ {info['bitrate']//1000}kbps).")
            shutil.copy(input_path, output_path)
            logging.info(f"✅[CONVERT-VIDEO] Copying {input_path} to {output_path}")
            FINAL_META.record(
            action="Copy Video",
            status="Success",
            source_path=input_path,
            target_path=output_path,
            t_start=t0, t_end=time.time()
        )
        
        else: #compress
            """(
                ffmpeg
                .input(input_path)
                .output(output_path, vcodec='libx264', crf=crf, preset='slow')
                .run(overwrite_output=True)
            )"""

            # 1. Run the compression
            (
                ffmpeg
                .input(input_path)
                .output(output_path, vcodec='libx264', crf=crf, preset='fast')
                .run(overwrite_output=True, quiet=True) # quiet=True reduces console spam
            )

            # 2. Check the file sizes
            initial_size = os.path.getsize(input_path)
            final_size = os.path.getsize(output_path)
            
            # 3. The Safety Net: If the new file is bigger, scrap it and copy the original
            if final_size >= initial_size:
                shutil.copy(input_path, output_path)
                print(f"File bloated ({initial_size/1048576:.2f}MB -> {final_size/1048576:.2f}MB). Reverting to original.")
                logging.info(f"✅[CONVERT-VIDEO] Output larger than input. Keeping original: {input_path}")
                final_size = initial_size # Update final size for your records
                FINAL_META.record(
                action="Copy Video",
                status="Success",
                reason="Output larger than input. Keeping original",
                source_path=input_path,
                target_path=output_path,
                t_start=t0, t_end=time.time()
                )
            else:
                print(f"Reduction: {initial_size/1048576:.2f}MB -> {final_size/1048576:.2f}MB")
                logging.info(f"✅[CONVERT-VIDEO] Reduction: {initial_size/1048576:.2f}MB -> {final_size/1048576:.2f}MB")
                print(f"Successfully saved to: {output_path}")
                logging.info(f"✅[CONVERT-VIDEO] Successfully saved to: {output_path}")
                FINAL_META.record(
                action="Compress Video",
                status="Success",
                source_path=input_path,
                target_path=output_path,
                t_start=t0, t_end=time.time()
                )

    except ffmpeg.Error as e:
        print(f"An error occurred: {e.stderr.decode()}")
        logging.error(f"❌[CONVERT-VIDEO]An error occurred: {e.stderr.decode()}")


def convert_doc_to_pdf(doc_path, output_folder, delete = False):
    import subprocess
    from subprocess import PIPE
    t0 = time.time()

    base_name = os.path.splitext(os.path.basename(doc_path))[0]
    pdf_filename = sanitize_and_truncate_filename(
        output_folder, base_name + '.pdf')
    pdf_filename = ensure_unique_filename(output_folder, pdf_filename)
    pdf_path = os.path.join(output_folder, pdf_filename)

    cmd = [r"C:\Program Files\LibreOffice\program\soffice.exe",
        "--headless", "--convert-to", "pdf", "--outdir", output_folder, doc_path]
    try:
        subprocess.run(cmd, check=True, stdout=PIPE, stderr=PIPE, text=True)
        logging.info(f"Converted {doc_path} to PDF: {pdf_path}")

        try:
            split_pdf_by_size_and_pages(pdf_path, output_folder, max_size_mb=5)
        except Exception as split_err:
            logging.error(f"❌PDF split failed for {pdf_path}: {split_err}")

        if delete:
                os.remove(doc_path)
                logging.info(f'File {doc_path} removed')

        logging.info(f"✅ File .doc {doc_path} converted to .pdf {pdf_path}")
        FINAL_META.record(action="doc->pdf", status="Success",
                        source_path=doc_path, target_path=pdf_path,
                        t_start=t0, t_end=time.time())
    except subprocess.CalledProcessError as e:
        msg = e.stderr.strip() or e.stdout.strip() or str(e)
        logging.error(f"❌Error converting doc to PDF: {msg}")
        FINAL_META.record(action="doc->pdf", status="Failure",
                        source_path=doc_path, reason=msg,
                        t_start=t0, t_end=time.time())
    except Exception as e:
        logging.error(f"❌Error converting doc to PDF: {e}")
        FINAL_META.record(action="doc->pdf", status="Failure",
                        source_path=doc_path, reason=str(e),
                        t_start=t0, t_end=time.time())


def unzip_files(file, destFile, _ext, delete=False): 
    def contains_autorun(folder):
        for root, dirs, files in os.walk(folder):
            for _file in files:
                if os.path.basename(_file).lower() == "autorun.inf":
                    return True
        return False

    file_name = os.path.splitext(os.path.basename(file))
    #print(file_name)
    outFolder = os.path.join(destFile,file_name[0])
    os.makedirs(outFolder, exist_ok=True)
    try:
        t0 = time.time()
        tool = unZip(file,outFolder,_ext)
        if contains_autorun(outFolder):
            print("Autorun detected - skipping")
            shutil.rmtree(outFolder)
            if not delete:
                try:
                    shutil.copy(file, destFile)
                    logging.info(f'✅ZIP file with "autorun.inf" on it, copied, not extracted {file}')
                    FINAL_META.record(action="copy",status= "Success",source_path=file, target_path=destFile, t_start=t0, t_end=time.time(), reason="ZIP file with autorun.inf")
                    #return file
                except Exception as e:
                    logging.error(f'❌ ZIP file to copy: {e}')
                    FINAL_META.record(action="copy",status= "Failure", reason=str(e),source_path=file, t_start=t0, t_end=time.time())
                #return None
            else:
                logging.info(f'✅ZIP file with "autorun.inf" on it, copied, not extracted {file}')
                FINAL_META.record(action="copy",status= "Success",source_path=file, target_path=destFile, t_start=t0, t_end=time.time(), reason="ZIP file with autorun.inf") 
            return

        if delete:
            os.remove(file)
        logging.info(f"✅File {file} extracted, using {tool}")
        FINAL_META.record(action="Unzip", status="Success",
                        source_path=file, target_path=destFile,
                        t_start=t0, t_end=time.time())
        prefix = 1
        for file in os.scandir(outFolder):
            from processing import process_file #local import
            _path, _ext = os.path.splitext(file)
            src = _path + _ext
            process_file(src, outFolder, delete=True, prefix=prefix)
            prefix += 1
    except Exception as e:
        logging.error(f"❌An error occurred during extraction: {e}")
        FINAL_META.record(action="Unzip", status="Fail", 
                        reason=str(e), source_path=file,
                        t_start=t0, t_end=time.time())
    for value in os.scandir(outFolder):
        filePath, fileExt = os.path.splitext(value)
        file = filePath + fileExt
        if fileExt in ZIP_EXTS:
            unzip_files(outFolder,outFolder,fileExt)


def convert_txt_to_pdf(input_file, output_file=None, page_size=letter, font_size=12, margin=1*inch):
    """
    Convert a text file to PDF
    
    Args:
        input_file (str): Path to input text file
        output_file (str): Path to output PDF file (optional)
        page_size (tuple): Page size (default: letter)
        font_size (int): Font size (default: 12)
        margin (float): Page margin (default: 1 inch)
    """
    folder_name = os.path.basename(output_file)        
    # body pdf
    pdf_filename = sanitize_and_truncate_filename(
        output_file, f"NestedEmail_{folder_name}.pdf")
    pdf_filename = ensure_unique_filename(
        output_file, pdf_filename)
    output_file = os.path.join(output_file, pdf_filename)

    # Set default output filename if not provided
    if output_file is None:
        base_name = os.path.splitext(input_file)[0]
        output_file = f"{base_name}.pdf"
    
    # Check if input file exists
    if not os.path.exists(input_file):
        #print(f"Error: Input file '{input_file}' not found.")
        return False
    
    try:
        # Read the text file
        with open(input_file, 'r', encoding='utf-8') as file:
            text = file.read()
        
        # Create PDF canvas
        c = canvas.Canvas(output_file, pagesize=page_size)
        width, height = page_size
        
        # Set font
        c.setFont("Helvetica", font_size)
        
        # Calculate text area dimensions
        text_width = width - 2 * margin
        text_height = height - 2 * margin
        
        # Calculate characters per line based on font size and page width
        chars_per_line = int(text_width / (font_size * 0.6))  # Approximate character width
        
        # Split text into lines
        lines = text.split('\n')
        wrapped_lines = []
        
        for line in lines:
            if len(line) <= chars_per_line:
                wrapped_lines.append(line)
            else:
                # Wrap long lines
                wrapped = textwrap.fill(line, width=chars_per_line)
                wrapped_lines.extend(wrapped.split('\n'))
        
        # Calculate lines per page
        line_height = font_size * 1.2  # Line spacing
        lines_per_page = int(text_height / line_height)
        
        # Write text to PDF
        y_position = height - margin
        line_count = 0
        
        for line in wrapped_lines:
            # Check if we need a new page
            if line_count >= lines_per_page:
                c.showPage()  # Start new page
                c.setFont("Helvetica", font_size)
                y_position = height - margin
                line_count = 0
            
            # Write line to PDF
            c.drawString(margin, y_position, line)
            y_position -= line_height
            line_count += 1
        
        # Save the PDF
        c.save()
        #print(f"Successfully converted '{input_file}' to '{output_file}'")
        return True, output_file
        
    except Exception as e:
        #print(f"Error converting file: {str(e)}")
        return False


def convert_heic_to_jpg_for_pdf(heic_path, jpg_path=None, max_size=(1500, 1500)):
    t0 = time.time()
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        with Image.open(heic_path) as img:
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail(max_size, Image.LANCZOS)
            if not jpg_path:
                jpg_path = os.path.splitext(heic_path)[0] + "_converted.jpg"
            img.save(jpg_path, "JPEG", quality=70, optimize=True)
            logging.info(f"✅[HEIC] Converted and compressed: {jpg_path}")
            FINAL_META.record(action="heic->jpg", status="Success",
                            source_path=heic_path, target_path=jpg_path,
                            t_start=t0, t_end=time.time())
                            
        return jpg_path
    except Exception as e:
        logging.error(f"❌[HEIC ERROR] Could not convert {heic_path}: {e}")
        FINAL_META.record(action="heic->jpg", status="Failure",
                        source_path=heic_path, reason=str(e),
                        t_start=t0, t_end=time.time())
                        
        return None
    

def convert_images_to_pdf(image_files, pdf_path):
    """
    Build a single PDF from a list of image paths.

    Improvements:
    - Handles palette ('P') images with transparency by converting to RGBA, then
        flattening onto a white background before saving as JPEG (since JPEG has no alpha).
    - Preserves existing logging to Final_Metadata.xlsx with pages_out.
    """

    # sort for stable ordering
    image_files = sorted(
        image_files, key=lambda p: os.path.basename(p).lower())

    def _ensure_jpeg_compatible(img: Image.Image) -> Image.Image:
        """
        Return an RGB image safe to save as JPEG.
        - If RGBA/LA: flatten on white
        - If P with transparency: convert to RGBA then flatten
        - If L: leave as is (FPDF can take JPEG; we will convert to RGB for saving)
        - Else: convert to RGB
        """
        if img.mode == "P" and "transparency" in img.info:
            img = img.convert("RGBA")

        if img.mode in ("RGBA", "LA"):
            # Flatten onto white background
            bg = Image.new("RGB", img.size, (255, 255, 255))
            # For 'LA', alpha channel is at band 1; for 'RGBA', band 3
            alpha = img.split()[-1]
            bg.paste(img.convert("RGB"), mask=alpha)
            return bg

        if img.mode == "P":
            return img.convert("RGB")

        if img.mode == "L":
            # JPEG can be L, but to be safe and consistent use RGB
            return img.convert("RGB")

        if img.mode not in ("RGB",):
            return img.convert("RGB")

        return img

    t0 = time.time()
    pdf = FPDF()
    pages_added = 0

    for img_path in image_files:
        try:
            with Image.open(img_path) as img:
                img.load()

                # Make JPEG-safe (handles palette + transparency properly)
                safe = _ensure_jpeg_compatible(img)

                # Scale to A4 (210x297 mm) keeping aspect ratio
                width_px, height_px = safe.size
                pdf_w, pdf_h = 210.0, 297.0
                ratio = min(pdf_w / width_px, pdf_h / height_px)
                w_mm, h_mm = width_px * ratio, height_px * ratio

                # Ensure we pass a JPEG (FPDF likes actual JPEG files)
                tmp_jpg = img_path
                if not img_path.lower().endswith((".jpg", ".jpeg")) or safe.mode != "RGB":
                    tmp_jpg = os.path.splitext(img_path)[0] + ".__merge.jpg"
                    try:
                        safe.save(tmp_jpg, "JPEG", quality=85, optimize=True)
                    except Exception:
                        safe.save(tmp_jpg, "JPEG", quality=85)

                pdf.add_page()
                # Place at top-left; you could center by computing x/y if desired
                pdf.image(tmp_jpg, x=0, y=0, w=w_mm, h=h_mm)
                pages_added += 1

                # clean temp file if we created one
                if tmp_jpg != img_path and os.path.exists(tmp_jpg):
                    try:
                        os.remove(tmp_jpg)
                    except Exception:
                        pass

        except Exception as e:
            logging.error(f"❌[images->pdf] Skip {img_path}: {e}")

    try:
        if pages_added == 0:
            logging.warning(f"⚠️[images->pdf] No valid images for: {pdf_path}")
            FINAL_META.record(
                action="images->pdf", status="Skipped",
                source_path=os.path.dirname(pdf_path), target_path="",
                reason="no valid images", pages_out=0,
                t_start=t0, t_end=time.time()
            )
            return False

        pdf.output(pdf_path, "F")
        logging.info(f"✅[images->pdf] Created: {pdf_path}")
        FINAL_META.record(
            action="images->pdf", status="Success",
            source_path=os.path.dirname(pdf_path), target_path=pdf_path,
            pages_out=pages_added, t_start=t0, t_end=time.time()
        )
        return True

    except Exception as e:
        logging.error(f"❌[images->pdf] Write failed {pdf_path}: {e}")
        FINAL_META.record(
            action="images->pdf", status="Failure",
            source_path=os.path.dirname(pdf_path), target_path="",
            reason=str(e), pages_out=pages_added,
            t_start=t0, t_end=time.time()
        )
        return False
    

