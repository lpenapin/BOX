import os
import logging
import pyodbc
import time
import pandas as pd

from __init__ import base_folder,db_config

def create_table(db_config: dict, claim_number):
    conn_str = ";".join([f"{key}={value}" for key, value in db_config.items()])
    logging.info(f"🔗 Connecting to SQL Server...")

    try:
        start_db = time.time()
        with pyodbc.connect(conn_str, timeout=10) as conn:  # Safe timeout
            logging.info("✅ Successfully connected to SQL Server.")

            cursor = conn.cursor()
            # Optional: Ping DB to ensure responsiveness
            #cursor.execute("SELECT 1")
            #if cursor.fetchone()[0] != 1:
             #   logging.warning("⚠️ DB ping failed.")

            query = """
                SELECT [FileName]
                    ,[ClaimNumber]
                    ,[DestinationFolderPath]
                    ,[DownloadStatus]
                    ,[DownloadErrorReason]
                    ,[BusinessArea]
                    ,[InsertedAt]
                    ,[ActorName]
                FROM [Box].[dbo].[BOX_FileDownloadLog]
                where [ClaimNumber] = ? AND [InsertedAt] >= CAST(GETDATE() AS DATE)
            """

            cursor.execute(query, claim_number)
            rows = cursor.fetchall()
            df = pd.DataFrame.from_records(rows, columns=[desc[0] for desc in cursor.description])

            conn.commit()
            elapsed = time.time() - start_db
            #print(f"✅ Table create for claim_number {claim_number} in {elapsed:.2f}s.")
            logging.info(f"✅ Table create for claim_number {claim_number} in {elapsed:.2f}s.")

            if elapsed > 10:
                #print("⚠️ DB select took longer than expected.")
                logging.warning("⚠️ DB select took longer than expected.")
            
            return df

    except Exception as e:
        #(f'error {e}')
        logging.error(f"❌ Table create Error: {e}")
        return None

def csv_log():
    try:
        for LOB in os.listdir(base_folder):
            #print(f'{LOB}')
            logging.info(f'✅ Creating csv log for LOB: {LOB}')
            if LOB != 'Catherine & Maria':
                LOB_folder = os.path.join(base_folder,LOB)
                for claim in os.listdir(LOB_folder):
                    _name, _ext = os.path.splitext(claim)
                    if _ext == "":
                        #print(f'>>>{claim}')
                        table = create_table(db_config,claim)
                        claim_folder = os.path.join(LOB_folder,claim)
                        new_file = os.path.join(claim_folder,f'SQL_data_{claim}.csv')
                        table.to_csv(new_file,index=False)
                        logging.info(f'✅ Log created for claim: {claim}')
                        #print(table)
                        #claim_folder = os.path.join(LOB_folder,claim)
                        #for file in os.listdir(claim_folder):
                        #    print(f'     {file}')
    except Exception as e:
        #(f'error {e}')
        logging.error(f"❌ Error creating CSV log: {e}")
