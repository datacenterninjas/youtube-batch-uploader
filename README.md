# YouTube Auto-Uploader & Monitor Dashboard

An automated local pipeline to monitor folders and upload videos directly to YouTube using the YouTube Data API v3, accompanied by a real-time Tkinter desktop monitoring dashboard.

---

## Features

### YouTube Auto-Uploader (`uploader.py`)
- **Folder Monitoring:** Automatically scans `videos_to_upload/` directories for video files (`.mp4`, `.mov`, `.mkv`, `.avi`).
- **Privacy Status Mapping:** The privacy status is mapped directly from the parent subfolder (`Public`, `Private`, `Unlisted`).
- **File Stabilization:** Waits for files to finish copying/rendering (verifying size stability over a 5-second interval) before starting the upload.
- **Title Sanitization:** Truncates titles to 95 characters, removes invalid character sequences (`<`, `>`), and replaces underscores with spaces.
- **Quota Management:** Automatically manages daily YouTube API limits (default maximum `6` uploads per day) and resets at midnight.
- **Network Resilience:** Automatically retries uploads with exponential backoff on transient network errors (up to 5 retries: 5s, 10s, 20s, 40s, 80s).
- **Graceful Error Handling:** Logs success/failure to local files and moves processed videos to `uploaded_archive/` or `failed_to_upload/` respectively.
- **Single-Instance Enforcement:** Uses file-locking mechanisms (`youtube_uploader.lock`) to prevent multiple instances from running simultaneously.

### Monitoring Dashboard (`dashboard.py`)
- **Process Status Tracking:** Uses `psutil` to check if `uploader.py` is currently running.
- **Upload Quota Counter:** Visualizes the progress of daily uploads.
- **Queue Count & Folder Status:** Tracks pending, successfully archived, and failed uploads in real-time.
- **Auto-Refresh:** Updates dashboard statistics automatically every 5 seconds.
- **Cross-Platform Interface:** Sleek desktop layout built using Python's standard `tkinter` library.

---

## Directory Structure

```text
antigrav/
├── uploader.py              # Main background upload processor
├── dashboard.py             # Desktop monitoring application (Tkinter)
├── client_secrets.json      # OAuth 2.0 Credentials (User provided)
├── token.pickle             # OAuth token storage (Auto-generated after login)
├── quota.json               # Tracks uploads for the current day (Auto-generated)
├── youtube_uploader.lock    # Prevents concurrent execution (Auto-generated)
├── success_logs.txt         # Success logs (Auto-generated)
├── error_logs.txt           # Failure/Error logs (Auto-generated)
│
├── videos_to_upload/        # Queue folder for videos to be uploaded
│   ├── Public/              # Videos here are uploaded as Public
│   ├── Private/             # Videos here are uploaded as Private
│   └── Unlisted/            # Videos here are uploaded as Unlisted
│
├── uploaded_archive/        # Successfully uploaded videos are moved here
└── failed_to_upload/        # Failed video uploads are moved here
```

---

## Installation & Setup

### 1. Prerequisites
- Python 3.8 or higher.
- A Google Cloud Project with the **YouTube Data API v3** enabled.
- OAuth 2.0 Client credentials file downloaded as `client_secrets.json` and placed in the project root directory.

### 2. Configure Virtual Environment & Install Dependencies
Initialize your virtual environment and install the required libraries:

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

# Install dependencies
pip install -r requirements.txt
```

---

## Usage

### 1. Preparing Videos
Move your video files into the respective subfolders under `videos_to_upload/` depending on the desired privacy setting:
- Place public videos in `videos_to_upload/Public/`
- Place private videos in `videos_to_upload/Private/`
- Place unlisted videos in `videos_to_upload/Unlisted/`

### 2. Running the Uploader
Execute the script to start processing the queue:

```bash
python uploader.py
```

*Note: On the first run, a browser tab will open asking you to authenticate with the Google account associated with your YouTube Channel. Once completed, a `token.pickle` file will be created to authenticate future uploads automatically.*

### 3. Launching the Dashboard
To monitor the uploading process in real-time, run the Tkinter dashboard:

```bash
python dashboard.py
```

---

## Internal Workings & Logic

### File Lock (`youtube_uploader.lock`)
To prevent concurrent upload processes from corrupting files or uploading the same video twice, a locking mechanism is used:
- **Windows:** Uses `msvcrt` library.
- **macOS/Linux:** Uses `fcntl` library.

### Quota Reset
The quota is stored in `quota.json`. Every time a video is successfully uploaded, the count is incremented. The script matches the current calendar date. If a new day is detected, it automatically resets the counter to `0`. If the daily count reaches the limit (default `6`), the script sleeps until midnight before continuing the queue processing.
