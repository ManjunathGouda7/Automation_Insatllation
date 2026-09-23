# V-DPWR-EPR Software Auto-Updater

An automated pipeline in Python (tested on Python 3.14) that checks email notifications for the **V-DPWR-EPR** software, extracts the download link, downloads the installer, unpacks archives (if compressed as `.zip`), and launches the installation process on your machine.

---

## Architecture & Workflow

```mermaid
flowchart TD
    A[Start: python main.py] --> B[Load config.json]
    B --> C{Test URL provided?}
    C -- Yes --> F[Skip Email Check]
    C -- No --> D[Connect to IMAP Server\nFilter emails from today/yesterday]
    D --> E[Search for V-DPWR-EPR & Extract:\n- Version tag: [v1.1.1.X]\n- Installer URL from HTML or Text]
    E --> F[Download Installer via down.py\n- Parse Content-Disposition\n- Stream with live progress bar]
    F --> G{Is downloaded file a .zip?}
    G -- Yes --> H[Unpack ZIP via install.py\nFind setup.exe / installer binary]
    G -- No --> I[Locate .exe / .msi]
    H --> J[Execute Installer]
    I --> J
    J --> K[Installation Completed]
```

---

## File Structure

| File | Description |
|---|---|
| [`config.json`](config.json) | Configuration file containing email credentials, software target, filters, and preferences. |
| [`main.py`](main.py) | Main entry point and CLI orchestrator running the step-by-step pipeline. |
| [`mail.py`](mail.py) | Connects to the IMAP mailbox, applies date filters, and extracts versions and download links. |
| [`down.py`](down.py) | Streams files with progress reporting and extracts accurate filenames from HTTP headers. |
| [`install.py`](install.py) | Handles `.zip` archive extraction, installer executable discovery, and execution. |
| [`test_updater.py`](test_updater.py) | Unit test suite covering regex parsing, HTML link extraction, headers, and ZIP handling. |
| [`requirements.txt`](requirements.txt) | Required Python packages (`requests`, `beautifulsoup4`). |

---

## Configuration (`config.json`)

```json
{
  "imap_server": "outlook.office365.com",
  "email_user": "your_email@domain.com",
  "email_pass": "your_app_password",
  "target_software": "V-DPWR-EPR",
  "subject_keyword": "V-DPWR-EPR",
  "days_back": 2,
  "download_dir": "downloads",
  "silent_install": false,
  "test_download_url": ""
}
```

### Parameter Reference
* **`imap_server`**: Hostname of your email server (e.g. `outlook.office365.com` or `imap.gmail.com`).
* **`email_user`**: Email account username.
* **`email_pass`**: Email password (for Office 365, an **App Password** is required).
* **`target_software`**: Target software name to match (default: `"V-DPWR-EPR"`).
* **`subject_keyword`**: Keyword to search for in email subject lines or message bodies.
* **`days_back`**: How many days back to search (`2` checks today and yesterday).
* **`download_dir`**: Folder where downloaded installers are stored (default: `"downloads"`).
* **`silent_install`**: Set `true` to pass silent flags (`/S` for EXE, `/qn` for MSI) or `false` for normal interactive UI.
* **`test_download_url`**: Optional direct download link. If populated, can act as a fallback when offline.

---

## How It Works

### 1. Email Search & Parsing (`mail.py`)
* **Recent Date Filtering**:
  Uses IMAP `SINCE` query with dynamic dates (e.g. `(SINCE "22-Sep-2026")`) to check only recent emails (today and yesterday).
* **Variable Version Detection**:
  Dynamically matches variable version formats matching:
  > *"Please find the download link for V-DPWR-EPR software (version [v1.1.1.X])"*
  Handles any variable numbers such as `v1.1.1.25`, `1.2.0.4`, `v2.0.1.9`, etc.
* **HTML & Plain Text Extraction**:
  Uses `BeautifulSoup` to parse rich HTML content and extract URLs from `<a href="...">` anchor tags, as well as plain text URLs.
* **Scoring & Prioritization**:
  Prioritizes direct installer links ending in `.exe`, `.msi`, `.zip` and links associated with `"V-DPWR-EPR"` or `"download"`.

### 2. Downloading (`down.py`)
* Inspects HTTP `Content-Disposition` response headers (and URL redirect targets) to determine the exact filename (e.g. `V-DPWR-EPR_v1.1.1.2.zip`).
* Downloads the file in streaming chunks (64 KB) with an active console progress indicator showing percentage and MB transferred.
* Automatically sanitizes filenames to prevent illegal Windows filesystem characters.

### 3. Archive Extraction & Installation (`install.py`)
* **Automatic ZIP Unpacking**:
  If the downloaded file is a `.zip` archive, it extracts all files into `downloads/extracted_<archive_name>/`.
* **Installer Discovery**:
  Scans extracted files to find the setup executable (scoring files containing `setup`, `install`, `v-dpwr`, or `.msi` / `.exe`).
* **Execution**:
  * `.msi`: Runs via `msiexec /i <file>` (adds `/qn` if silent).
  * `.exe`: Runs binary directly (adds `/S` if silent).
  * Other file types: Opens using Windows shell handler (`os.startfile`).

---

## Prerequisites & Installation

### Requirements
* **Python 3.14** (or Python 3.10+)

### Setup Instructions
1. **Activate your virtual environment** (if using `env`):
   ```powershell
   .\env\Scripts\activate
   ```
2. **Install required dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

---

## Usage Guide

### 1. Run the Full Update Process
Checks recent emails, downloads the latest release, and launches the installer:
```powershell
python main.py
```
*(Or with the Python 3.14 launcher: `py -3.14 main.py`)*

### 2. Dry Run Mode (Download Only)
Downloads the latest installer to `downloads/` and validates it without running the installer:
```powershell
python main.py --dry-run
```

### 3. Silent / Unattended Installation
Runs the installation silently in the background:
```powershell
python main.py --silent
```

### 4. Direct Test URL (Bypass Email Check)
Test download and installation directly with a specific link:
```powershell
python main.py --test-url "https://example.com/files/V-DPWR-EPR_Setup.exe"
```

---

## Running Automated Tests

A unit test suite is included in [`test_updater.py`](test_updater.py) using Python's standard `unittest` framework:
```powershell
python test_updater.py -v
```
*(Or with the Python 3.14 launcher: `py -3.14 test_updater.py -v`)*

**Tests include:**
* Dynamic variable version pattern extraction.
* HTML email parsing and `<a href>` link prioritization.
* Plain text URL extraction.
* IMAP `SINCE` date formatting.
* HTTP `Content-Disposition` header filename extraction.
* ZIP archive extraction and installer discovery.

---

## Office 365 IMAP Authentication Note

Microsoft Exchange Online / Office 365 disables standard basic password authentication for IMAP (`AUTHENTICATE failed`).

To connect to your Office 365 account:
1. Log into your Microsoft account security dashboard:
   [https://mysignins.microsoft.com/security-info](https://mysignins.microsoft.com/security-info)
2. Click **Add sign-in method** $\rightarrow$ **App password**.
3. Generate a dedicated App Password and paste it into `"email_pass"` in [`config.json`](config.json).
