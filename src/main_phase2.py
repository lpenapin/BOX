import logging
import aspose.email as ae
import time
from datetime import datetime

from __init__ import input_root, output_root, claims_root,backup_root
from processing import batch_process,moving_files
from notifications import send_convert_success_email

#✅
#❌
#⚠️

def phase_2():
    #Configure logging BEFORE running anything
    #logging.basicConfig(filename="process.log", level=logging.INFO)
    
    #Run your main processing first (if it can create/modify metadata files)
    logging.info(
        f"✅Starting batch processing from {input_root} to {output_root}")
    start = time.time()
    P_start = datetime.fromtimestamp(start).strftime("%Y-%m-%d %H:%M:%S")
    print("Start time: ", P_start)
    logging.info(f"✅Start time: {P_start}")
    time.sleep(10)
    files = 0
    files = batch_process(input_root, output_root, backup_root)
    #logging.info(f"✅Batch processing complete. Total {files} processed")
    #moving_files(input_root,backup_root)
    #logging.info("✅All files has been moved.")
    end = time.time()
    elapsed_time = end - start
    send_convert_success_email(files,elapsed_time)

    P_end = datetime.fromtimestamp(end).strftime("%Y-%m-%d %H:%M:%S")
    print('End time: ', P_end)
    logging.info(f"✅End time: {P_end}")
    
    diff_seconds = end - start
    # Convert seconds to h:m:s
    hours, remainder = divmod(diff_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"Process time: {int(hours)}:{int(minutes)}:{int(seconds)}")
    logging.info(f"✅Process time: {int(hours)}:{int(minutes)}:{int(seconds)}")


if __name__== "__main__":

    phase_2()
    '''r = license()
    #print(r)
    if r:
        phase_2()
    else:
        print('End of the process')'''