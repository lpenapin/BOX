import email
from email import policy
from email.parser import BytesParser
import extract_msg
import pdfkit
from pathlib import Path
import base64
import re
import tempfile
from PIL import Image
import io
import logging


def resize_image(image_data, max_width=800, max_height=1000):
    """Resize image to fit within max dimensions while maintaining aspect ratio"""
    try:
        # Open image from bytes
        img = Image.open(io.BytesIO(image_data))
        
        # Get original dimensions
        original_width, original_height = img.size
        
        # Calculate new dimensions maintaining aspect ratio
        ratio = min(max_width / original_width, max_height / original_height)
        
        # Only resize if image is larger than max dimensions
        if ratio < 1:
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Save to bytes
        output = io.BytesIO()
        # Preserve original format or default to JPEG
        img_format = img.format if img.format else 'JPEG'
        if img_format == 'JPEG':
            img.save(output, format=img_format, quality=85, optimize=True)
        else:
            img.save(output, format=img_format, optimize=True)
        
        return output.getvalue()
    except Exception as e:
        logging.warning(f"⚠️[Email] Error resizing in line image, returning original. - {e}")
        #print(f"Error resizing image: {e}")
        return image_data  # Return original if resize fails

def extract_eml_content(eml_path):
    """Extract content from .eml file"""
    with open(eml_path, 'rb') as f:
        msg = BytesParser(policy=policy.default).parse(f)
    
    # Extract headers
    subject = msg.get('subject', 'No Subject')
    from_addr = msg.get('from', 'Unknown')
    to_addr = msg.get('to', 'Unknown')
    cc_addr = msg.get('cc', 'Unknown')  # New
    date = msg.get('date', 'Unknown')
    
    # Extract body
    html_body = None
    text_body = None
    attachments = []
    attachment_names = []  # Track all attachment filenames
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get('Content-Disposition', ''))

            # Get filename if this part has one
            filename = part.get_filename()
            if filename:
                attachment_names.append(filename)
            
            if content_type == 'text/html' and 'attachment' not in content_disposition:
                content = part.get_content()
                # Ensure content is string
                html_body = content if isinstance(content, str) else content.decode('utf-8', errors='ignore')
            elif content_type == 'text/plain' and 'attachment' not in content_disposition and not html_body:
                content = part.get_content()
                text_body = content if isinstance(content, str) else content.decode('utf-8', errors='ignore')
            elif content_type.startswith('image/'):
                cid = part.get('Content-ID', '').strip('<>')
                if cid:
                    attachments.append({
                        'content_type': content_type,
                        'data': part.get_payload(decode=True),
                        'cid': cid,
                        'filename': filename or 'unnamed_image'
                    })
    else:
        content_type = msg.get_content_type()
        content = msg.get_content()
        if content_type == 'text/html':
            html_body = content if isinstance(content, str) else content.decode('utf-8', errors='ignore')
        else:
            text_body = content if isinstance(content, str) else content.decode('utf-8', errors='ignore')
    
    return {
        'subject': subject,
        'from': from_addr,
        'to': to_addr,
        'cc' : cc_addr, #new
        'date': date,
        'html_body': html_body,
        'text_body': text_body,
        'attachments': attachments,  # Images for embedding
        'attachment_names': attachment_names  # All attachment names for display
    }

