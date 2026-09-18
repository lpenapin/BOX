import logging
import requests
from dateutil import parser
from datetime import timezone
from pathlib import Path
import re
import time
import uuid


from __init__ import BOX_API, box_folder_ids, download_complete_folders
from authentication_utils import load_tokens


def moving_to_downloadCompleted(file_id, org_folder_id):

    # actual access token
    access_token, refresh_token = load_tokens()

    # actual file ID and destination folder ID
    file_id
    org_folder_id #box_folder_id

    position = box_folder_ids.index(org_folder_id)
    destination_folder_id = download_complete_folders[position]

    url = f'{BOX_API}/files/{file_id}'

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    data = {
        'parent': {'id': destination_folder_id}
    }
    response = requests.put(url, headers=headers, json=data)

    

    if response.status_code == 200:
        logging.info(f'File {file_id} moved successfully!')
        #print('File moved successfully!')
    else:
        print(f'Error: {response.status_code} - {response.text}')
        logging.error(f'Error on file {file_id}: {response.status_code} - {response.text}')
    
    return response.status_code, response.text


def ensure_unique_filename(folder: Path, filename: str) -> str:
    base = Path(filename).stem
    ext = Path(filename).suffix
    candidate = folder / filename
    counter = 1
    while candidate.exists():
        new_name = f"{base}_v{counter}{ext}"
        candidate = folder / new_name
        counter += 1
    return candidate.name


def sanitize_and_truncate_filename(folder_path: Path, filename: str, max_total_length: int = 256, min_name_length: int = 10) -> str:
    import unicodedata

    # Remove invalid characters
    base_name = re.sub(r'[<>:"/\\|?*]', '_', Path(filename).stem)

    # Normalize accents (French → English letters)
    base_name = unicodedata.normalize('NFKD', base_name).encode('ASCII', 'ignore').decode('utf-8')

    ext = Path(filename).suffix
    full_path_prefix = folder_path.resolve()

    # Start without suffix
    suffix = ""
    allowed = max_total_length - len(str(full_path_prefix)) - len(ext) - 1
    allowed = max(min_name_length, allowed)

    if len(base_name) > allowed:
        suffix = f"_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        allowed = max_total_length - len(str(full_path_prefix)) - len(suffix + ext) - 1
        allowed = max(min_name_length, allowed)

    truncated_base = base_name[:allowed]
    return f"{truncated_base}{suffix}{ext}"


def resolve_actor_via_sa_rest(client, file_id: str) -> dict:
    """
    Mirror the working probe:
        1) GET /files/{id}?fields=file_version
        2) GET /files/{id}/versions/{ver}?fields=uploader_display_name,modified_by
    Returns: {'actor_name','actor_login','actor_source'}
    """
    bearer = client.auth.access_token
    hdrs = {"Authorization": f"Bearer {bearer}"}

    # 1) current version id
    r = requests.get(f"{BOX_API}/files/{file_id}", headers=hdrs,
                    params={"fields": "file_version"}, timeout=20)
    r.raise_for_status()
    ver_id = (r.json() or {}).get("file_version", {}).get("id")
    if not ver_id:
        return {"actor_name": "Anonymous User", "actor_login": None, "actor_source": "no_version"}

    # 2) version → uploader_display_name / modified_by
    r = requests.get(f"{BOX_API}/files/{file_id}/versions/{ver_id}", headers=hdrs,
                    params={"fields": "uploader_display_name,modified_by"}, timeout=20)
    r.raise_for_status()
    v = r.json() or {}

    udn = v.get("uploader_display_name")
    if udn:
        looks_email = ("@" in udn) and ("." in udn.split("@")[-1])
        return {
            "actor_name": udn,
            "actor_login": (udn if looks_email else None),
            "actor_source": "current_version.uploader_display_name"
        }

    mv = (v.get("modified_by") or {})
    if mv.get("login"):
        return {
            "actor_name": mv.get("name"),
            "actor_login": mv.get("login"),
            "actor_source": "current_version.modified_by"
        }

    return {"actor_name": "Anonymous User", "actor_login": None, "actor_source": "anonymous"}


def parse_box_datetime_to_utc(datetime_str):
    try:
        # Automatically parse ISO 8601 (Z or with offsets)
        dt = parser.isoparse(datetime_str)
        # Always convert to UTC and return without tzinfo (for SQL Server DATETIME)
        dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt_utc
    except Exception as e:
        logging.warning(f" Failed to parse datetime '{datetime_str}': {e}")
        return None  # or fallback to datetime.utcnow() if you prefer

