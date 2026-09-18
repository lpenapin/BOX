import os
import logging
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from __init__ import (sender_email,
                        to_email,
                        cc_emails,
                        smtp_server,
                        smtp_port
)


def send_email_alert(msg_text, subj):
    message = MIMEText(msg_text)
    message['Subject'] = subj
    message['From'] = sender_email
    message["To"] = ", ".join(to_email)
    message["Cc"] = ", ".join(cc_emails)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            recipients = to_email + cc_emails
            server.sendmail(sender_email, recipients, message.as_string())
        logging.info(f" Alert email sent: {subj}")
    except Exception as e:
        logging.error(f" Failed to send SMTP alert: {str(e)}")


def send_success_email(downloaded_files, failed_files, box_testing_folder, elapsed_seconds=None):

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    status = "With Failures" if failed_files else "Success" 
    subject = f"📥 Box File Donwload Report [{status}] - {now}"

    body = f"📊 Report Summary For Box ({now}):\n"
    body += f"✅ Files Downloaded: {len(downloaded_files)}\n"
    body += f"❌ Files Failed: {len(failed_files)}\n\n"

    if elapsed_seconds:
        h, m, s = int(elapsed_seconds // 3600), int((elapsed_seconds % 3600) // 60), int(elapsed_seconds % 60)
        body += f"⏱ Total Time: {h}h {m}m {s}s\n\n"

    message = MIMEMultipart()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = ", ".join(to_email)
    message["Cc"] = ", ".join(cc_emails)
    message.attach(MIMEText(body, "plain"))

    # === Loop through each high-level project folder (e.g. Healthcare_new, Protect_new)
    for project_folder in os.listdir(box_testing_folder):
        project_path = os.path.join(box_testing_folder, project_folder)
        if not os.path.isdir(project_path):
            continue

        for filename in ["missing_claims_metadata.xlsx", "failed_files.xlsx"]:
            full_path = os.path.join(project_path, filename)
            if os.path.exists(full_path):
                renamed = f"{project_folder}_{filename}"
                try:
                    with open(full_path, "rb") as f:
                        part = MIMEApplication(f.read(), _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        part.add_header('Content-Disposition', 'attachment', filename=renamed)
                        message.attach(part)
                        logging.info(f"📎 Attached: {renamed}")
                except Exception as e:
                    logging.warning(f"⚠️ Failed to attach {renamed}: {str(e)}")

    # === Send Email ===
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            recipients = to_email + cc_emails
            server.sendmail(sender_email, recipients, message.as_string())
        logging.info("✅ Summary email sent.")
    except Exception as e:
        logging.error(f"❌ Failed to send email: {str(e)}")


def send_convert_success_email(converted_files,elapsed_seconds=None):

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"📥 Box File Converter Report - {now}"

    body = f"📊 Report Summary For Box ({now}):\n"
    body += f"✅ Files Converted: {converted_files}\n"
    #body += f"❌ Files Failed: {len(failed_files)}\n\n"
    if elapsed_seconds:
        h, m, s = int(elapsed_seconds // 3600), int((elapsed_seconds % 3600) // 60), int(elapsed_seconds % 60)
        body += f"⏱ Total Time: {h}h {m}m {s}s\n\n"
    
    message = MIMEMultipart()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = ", ".join(to_email)
    message["Cc"] = ", ".join(cc_emails)
    message.attach(MIMEText(body, "plain"))

    # === Send Email ===
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            recipients = to_email + cc_emails
            server.sendmail(sender_email, recipients, message.as_string())
        logging.info("✅ Summary email sent.")
    except Exception as e:
        logging.error(f"❌ Failed to send email: {str(e)}")