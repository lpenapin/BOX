import os
import time
import pyodbc
import logging
from dotenv import load_dotenv



def _conn_str_from_config(cfg: dict) -> str:
    return ";".join([f"{k}={v}" for k, v in cfg.items()])


def build_db_config_from_env() -> dict:
    load_dotenv()
    trusted = (os.getenv("DB_TRUSTED") or "").strip().lower() in {
        "yes", "true", "1"}

    if trusted:
        cfg = {
            "DRIVER": os.getenv("DB_DRIVER"),
            "SERVER": os.getenv("DB_SERVER"),
            "DATABASE": os.getenv("DB_DATABASE"),
            "Trusted_Connection": "yes"
        }
    else:
        cfg = {
            "DRIVER": os.getenv("DB_DRIVER"),
            "SERVER": os.getenv("DB_SERVER"),
            "DATABASE": os.getenv("DB_DATABASE"),
            "UID": os.getenv("DB_UID"),
            "PWD": os.getenv("DB_PWD")
        }

    # add optional encryption flags
    if os.getenv("DB_ENCRYPT", "yes").strip().lower() in {"yes", "true", "1"}:
        cfg["Encrypt"] = "yes"
    if os.getenv("DB_TRUST_SERVER_CERT", "yes").strip().lower() in {"yes", "true", "1"}:
        cfg["TrustServerCertificate"] = "yes"

    # wrap driver in {}
    drv = cfg.get("DRIVER", "")
    if not drv.startswith("{"):
        cfg["DRIVER"] = "{" + drv + "}"

    try:
        test_conn = pyodbc.connect(_conn_str_from_config(cfg), timeout=5)
        test_conn.close()
        logging.info("✅ SQL Server connection test passed.")
    except Exception as e:
        logging.error(f"❌ SQL Server connection failed: {e}")
    return cfg


def log_download_to_db(db_config: dict, log: dict):
    conn_str = ";".join([f"{key}={value}" for key, value in db_config.items()])
    logging.info(f"🔗 Connecting to SQL Server...")

    try:
        start_db = time.time()
        with pyodbc.connect(conn_str, timeout=10) as conn:  # Safe timeout
            logging.info("✅ Successfully connected to SQL Server.")

            cursor = conn.cursor()
            # Optional: Ping DB to ensure responsiveness
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                logging.warning("⚠️ DB ping failed.")

            query = """
                INSERT INTO BOX_FileDownloadLog (
                    FileName, ClaimNumber, FileType, CreationDate, Description,
                    SourceBoxFolderPath, DestinationFolderPath, FileSizeMB,
                    DownloadStartTime, DownloadEndTime, TotalDownloadTimeSeconds,
                    DownloadStatus, DownloadErrorReason, BusinessArea,
                    ActorName, ActorLogin
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,?,?)
            """

            cursor.execute(query, (
                log['file_name'],
                log['claim_number'],
                log['file_type'],
                log['creation_date'],
                log['description'],
                log['source_box_folder'],
                log['destination_folder'],
                log['file_size_mb'],
                log['download_start'],
                log['download_end'],
                log['total_time_seconds'],
                log['download_status'],
                log['download_error_reason'],
                log['business_area'],
                log['actor_name'],
                log['actor_login'],
            ))

            conn.commit()
            elapsed = time.time() - start_db
            logging.info(f"✅ Log inserted for file '{log['file_name']}' (Claim {log['claim_number']}) in {elapsed:.2f}s.")

            if elapsed > 10:
                logging.warning("⚠️ DB insert took longer than expected.")

    except Exception as e:
        logging.error(f"❌ DB Insert Error: {e} | log: {log}")
        # Let your script continue and send the email


def ensure_final_metadata_table(db_config: dict, table_name: str = "FinalMetadataLog") -> None:
    ddl = f"""
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = '{table_name}')
    BEGIN
        CREATE TABLE dbo.{table_name}(
            Id               INT IDENTITY(1,1) PRIMARY KEY,
            TimestampStart   DATETIME2(3)   NOT NULL,
            TimestampEnd     DATETIME2(3)   NOT NULL,
            TimeTakenSec     DECIMAL(18,3)  NOT NULL,
            ClaimNumber      NVARCHAR(64)   NULL,
            Action           NVARCHAR(100)  NOT NULL,
            Status           NVARCHAR(50)   NOT NULL,
            Reason           NVARCHAR(MAX)  NULL,
            SourcePath       NVARCHAR(4000) NULL,
            SourceExt        NVARCHAR(16)   NULL,
            SourceBytes      BIGINT         NULL,
            TargetPath       NVARCHAR(4000) NULL,
            TargetExt        NVARCHAR(16)   NULL,
            TargetBytes      BIGINT         NULL,
            PagesOut         INT            NULL,
            ActorName        NVARCHAR(255)  NULL,
            ActorLogin       NVARCHAR(255)  NULL
        );
        CREATE INDEX IX_{table_name}_Claim_Timestamp ON dbo.{table_name}(ClaimNumber, TimestampStart);
        CREATE INDEX IX_{table_name}_Action_Status   ON dbo.{table_name}(Action, Status);
    END
    """
    try:
        with pyodbc.connect(_conn_str_from_config(db_config)) as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
                conn.commit()
        logging.info(f"✅ Ensured dbo.{table_name} exists.")
    except Exception as e:
        logging.error(f"❌ Could not ensure table dbo.{table_name}: {e}")


def log_metadata_to_db(db_config: dict, row: dict, table_name: str = "FinalMetadataLog") -> None:
    sql = f"""
    INSERT INTO dbo.{table_name}(
        TimestampStart, TimestampEnd, TimeTakenSec,
        ClaimNumber, Action, Status, Reason,
        SourcePath, SourceExt, SourceBytes,
        TargetPath, TargetExt, TargetBytes,
        PagesOut, ActorName, ActorLogin
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        row.get("TimestampStart"),
        row.get("TimestampEnd"),
        row.get("TimeTakenSec"),
        row.get("ClaimNumber"),
        row.get("Action"),
        row.get("Status"),
        row.get("Reason"),
        row.get("SourcePath"),
        row.get("SourceExt"),
        row.get("SourceBytes"),
        row.get("TargetPath"),
        row.get("TargetExt"),
        row.get("TargetBytes"),
        row.get("PagesOut"),
        row.get("ActorName"),
        row.get("ActorLogin"),
    )
    try:
        with pyodbc.connect(_conn_str_from_config(db_config)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
        logging.info("✅ Row inserted into FinalMetadataLog.")
    except Exception as e:
        logging.error(f"❌ DB insert failed: {e} | row: {row}")