def extract_msg_content(msg_path):
    """Extract content from .msg file"""
    msg = extract_msg.Message(msg_path)
    
    html_body = msg.htmlBody
    text_body = msg.body if not html_body else None
    
    # Ensure content is string, not bytes
    if html_body and isinstance(html_body, bytes):
        html_body = html_body.decode('utf-8', errors='ignore')
    if text_body and isinstance(text_body, bytes):
        text_body = text_body.decode('utf-8', errors='ignore')
    
    attachments = []
    attachment_names = []  # Track all attachment filenames
    for attachment in msg.attachments:
        # Get the filename
        #filename = getattr(attachment, 'longFilename', None) or getattr(attachment, 'shortFilename', 'unnamed_attachment')
        long_name = getattr(attachment, 'longFilename', None)
        short_name = getattr(attachment, 'shortFilename', None)
        
        filename = long_name or short_name or 'unnamed_attachment'
        # Add to names list for display in header
        attachment_names.append(filename)

        if hasattr(attachment, 'data') and attachment.mimetype and attachment.mimetype.startswith('image/'):
            cid = getattr(attachment,'cid','')
            if cid:
                att_data = attachment.data
                # Ensure data is bytes
                if isinstance(att_data, str):
                    att_data = att_data.encode('utf-8')
                attachments.append({
                    'content_type': attachment.mimetype,
                    'data': att_data,
                    'cid': getattr(attachment, 'cid', '')
                })
    
    return {
        'subject': msg.subject or 'No Subject',
        'from': msg.sender or 'Unknown',
        'to': msg.to or 'Unknown',
        'cc' : msg.cc or 'Unknown', #new
        'date': str(msg.date) if msg.date else 'Unknown',
        'html_body': html_body,
        'text_body': text_body,
        'attachments': attachments,  # Images for embedding
        'attachment_names': attachment_names  # All attachment names for display
    }

def embed_images(html_content, attachments):
    """Embed images as base64 data URIs"""
    if not html_content or not attachments:
        return html_content
    
    # Ensure html_content is a string
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8', errors='ignore')
    
    # Create a mapping of CID to base64 data
    cid_map = {}
    for att in attachments:
        if att['cid']:
            resized_data = resize_image(att['data'], max_width=800, max_height=1000)
            b64_data = base64.b64encode(resized_data).decode('utf-8')
            data_uri = f"data:{att['content_type']};base64,{b64_data}"
            cid_map[att['cid']] = data_uri
    
    # Replace cid: references with data URIs
    for cid, data_uri in cid_map.items():
        html_content = re.sub(
            f'src=["\']cid:{re.escape(cid)}["\']',
            f'src="{data_uri}"',
            html_content,
            flags=re.IGNORECASE
        )
    
    return html_content

