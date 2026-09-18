import os
import unicodedata
import re
import time
import uuid
from PIL import Image
import io
from fpdf import FPDF
from pathlib import Path
from openpyxl import load_workbook
import csv
import zipfile
import py7zr
import patoolib
import tarfile
import logging
import hashlib
import subprocess


# cache {claim: (actor_name, actor_login)}
_ACTOR_CACHE: dict[str, tuple[str | None, str | None]] = {}


def _run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err


def _longpath(p: Path) -> str:
    r"""Prefix \\?\ on Windows to avoid MAX_PATH issues."""
    s = str(p)
    if os.name == "nt":
        s = str(p.resolve())
        if not s.startswith("\\\\?\\"):
            s = "\\\\?\\" + s
    return s


def _ensure_short_enough(path: Path, base_stem: str, start_idx: int, end_idx: int) -> Path:
    """
    If the final path would be too long, progressively shorten the base stem.
    Aim for <= 240 chars as a safety margin.
    """
    MAX_TOTAL = 240
    stem = base_stem
    while True:
        candidate = path.parent / f"{stem}_p{start_idx}-{end_idx}.pdf"
        if len(str(candidate)) <= MAX_TOTAL:
            return candidate
        if len(stem) > 20:
            stem = _safe_slug(stem, limit=max(20, len(stem) - 10))
        else:
            # last resort
            return path.parent / f"p_{start_idx}-{end_idx}.pdf"


def _safe_slug(name: str, limit: int = 60) -> str:
    """Windows-safe, shortened base name with a short hash if truncated."""
    base = re.sub(r'[^\w\s\-]+', '', name, flags=re.UNICODE).strip()
    base = re.sub(r'\s+', ' ', base)
    if len(base) <= limit:
        return base or "pdf"
    h = hashlib.sha1(base.encode('utf-8')).hexdigest()[:6]
    return f"{base[:limit-7].rstrip()}_{h}"


def unZip(file, destFile, _ext):
    if _ext == ".7z":
        #print(">>>>>>>>TRYING PY7ZR")
        with py7zr.SevenZipFile(file,mode='r') as zip_ref:
            zip_ref.extractall(path=destFile)
        return "PY7ZR"

    elif _ext == ".xz":
        #print(">>>>>>>>TRYING TARFILE")
        try:
            with tarfile.open(file, 'r:xz') as tar:
                tar.extractall(path=destFile)
                return "TARFILE"
        except FileNotFoundError:
            logging.error(f"❌Error: The file '{file}' was not found.")
        except tarfile.ReadError:
            logging.error(f"❌Error: Could not open '{file}'. It might not be a valid tar.xz archive.")
        except Exception as e:
            logging.error(f"❌An error occurred during extraction: {e}")
            
    elif _ext == ".rar" or ".tar":
        #print(">>>>>>>>TRYING PATOOLIB")
        patoolib.extract_archive(file,outdir=destFile)
        return "PATOOLIB"

    else:
        #print(">>>>>>>>TRYING ZIPFILE")
        with zipfile.ZipFile(file,'r') as zip_ref:
            zip_ref.extractall(destFile)
        return "ZIPFILE"


def _latest_metadata_file(claim_dir: Path) -> Path | None:
    cands = [p for p in claim_dir.rglob("*")
            if p.is_file() and "metadata" in p.name.lower()
            and p.suffix.lower() in {".xlsx", ".xlsm", ".csv"}]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


'''
def _rec(action, status, *, src="", dst="", reason="", tool="", t0=None, pages_out=None,asm=""):
        FINAL_META.record(
            action=action, status=status,
            source_path=src , target_path=dst or "",
            reason=reason or "", pages_out=pages_out,
            actor_source_meta=asm,
            t_start=t0, t_end=time.time()
        )
'''


def _find_claim_dir_for_path(root: Path, some_path: str | Path) -> Path:
    p = Path(some_path).resolve()
    for cur in [p] + list(p.parents):
        if re.fullmatch(r"\d{8,}", cur.name or ""):
            return cur
    return root


def _wait_stable(path: str, retries: int = 15, delay: float = 0.15) -> bool:
    """Return True when file exists and size is stable across two checks."""
    import time
    prev = -1
    for _ in range(retries):
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size > 0 and size == prev:
                return True
            prev = size
        time.sleep(delay)
    return os.path.exists(path) and os.path.getsize(path) > 0


