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

import database
import analyzer
import metadata_generator
import thumbnail_analyzer
import config

# Define scopes and paths
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE = "token.pickle"
QUOTA_FILE = "quota.json"

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
    with open(QUOTA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def increment_quota():
    data = load_quota()
    data["count"] += 1
    save_quota(data)

def get_seconds_until_midnight():
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

def upload_video(youtube, filepath, video_row):
    title = video_row.get("title") or Path(filepath).stem
    description = video_row.get("description") or "Uploaded via YouTube Auto Publisher"
    tags_str = video_row.get("tags") or "automated"
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    privacy_status = (video_row.get("privacy") or "unlisted").lower()
    
    body = {
        "snippet": {
            "title": title[:95],
            "description": description,
            "tags": tags,
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": privacy_status
        }
    }
    
    insert_request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=MediaFileUpload(filepath, chunksize=-1, resumable=True)
    )
    print(f"Starting YouTube upload for '{title}' ({privacy_status})...")
    
    retries = 0
    max_retries = config.get_setting("max_upload_retries", 5)
    response = None
    
    while response is None:
        try:
            _, response = insert_request.next_chunk()
        except (HttpError, ConnectionResetError, socket.timeout, httplib2.ServerNotFoundError) as e:
            if isinstance(e, HttpError) and e.resp.status == 403 and "quotaExceeded" in str(e):
                raise e
            if retries >= max_retries:
                raise e
            sleep_time = 5 * (2 ** retries)
            print(f"Network error: {e}. Retrying in {sleep_time}s (Attempt {retries + 1}/{max_retries})...")
            time.sleep(sleep_time)
            retries += 1
            
    return response

def scan_for_videos():
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
                
    queue.sort(key=lambda p: p.name)
    return queue