def create_html_template(email_data):
    """Create HTML template with email content"""
    import html
    
    html_body = email_data.get('html_body')
    text_body = email_data.get('text_body')
    
    # Embed images in HTML body
    if html_body:
        html_body = embed_images(html_body, email_data.get('attachments', []))
        # Clean up excessive newlines in HTML
        # Remove \r\n, \n, \r that appear as literal text
        html_body = html_body.replace('\\n', '').replace('\\r', '')
        body_content = html_body
    elif text_body:
        # Escape HTML characters and convert plain text to HTML
        escaped_text = html.escape(text_body)
        # Replace newlines with <br> tags for proper rendering
        formatted_text = escaped_text.replace('\n', '<br>')
        body_content = f'<div style="white-space: pre-wrap; font-family: Arial, sans-serif;">{formatted_text}</div>'
    else:
        body_content = '<p>No content available</p>'

    # Escape header values to prevent HTML injection
    subject = html.escape(str(email_data['subject']))
    from_addr = html.escape(str(email_data['from']))
    to_addr = html.escape(str(email_data['to']))
    cc_addr = html.escape(str(email_data["cc"]))
    date = html.escape(str(email_data['date']))
    
    # Get attachment names
    attachment_names = email_data.get('attachment_names', [])
    if attachment_names:
        # Create a nice list format
        attachments_html = ', '.join([html.escape(str(name or 'Unknown')) for name in attachment_names])
    else:
        attachments_html = 'None'

    if cc_addr != 'Unknown':
        cc_block = f"""    
        <div class="email-header-item">
            <span class="email-header-label">Cc:</span>
            <span>{cc_addr}</span>
        </div>"""
    else:
        cc_block = ""  # If Unknown it injects nothing
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 20px;
                line-height: 1.6;
            }}
            .email-header {{
                border-bottom: 2px solid #333;
                padding-bottom: 15px;
                margin-bottom: 20px;
            }}
            .email-header-item {{
                margin: 5px 0;
            }}
            .email-header-label {{
                font-weight: bold;
                display: inline-block;
                width: 80px;
            }}
            .email-body {{
                margin-top: 20px;
            }}
            img {{
                max-width: 100%;
                height: auto;
                page-break-inside: avoid;
                page-break-before: auto;
                page-break-after: auto;
            }}
        </style>
    </head>
    <body>
        <div class="email-header">
            <div class="email-header-item">
                <span class="email-header-label">Subject:</span>
                <span>{subject}</span>
            </div>
            <div class="email-header-item">
                <span class="email-header-label">From:</span>
                <span>{from_addr}</span>
            </div>
            <div class="email-header-item">
                <span class="email-header-label">To:</span>
                <span>{to_addr}</span>
            </div>
            {cc_block}
            <div class="email-header-item">
                <span class="email-header-label">Date:</span>
                <span>{date}</span>
            </div>
            <div class="email-header-item">
                <span class="email-header-label">Att.:</span>
                <span>{attachments_html}</span>
            </div>
        </div>
        <div class="email-body">
            {body_content}
        </div>
    </body>
    </html>
    """
    
    return html_template

def convert_email_to_pdf(email_path, pdf_path, wkhtmltopdf_path=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"):
    """
    Convert email file to PDF
    
    Args:
        email_path: Path to .eml or .msg file
        pdf_path: Destination path for PDF file
        wkhtmltopdf_path: Optional path to wkhtmltopdf executable
                         If None, will try to find it automatically
    
    Returns:
        int: Total number of pages in the generated PDF
    """
    from PyPDF2 import PdfReader
    
    email_path = Path(email_path)
    pdf_path = Path(pdf_path)
    
    # Ensure destination directory exists
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Extract email content based on file type
    if email_path.suffix.lower() == '.eml':
        email_data = extract_eml_content(email_path)
    elif email_path.suffix.lower() == '.msg':
        email_data = extract_msg_content(email_path)
    else:
        raise ValueError(f"Unsupported file format: {email_path.suffix}")
    
    # Create HTML content
    html_content = create_html_template(email_data)

    # Configure pdfkit
    config = None
    if wkhtmltopdf_path:
        config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
        logging.info(f"wkhtmltopdf SET {wkhtmltopdf_path}")
    
    # PDF options for better rendering
    options = {
        'encoding': 'UTF-8',
        'enable-local-file-access': "",
        'print-media-type': None,
        'no-outline': None
    }
    
    # Convert HTML to PDF
    try:
        pdfkit.from_string(html_content, str(pdf_path), options=options, configuration=config)
    except Exception as e:
        # If direct conversion fails, try with temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            temp_html = f.name
        
        try:
            pdfkit.from_file(temp_html, str(pdf_path), options=options, configuration=config)
        finally:
            Path(temp_html).unlink(missing_ok=True)
    
    # Get page count from generated PDF
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    
    logging.info(f"[EMAIL]PDF successfully created at: {pdf_path}")
    logging.info(f"Total pages: {total_pages}")
    
    return total_pages


# Example usage
if __name__ == "__main__":
    # Specify your paths here
    email_file_path = r"C:\file_location\email_test.msg"  # or .eml
    output_pdf_path = r"C:\file_location\email_test.pdf"
    
    # If wkhtmltopdf is not in PATH, specify its location:
    # wkhtmltopdf_exe = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
    # convert_email_to_pdf(email_file_path, output_pdf_path, wkhtmltopdf_path=wkhtmltopdf_exe)
    
    total_pages = convert_email_to_pdf(email_file_path, output_pdf_path)
    print(f"The PDF has {total_pages} page(s)")