def is_likely_logo(filename, image_data):
    """
    Returns True if an image is likely a logo or too small to be meaningful.
    Skip if:
        - dimensions < 100x100 px
        - file size < 40 KB
    """
    TINY_BYTES = 40_000
    MIN_WH = 100

    # dimension check
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            w, h = img.size
        if w < MIN_WH or h < MIN_WH:
            return True
    except Exception:
        return True

    # size check
    try:
        if len(image_data) < TINY_BYTES:
            return True
    except Exception:
        return True
    
    return False


def remove_french_characters(text):
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join([c for c in nfkd if not unicodedata.combining(c)])


def sanitize_and_truncate_filename(folder_path, filename,part='', max_path_length=256, keep_chars=50):
    base, ext = os.path.splitext(filename)
    base = remove_french_characters(base)
    base = re.sub(r'[\/\\\:\*\?\"\<\>\|]', '_', base)
    base = re.sub(r'[^\w\s\-\.]', '', base)
    base = re.sub(r'[\s_]+', '_', base).strip('_')
    truncated_base = base[:keep_chars]
    #timestamp = time.strftime("%Y%m%d_%H%M%S")
    timestamp = time.strftime("%Y%m%d")
    suffix = f"_{timestamp}_{uuid.uuid4().hex[:4].upper()}{ext}"
    #suffix = f"_{timestamp}{ext}"
    if ext in ['.eml', '.msg'] or ext == '': part=''
    if part=='':
        new_filename = f"{truncated_base}{suffix}"
    else:
        new_filename = f'{part:03d}_{truncated_base}{suffix}'
    full_path = os.path.join(folder_path, new_filename)
    if len(full_path) > max_path_length:
        allowed_base_len = max_path_length - len(folder_path) - len(suffix) - 1
        truncated_base = base[:max(10, allowed_base_len)]
        new_filename = f"{truncated_base}{suffix}"
    return new_filename


def ensure_unique_filename(folder, file_name):
    """
    Ensures that a filename is unique in the given folder by appending a version number.
    """
    base_name, ext = os.path.splitext(file_name)
    counter = 1
    new_file_name = file_name
    while os.path.exists(os.path.join(folder, new_file_name)):
        new_file_name = f"{base_name}_{counter:04d}{ext}"
        counter += 1
    return new_file_name


def _read_actor_from_csv(path: Path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        if not rdr.fieldnames:
            return None, None
        norm = {_norm(k): k for k in rdr.fieldnames}

        def pick(keys):
            for k in keys:
                if k in norm:
                    return norm[k]
            return None
        k_name = pick({"actor name", "actor", "sender name"})
        k_login = pick(
            {"actor login", "login", "username", "user login", "user id"})
        for r in rdr:
            name, login = (r.get(k_name) or "").strip(
            ), (r.get(k_login) or "").strip()
            if name or login:
                return name, login
    return None, None


def _norm(s: str) -> str: return re.sub(r"\s+",
                                        " ", str(s or "")).strip().lower()


def _read_actor_from_xlsx(path: Path):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    headers = next(rows, None)
    if not headers:
        return None, None
    name_col = login_col = None
    for i, h in enumerate(headers):
        h = _norm(h)
        if h in {"actor name", "actor", "sender name"}:
            name_col = i
        if h in {"actor login", "login", "username", "user login", "user id"}:
            login_col = i
    for row in rows:
        if not row:
            continue
        name = row[name_col] if name_col is not None else None
        login = row[login_col] if login_col is not None else None
        if name or login:
            return str(name or ""), str(login or "")
    return None, None


def _actor_from_claim_dir(claim_dir: Path):
    claim = claim_dir.name
    if claim in _ACTOR_CACHE:
        return _ACTOR_CACHE[claim]
    meta = _latest_metadata_file(claim_dir)
    if not meta:
        return None, None
    try:
        if meta.suffix.lower() in {".xlsx", ".xlsm"}:
            val = _read_actor_from_xlsx(meta)
        else:
            val = _read_actor_from_csv(meta)
    except Exception:
        val = (None, None)
    _ACTOR_CACHE[claim] = val
    return val


def _safe_getsize(p: str | Path) -> int:
    try:
        size = os.path.getsize(p)
        logging.info(f"➡️File {p} size {size}")
        return size
    except Exception as e:
        logging.exception(f"Failed to get size for {p}")
        return 0
    

