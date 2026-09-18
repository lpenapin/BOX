# Box File Downloader and Converter

Python automation for downloading files from Box, organizing them by claim number and business area, converting supported content to standardized formats, and recording processing metadata.

> **Status:** Presentation-only documentation for an internal operational utility. Production source code, credentials, tokens, license files, and infrastructure configuration are intentionally not part of the public project.

## Contents

- [Overview](#overview)
- [Features](#features)
- [Technical design](#technical-design)
- [C# attachment extractor](#c-attachment-extractor)
- [Requirements](#requirements)
- [Configuration](#configuration)
- [Installation](#installation)
- [Usage](#usage)
- [Output and observability](#output-and-observability)
- [Implementation plan](#implementation-plan)
- [Future requirements](#future-requirements)
- [Risks and mitigations](#risks-and-mitigations)
- [Security checklist before publishing](#security-checklist-before-publishing)
- [Repository layout](#repository-layout)

## Overview

The application runs as a two-phase batch pipeline:

1. **Download phase:** authenticates with Box, refreshes the OAuth token, reads configured Box folders, extracts claim numbers from file names and descriptions, downloads files to a network location, and records download metadata.
2. **Conversion phase:** scans the input directory, converts or copies files into the target format/location, preserves a backup copy, and records the result in per-claim Excel metadata and SQL Server.

The main entry point is `main.py`. It is designed for scheduled, long-running execution and repeats the download/conversion cycle at approximately 50-minute intervals until the configured end-of-day cutoff.

## Features

- Box OAuth authentication using access and refresh tokens.
- Token refresh and persistence in a local JSON file.
- Download organization by Box business-area folder and claim number.
- Claim number detection from file names and descriptions.
- Duplicate-safe and Windows-compatible file naming.
- Processing of:
  - Images, including HEIC conversion and EXIF orientation handling.
  - Email files (`.eml` and `.msg`) with embedded images and attachments.
  - Office documents converted to PDF.
  - Archives extracted with protection against `autorun.inf`.
  - Audio converted to MP3.
  - Video converted to H.264/AAC MP4.
  - Excel/CSV files copied to the output.
- PDF splitting by configured size/page limits.
- Per-claim Excel metadata logs.
- SQL Server download and conversion audit logs.
- SMTP summary and alert emails.

## Technical design

### Logical architecture

```text
Box API
  |
  v
main.py
  |
  +--> authentication_utils.py
  |      OAuth token loading, refresh, and persistence
  |
  +--> downloader.py
  |      Folder enumeration, claim extraction, download, metadata logging
  |
  +--> db_helpers.py
  |      SQL Server connectivity and audit inserts
  |
  +--> log_file.py
  |      Per-claim CSV exports from SQL Server
  |
  +--> main_phase2.py
         |
         +--> processing.py
         |      File classification and batch orchestration
         |
         +--> converters.py / email_utils.py
         |      File conversion and email extraction
         |          |
         |          +--> extractAttachments (C#/.NET)
         |                 MSG attachment extraction
         |
         +--> metadata.py
                Excel and SQL Server conversion audit records
```

### Data flow

1. Authenticate to Box using the configured client credentials and stored refresh token.
2. Enumerate the configured Box source folders.
3. Retrieve file metadata and resolve the actor/uploader when available.
4. Extract one or more claim numbers from the file name and description.
5. Store files under a business-area/claim-number directory.
6. Write download metadata to Excel and `BOX_FileDownloadLog`.
7. Process files from the phase-two input directory.
8. Write converted files to the output directory and preserve source files in the backup directory.
9. Write conversion results to `Xerox_Final_Metadata.xlsx` and `FinalMetadataLog`.
10. Send summary or alert email notifications.

### Reliability and idempotency behavior

- File names are sanitized, truncated for Windows path limits, and made unique with version suffixes.
- Download operations retry up to three times.
- Metadata tables and workbook headers are created or reconciled when needed.
- Individual conversion failures are logged as failed metadata records so the batch can continue.
- Network paths and external services remain required for successful end-to-end execution.

## C# attachment extractor

The [`extractAttachments/`]() project is a small C#/.NET helper used by the Python email-processing flow for Outlook `.msg` files.

### Responsibilities

- Load an Outlook `.msg` file through Aspose.Email.
- Extract embedded and regular attachments.
- Preserve attachment names when available.
- Add a `.msg` extension to embedded Outlook messages.
- Sanitize Windows-invalid filename characters.
- Detect a file extension from its content when the attachment has no usable extension.
- Avoid overwriting an existing attachment by generating a unique filename.
- Save extracted files into a temporary output directory consumed by Python.

### Command-line interface

The compiled helper expects three arguments:

```text
extractAttachments.exe <msg-file> <output-directory> <aspose-license-path>
```

The Python integration invokes this executable from `email_utils.py`, then copies the extracted files from the temporary directory into the claim's output directory for further processing.

### Build requirements

- .NET 8 SDK.
- The `Aspose.Email` NuGet package, currently referenced at version `22.8.0`.
- A valid Aspose.Email license.

Build from the C# project directory:

```powershell
dotnet restore .\extractAttachments.csproj
dotnet build .\extractAttachments.csproj --configuration Release
```

The generated `bin/` and `obj/` directories are build artifacts and should not be included in a presentation repository. The source files, project file, and solution files are sufficient to explain or reproduce the component, subject to the applicable Aspose.Email license.

## Requirements

### Runtime

- Windows 10/11 or Windows Server.
- Python 3.10 or later.
- .NET 8 SDK/runtime for building or running `extractAttachments`.
- Access to the configured Box folders and Box API.
- Microsoft SQL Server access.
- SQL Server ODBC Driver 17 or later.
- SMTP relay access.
- Read/write access to the configured local or UNC paths.

### Python packages

The project currently imports the following third-party packages. Because no `requirements.txt` is present, create one for the deployment environment and pin versions after validation:

```text
aspose-email
boxsdk
ffmpeg-python
fpdf2
matplotlib
openpyxl
pandas
pdfkit
Pillow
pillow-heif
PyPDF2
pypdf
pyodbc
python-dateutil
python-dotenv
extract-msg
reportlab
pydub
```

Install the package dependencies with:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install aspose-email boxsdk ffmpeg-python fpdf2 matplotlib openpyxl pandas pdfkit Pillow pillow-heif PyPDF2 pypdf pyodbc python-dateutil python-dotenv extract-msg reportlab pydub
```

### Native and licensed dependencies

The following are not installed by the Python command above:

- **FFmpeg**, available on `PATH`, for video and audio processing.
- **LibreOffice**, currently expected at `C:\Program Files\LibreOffice\program\soffice.exe`.
- **wkhtmltopdf**, used by the email-to-PDF flow and currently configured at `C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe`.
- **Aspose.Email for Python via .NET** license files.
- **Aspose.Email for .NET** for the C# attachment extractor.
- Microsoft SQL Server ODBC driver.

## Configuration

The current operational paths and non-secret settings are centralized in `__init__.py`. Database connection values are loaded from environment variables by `db_helpers.py`; no database credential defaults should be stored in source code.

At minimum, configure:

| Area | Values |
| --- | --- |
| Box | Client ID, client secret, token file, source folder IDs, completed-folder IDs |
| Storage | Download root, conversion input/output roots, backup root, claims root |
| Database | `DB_DRIVER`, `DB_SERVER`, `DB_DATABASE`, `DB_TRUSTED`, `DB_UID`, `DB_PWD`, encryption flags |
| Email | Sender, recipients, SMTP server, SMTP port |
| Conversion | FFmpeg, LibreOffice, wkhtmltopdf, Aspose licenses, attachment extractor path |

Example `.env` values for SQL Server:

```dotenv
BOX_CLIENT_ID=your-box-client-id
BOX_CLIENT_SECRET=use-an-approved-secret-store
BOX_TOKEN_FILE=C:\Projects\_box_phase_1\box_tokens.json
DB_TRUSTED=true
DB_DRIVER=ODBC Driver 17 for SQL Server
DB_SERVER=server-name
DB_DATABASE=Box
DB_ENCRYPT=true
DB_TRUST_SERVER_CERT=false
```

For SQL authentication, use a secret-management solution or protected deployment variable for `DB_UID` and `DB_PWD`. Do not commit credentials, Box tokens, license files, or private network details.