def main_loop(youtube_client):
    database.init_db()
    
    while True:
        cfg = config.load_config()
        max_quota = cfg.get("daily_upload_limit", 6)
        quota_data = load_quota()
        count = quota_data.get("count", 0)
        
        if count >= max_quota:
            sleep_seconds = get_seconds_until_midnight()
            hours = sleep_seconds / 3600
            print(f"Daily quota reached ({count}/{max_quota}). Sleeping for {hours:.2f} hours until midnight...")
            time.sleep(sleep_seconds)
            continue
            
        queue = scan_for_videos()
        if not queue:
            print("Queue is empty. Sleeping for 60 seconds...")
            time.sleep(60)
            continue
            
        file_path = queue[0]
        original_title = file_path.stem
        privacy_status = file_path.parent.name
        
        # 1. Register Video
        video_record, is_duplicate = database.register_video(file_path, privacy_status)
        video_id = video_record['id']
        current_status = video_record['status']
        
        if is_duplicate and current_status in ('UPLOADED', 'ARCHIVED', 'DUPLICATE'):
            print(f"⚠️ Duplicate video hash detected: {video_record['file_hash']}. Archiving without upload.")
            database.update_video_status(video_id, 'DUPLICATE', error_message="Duplicate file hash detected.")
            shutil.move(str(file_path), os.path.join("uploaded_archive", file_path.name))
            continue

        approval_mode = cfg.get("approval_mode", "review")

        # If already analyzed and awaiting approval, don't re-analyze
        if current_status == "AWAITING_APPROVAL":
            if approval_mode == "review":
                print(f"⏳ Video #{video_id} ('{file_path.name}') is AWAITING_APPROVAL in Web Dashboard...")
                time.sleep(15)
                continue

        # Run analysis pipeline only if video is newly discovered
        if current_status in ("DISCOVERED", "STABILIZING"):
            # 2. File Stabilization Check
            database.update_video_status(video_id, 'STABILIZING')
            wait_for_file_to_stabilize(str(file_path))
            
            # 3. Video Metadata & Frame Extraction (Sprint 3)
            try:
                analyzer.analyze_video(video_id, str(file_path))
            except Exception as e:
                print(f"⚠️ Analysis note: {e}")
                
            # 4. Generate Metadata (Sprint 4)
            try:
                metadata_generator.generate_metadata(video_id, file_path.name, privacy_status)
            except Exception as e:
                print(f"⚠️ Metadata note: {e}")
                
            # 5. Thumbnail Selection (Sprint 7)
            try:
                thumbnail_analyzer.select_best_thumbnails(video_id)
            except Exception as e:
                print(f"⚠️ Thumbnail note: {e}")

            current_status = database.get_video_by_id(video_id)['status']

        # Check Approval Mode (AUTO vs REVIEW)
        if approval_mode == "review" and current_status not in ("READY_TO_UPLOAD", "UPLOADING"):
            database.update_video_status(video_id, 'AWAITING_APPROVAL')
            print(f"⏳ Video #{video_id} ('{file_path.name}') is AWAITING_APPROVAL in Web Dashboard...")
            time.sleep(15)
            continue

        # 6. Upload
        database.update_video_status(video_id, 'UPLOADING')
        database.increment_upload_attempts(video_id)
        current_attempt = (video_record.get('upload_attempts') or 0) + 1
        
        video_record = database.get_video_by_id(video_id)
        
        try:
            response = upload_video(youtube_client, str(file_path), video_record)
            yt_id = response.get("id") if response else None
            yt_url = f"https://youtu.be/{yt_id}" if yt_id else None
            
            increment_quota()
            log_success(f"Successfully uploaded {original_title} (YouTube ID: {yt_id}). Moving to archive.")
            database.log_attempt(video_id, current_attempt, 'SUCCESS')
            database.update_video_status(video_id, 'UPLOADED', youtube_video_id=yt_id, youtube_url=yt_url)
            
            shutil.move(str(file_path), os.path.join("uploaded_archive", file_path.name))
            database.update_video_status(video_id, 'ARCHIVED')
            
        except HttpError as e:
            if e.resp.status == 403 and "quotaExceeded" in str(e):
                err_msg = f"Quota exceeded (API limit) while uploading {original_title}."
                log_error(err_msg)
                print("[CRITICAL ALERT] YouTube API Quota Exceeded. Forcing script to sleep until tomorrow.")
                database.log_attempt(video_id, current_attempt, 'FAILED', error=err_msg)
                database.update_video_status(video_id, 'UPLOAD_FAILED', error_message=err_msg)
                
                quota_data = load_quota()
                quota_data["count"] = max_quota
                save_quota(quota_data)
            else:
                err_msg = f"HTTP Error {e.resp.status} during upload of {original_title}: {str(e)}"
                log_error(err_msg)
                database.log_attempt(video_id, current_attempt, 'FAILED', error=err_msg)
                database.update_video_status(video_id, 'UPLOAD_FAILED', error_message=err_msg)
                if os.path.exists(file_path):
                    shutil.move(str(file_path), os.path.join("failed_to_upload", file_path.name))
        except Exception as e:
            err_msg = f"Unexpected error during upload of {original_title}: {str(e)}"
            log_error(err_msg)
            database.log_attempt(video_id, current_attempt, 'FAILED', error=err_msg)
            database.update_video_status(video_id, 'UPLOAD_FAILED', error_message=err_msg)
            if os.path.exists(file_path):
                shutil.move(str(file_path), os.path.join("failed_to_upload", file_path.name))
                
        time.sleep(2)

if __name__ == "__main__":
    enforce_single_instance()
    
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"Error: {CLIENT_SECRETS_FILE} not found. Please add your credentials.")
        exit(1)
        
    print("Authenticating with YouTube...")
    youtube_client = authenticate()
    print("Authentication successful.")
    
    print("Starting YouTube Auto Publisher V2 Engine...")
    try:
        main_loop(youtube_client)
    except KeyboardInterrupt:
        print("\nPublisher engine gracefully stopped by user.")
