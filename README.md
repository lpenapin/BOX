# Box Document Intake & Conversion Pipeline

A Python-based workflow for automating Box file intake, claim-based routing, document conversion, and metadata tracking for operational document processing.

This project connects Box, file normalization, downstream conversion tools, and reporting into a repeatable batch pipeline designed for claim-driven document handling.

## Overview

The solution is built around a two-stage automation flow:

1. Download files from configured Box folders and organize them by claim number and business area.
2. Process incoming files into standardized output formats for downstream use, storage, and audit.

It supports a wide range of file types including images, emails, Office documents, archives, video, audio, and PDFs, while also capturing audit details in Excel and SQL Server.

## Key capabilities

- Box API authentication and token refresh handling
- Claim number extraction from file names and descriptions
- Structured file organization by business area and claim number
- Retry logic for transient download failures
- Duplicate-safe and Windows-compatible file naming
- Metadata capture for downloads and conversion results
- Email, image, archive, document, audio, and video handling
- PDF splitting and normalization for large or complex files
- Alerting and success notifications via email

## Architecture

```text
Box API
  │
  ▼
src/main.py
  ├── authenticates to Box
  ├── downloads files for configured folders
  ├── identifies claim numbers
  └── triggers conversion workflow

src/main_phase2.py
  └── executes batch processing pipeline

src/processing.py
  ├── classifies files by type
  ├── converts to target output format
  ├── preserves backup copies
  └── records metadata
```

## Workflow

### Phase 1: Download and classification

The download stage orchestrates Box access and organizes files before processing:

- authenticates to Box using configured credentials
- reads files from configured source folders
- resolves claim numbers from metadata and file names
- stores files in a claim-based folder structure
- logs successful, failed, and skipped files
- marks completed files as processed in Box when appropriate

### Phase 2: Conversion and normalization

The conversion stage handles the file processing pipeline:

- scans input folders for new files
- converts images, emails, documents, audio, and video
- handles compression and PDF splitting when required
- writes output to the normalized target structure
- preserves backups and keeps audit records

## Supported file types

- Images: JPG, PNG, TIFF, HEIC, BMP, GIF
- Emails: EML, MSG
- Documents: DOC, DOCX, PPT, PPTX
- Spreadsheets: XLS, XLSX, CSV
- Archives: ZIP, RAR, 7Z, TAR, GZ, TGZ, BZ2, XZ
- Audio: MP3, WAV, OGG, M4A, FLAC
- Video: MP4, MOV and compatible video sources
- PDF: split, normalized, copied or processed according to pipeline rules

## Tech stack

- Python
- Box SDK
- OpenPyXL
- Pandas
- Pillow and Pillow-Heif
- PyPDF2 / pypdf
- pydub
- Aspose Email
- SQL Server / pyodbc
- FFmpeg, LibreOffice, wkhtmltopdf
- .NET helper for MSG attachment extraction

## Project structure

```text
BOX/
├── README.md
├── box_tokens.json
├── licenses/
│   └── Aspose.Total.lic
├── extractAttachments/
│   ├── Program.cs
│   ├── extractAttachments.csproj
│   └── ...
├── src/
│   ├── __init__.py
│   ├── authentication_utils.py
│   ├── converters.py
│   ├── db_helpers.py
│   ├── downloader.py
│   ├── email_utils.py
│   ├── email_to_pdf_converter.py
│   ├── log_file.py
│   ├── main.py
│   ├── main_phase2.py
│   ├── metadata.py
│   ├── notifications.py
│   ├── pdf_utils.py
│   ├── processing.py
│   ├── utils.py
│   ├── utils_phase2.py
│   └── ...
├── msgatt/
├── Documentation/
└── ...
```

## Setup and configuration

The project relies on environment variables and local configuration values for secure runtime settings.

Typical settings include:

- Box client ID and secret
- Box folder IDs and token file
- local or network base paths for raw, input, output, backup, and claim storage
- SQL Server connection settings
- SMTP configuration for notifications
- external tool paths for FFmpeg, LibreOffice, wkhtmltopdf, and Aspose licensing

Example environment configuration:

```dotenv
BOX_CLIENT_ID=your-box-client-id
BOX_CLIENT_SECRET=your-box-client-secret
BOX_TOKEN_FILE=C:\Projects\_box_phase_1\box_tokens.json
DB_TRUSTED=true
DB_DRIVER=ODBC Driver 17 for SQL Server
DB_SERVER=server-name
DB_DATABASE=Box
DB_ENCRYPT=true
DB_TRUST_SERVER_CERT=false
```

## Getting started

1. Create a virtual environment.
2. Install the required Python dependencies.
3. Configure Box, SQL Server, and SMTP settings.
4. Validate the Box token and folder access.
5. Run the main download workflow.
6. Run the conversion workflow once files are present in the intake path.

Example install command:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install aspose-email boxsdk ffmpeg-python fpdf2 matplotlib openpyxl pandas pdfkit Pillow pillow-heif PyPDF2 pypdf pyodbc python-dateutil python-dotenv extract-msg reportlab pydub
```

## Security note

This project handles sensitive operational data including Box content, claim information, and enterprise metadata. Do not commit secrets, tokens, license files, or environment-specific configuration to source control.

## License and usage

This repository is intended for internal operational use and is structured around the current environment configuration required for production file processing. The code and workflows may be adapted for other document-processing use cases with appropriate dependency and security review.

## Status

The project is designed as a scheduled automation pipeline for real-world document intake and conversion work, with operational logging, retries, and metadata tracking built into the processing flow.

