import datetime
import time
import os
import logging

from datetime import datetime

from authentication_utils import authenticate_box, test_token_refresh
from __init__ import (CLIENT_ID, 
                    CLIENT_SECRET, 
                    box_folder_ids, 
                    base_folder, 
                    db_config,
                    Protect_New,
                    base_folder)
from downloader import download_from_box
from notifications import send_success_email, send_email_alert
from log_file import csv_log
from main_phase2 import license, phase_2



def task(i):
    now = datetime.now()
    print(f"🔄 Running task at {now.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"🔄 Running task at {now.strftime('%Y-%m-%d %H:%M:%S')}")
    main(i)
    print("✅ Task completed.\n")

def main(i):
    # ✅ Split folders
    # Raw original files
    print("🔄 Refreshing tokens...")
    test_token_refresh()
    print("🔄 Step 1: Authenticating with Box...")
    client = authenticate_box(CLIENT_ID, CLIENT_SECRET)
    print(">>>>>", client)
    if not client:
        print("❌ Authentication failed. Exiting...")
        return
    else:
        print("✅ Authentication successful. Starting download process...")

    start_time = time.time()
    print("TIME ",time.ctime(start_time))
    logging.info(f">>>Lap {i}, time: {time.ctime(start_time)}")
    downloaded_files = []
    failed_files = []
    
    for box_folder_id in box_folder_ids:
        # Get folder name from Box for naming consistency
        folder = client.folder(box_folder_id).get(fields=['name'])
        folder_name = folder.name.replace(" ", "_")
        print(folder_name)

        # Setup paths for this folder
        raw_folder_path = os.path.join(base_folder, f"{folder_name}")

        download_from_box(
                    client,
                    [box_folder_id],
                    base_folder,
                    downloaded_files,
                    failed_files,
                    db_config=db_config,
                    # missing_claims_path=os.path.join(raw_folder_path, "missing_claims.txt"),
                    # failed_downloads_path=os.path.join(raw_folder_path, "failed_downloads.txt"),
                    # original_failed=os.path.join(raw_folder_path, "failed_downloads.txt")
        )

    elapsed_time = time.time() - start_time
    print(f"✅ All downloads completed in {elapsed_time:.2f} seconds.")
    logging.info(f"✅ All downloads completed in {elapsed_time:.2f} seconds.")

    csv_log()

    print("📧 Sending processing summary email...")
    send_success_email(
        downloaded_files,
        failed_files,
        box_testing_folder=base_folder, 
        elapsed_seconds=elapsed_time 
    )
   
    logging.info("🎉 Starting Phase 2 (Conversion).")
    phase_2()
    
    print("🎉 All steps completed successfully.")
    logging.info("🎉 All steps completed successfully.")



if __name__ == "__main__":

    #Change to run from 6 am to 8 PM CAN-6658 (ALL LOB every run)
    i=1
    while True:
        now = datetime.now()
        if now.hour >= 20:
            print(f"🛑 It's {now.strftime('%H:%M')}. Running for last time.")
            task(i)
            break
        task(i)
        i += 1

        print("⏳ Sleeping for 50 minutes before next run...\n")
        logging.info("⏳ Sleeping for 50 minutes before next run...\n")
        time.sleep(7200)  #  2 hours

    logging.info("✅ Tasks ended...Program will close now.\n")
    print("👋 All scheduled tasks are complete. Exiting now.")
        # First run was done at 10:00 AM (by the scheduler)
        # Assume script starts at 10:00 AM (scheduler starts script at this time)
        # first_run_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        # second_run_time = first_run_time + timedelta(hours=3)   # 1:00 PM
        # third_run_time  = second_run_time + timedelta(hours=4)  # 5:00 PM