import logging
import datetime
from pathlib import Path
from pillow_heif import register_heif_opener
from dotenv import load_dotenv

from metadata import FinalMeta
from db_helpers import build_db_config_from_env

load_dotenv()

current_date = datetime.datetime.now().strftime('%Y-%m-%d')
log_path = LOG_PATH

handler = logging.FileHandler(log_path,encoding='utf-8')
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Register HEIC support
register_heif_opener()

#>>>>> PHASE 1 <<<<<<<
# === Constants ===
MISSING_CLAIMS_FILE = MISSING_CLAIMS_FILE
FAILED_FILES_FILE = FAILED_FILES_FILE
TOKEN_FILE = TOKEN_FILE

CLIENT_ID = CLIENT_ID
CLIENT_SECRET = CLIENT_SECRET
URL_TOKEN = URL_TOKEN

box_folder_ids = BOX_FOLDER_IDS
download_complete_folders = DOWNLOAD_COMPLETE_FOLDERS
base_folder = BASE_FOLDER

BOX_API = BOX_API

db_config = build_db_config_from_env()

#email information
sender_email = SENDER_EMAIL
to_email = TO_EMAIL
smtp_server = SMTP_SERVER
smtp_port = SMTP_PORT

#>>>>> PHASE 2 <<<<<<<

# 1) Set correct roots
claims_root = CLAIMS_ROOT
input_root = INPUT_ROOT
output_root = OUTPUT_ROOT
backup_root = BACKUP_ROOT
wkhtmltopdf_exe = WKHTMLTOPDF_EXE

IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tif', '.tiff', '.heic', '.jpe','.jfi','hei','.nef']
AUDIO_EXTS = ['.mp3', '.wav', '.ogg', '.m4a', '.flac']
EMAIL_EXTS = ['.eml', '.msg']
ZIP_EXTS = ['.7z', '.rar', '.tar', '.gz', '.bz2', '.xz', '.zip']
DOC_EXTS = ['.doc', '.docx', '.ppt', '.pptx']
EXC_EXTS = ['.xls', '.xlsx', '.csv']
MIN_IMAGE_SIZE = 10 * 1024
FINAL_META = FinalMeta(CLAIMS_ROOT, db_config)
MAX_PDF_MB = 600
MAX_PDF_PAGES = 3000
CSHARP_EXE_PATH = CSHARP_EXE_PATH
ASPOSE_LIC_PATH = ASPOSE_LIC_PATH

