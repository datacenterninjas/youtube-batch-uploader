import os
import sys
if os.name == 'nt':
    import msvcrt
else:
    import fcntl
import time
import shutil
import pickle
import datetime
import json
import socket
import httplib2
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Define scopes and paths
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE = "token.pickle"
QUOTA_FILE = "quota.json"
MAX_DAILY_UPLOADS = 6

lock_file_pointer = None

def enforce_single_instance():
    global lock_file_pointer
    lock_file = "youtube_uploader.lock"
    try:
        if os.name == 'nt':
            lock_file_pointer = open(lock_file, 'w')
            msvcrt.locking(lock_file_pointer.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            lock_file_pointer = open(lock_file, 'w')
            fcntl.flock(lock_file_pointer, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError, PermissionError):
        print("⚠️ Another instance of the uploader is already running on this machine. Exiting safely.")
        sys.exit(0)

def get_timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_success(message):
    with open("success_logs.txt", "a") as f:
        f.write(f"[{get_timestamp()}] {message}\n")
    print(f"[SUCCESS] {message}")

def log_error(message):
    with open("error_logs.txt", "a") as f:
        f.write(f"[{get_timestamp()}] {message}\n")
    print(f"[ERROR] {message}")

def authenticate():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)
            
    if not creds or not creds.valid:
        try:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_FILE, "wb") as token:
                pickle.dump(creds, token)
        except RefreshError:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
            print("[CRITICAL ALERT] Token expired. Please run script manually to re-authenticate.")
            sys.exit(1)
            
    return build("youtube", "v3", credentials=creds)

def load_quota():
    """Reads the quota.json file and resets it if it's a new day."""
    today = datetime.date.today().isoformat()
    if os.path.exists(QUOTA_FILE):
        try:
            with open(QUOTA_FILE, "r") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data
        except json.JSONDecodeError:
            pass
    return {"date": today, "count": 0}

def save_quota(data):
    """Writes the quota data back to quota.json."""
    with open(QUOTA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def increment_quota():
    """Increments the successful upload count in quota.json."""
    data = load_quota()
    data["count"] += 1
    save_quota(data)

def get_seconds_until_midnight():
    """Calculates seconds until local midnight + 60s buffer."""
    now = datetime.datetime.now()
    tomorrow = now + datetime.timedelta(days=1)
    midnight = datetime.datetime(year=tomorrow.year, month=tomorrow.month, day=tomorrow.day, hour=0, minute=0, second=0)
    return (midnight - now).total_seconds() + 60  

def wait_for_file_to_stabilize(filepath):
    print(f"Waiting for {filepath} to stabilize...")
    previous_size = -1
    while True:
        try:
            current_size = os.path.getsize(filepath)
            if current_size == previous_size and current_size > 0:
                print(f"File {filepath} stabilized at {current_size} bytes.")
                return True
            previous_size = current_size
            time.sleep(5)
        except OSError:
            time.sleep(5)

def sanitize_title(title):
    title = title.replace("<", "").replace(">", "").replace("_", " ")
    return title[:95]

def upload_video(youtube, filepath, title, privacy_status):
    title = sanitize_title(title)
    body = {
        "snippet": {
            "title": title,
            "description": "Uploaded via Python Automation",
            "tags": ["automated"],
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": privacy_status.lower()
        }
    }
    insert_request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=MediaFileUpload(filepath, chunksize=-1, resumable=True)
    )
    print(f"Starting upload for {title} ({privacy_status})...")
    
    retries = 0
    max_retries = 5
    response = None
    
    while response is None:
        try:
            _, response = insert_request.next_chunk()
        except (HttpError, ConnectionResetError, socket.timeout, httplib2.ServerNotFoundError) as e:
            if isinstance(e, HttpError) and e.resp.status == 403 and "quotaExceeded" in str(e):
                raise e # Do not retry Quota Exhaustion
            
            if retries >= max_retries:
                raise e # Bubble up if max retries exceeded
                
            sleep_time = 5 * (2 ** retries) # 5, 10, 20, 40, 80...
            print(f"Network error: {e}. Retrying in {sleep_time} seconds (Attempt {retries + 1}/{max_retries})...")
            time.sleep(sleep_time)
            retries += 1
            
    return response

def scan_for_videos():
    """Scans subfolders and returns an alphabetically sorted list of pending video files."""
    valid_folders = ["Public", "Private", "Unlisted"]
    video_extensions = ('.mp4', '.mov', '.mkv', '.avi')
    base_dir = Path("videos_to_upload")
    queue = []
    
    if not base_dir.exists():
        return queue
        
    for folder_name in valid_folders:
        folder_path = base_dir / folder_name
        if not folder_path.exists():
            continue
        for file_path in folder_path.iterdir():
            if file_path.is_file() and file_path.name.lower().endswith(video_extensions):
                queue.append(file_path)
                
    # Sort alphabetically by filename
    queue.sort(key=lambda p: p.name)
    return queue

def main_loop(youtube_client):
    while True:
        quota_data = load_quota()
        count = quota_data.get("count", 0)
        
        if count >= MAX_DAILY_UPLOADS:
            sleep_seconds = get_seconds_until_midnight()
            hours = sleep_seconds / 3600
            print(f"Daily quota reached ({count}/{MAX_DAILY_UPLOADS}). Sleeping for {hours:.2f} hours until midnight...")
            time.sleep(sleep_seconds)
            continue
            
        queue = scan_for_videos()
        if not queue:
            print("Queue is empty. Sleeping for 60 seconds...")
            time.sleep(60)
            continue
            
        # Process the first video in the queue
        file_path = queue[0]
        original_title = file_path.stem
        privacy_status = file_path.parent.name
        
        print(f"Processing next video in queue: {file_path.name} ({count+1}/{MAX_DAILY_UPLOADS} for today)")
        wait_for_file_to_stabilize(str(file_path))
        
        try:
            upload_video(youtube_client, str(file_path), original_title, privacy_status)
            increment_quota()
            log_success(f"Successfully uploaded {original_title}. Moving to archive.")
            shutil.move(str(file_path), os.path.join("uploaded_archive", file_path.name))
        except HttpError as e:
            if e.resp.status == 403 and "quotaExceeded" in str(e):
                err_msg = f"Quota exceeded (API limit) while uploading {original_title}."
                log_error(err_msg)
                print("[CRITICAL ALERT] YouTube API Quota Exceeded. Forcing script to sleep until tomorrow.")
                # Mark quota as maxed out so the loop sleeps on the next iteration
                quota_data = load_quota()
                quota_data["count"] = MAX_DAILY_UPLOADS
                save_quota(quota_data)
            else:
                err_msg = f"HTTP Error {e.resp.status} during upload of {original_title}: {str(e)}"
                log_error(err_msg)
                if os.path.exists(file_path):
                    shutil.move(str(file_path), os.path.join("failed_to_upload", file_path.name))
        except Exception as e:
            err_msg = f"Unexpected error during upload of {original_title}: {str(e)}"
            log_error(err_msg)
            if os.path.exists(file_path):
                shutil.move(str(file_path), os.path.join("failed_to_upload", file_path.name))
                
        # Small delay before grabbing the next file in the queue
        time.sleep(2)

if __name__ == "__main__":
    enforce_single_instance()
    
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"Error: {CLIENT_SECRETS_FILE} not found. Please add your credentials.")
        exit(1)
        
    print("Authenticating with YouTube...")
    youtube_client = authenticate()
    print("Authentication successful.")
    
    print("Starting Batch Queue Processor...")
    try:
        main_loop(youtube_client)
    except KeyboardInterrupt:
        print("\nProcessor gracefully stopped by user.")
