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
    video_id = video_row.get("id")
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
    
    # 2MB chunks for smooth, real-time progress callbacks
    chunk_size = 2 * 1024 * 1024
    media = MediaFileUpload(str(filepath), chunksize=chunk_size, resumable=True)
    
    insert_request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media
    )
    print(f"🚀 Starting YouTube upload for '{title}' ({privacy_status})...")
    import activity_tracker
    activity_tracker.update_video_progress(video_id, "UPLOADING", f"🚀 Uploading '{title}' to YouTube (0%)...", 0)
    
    retries = 0
    max_retries = config.get_setting("max_upload_retries", 5)
    response = None
    
    while response is None:
        try:
            status, response = insert_request.next_chunk()
            if status:
                progress = status.progress() # float between 0.0 and 1.0
                pct = int(progress * 100)
                msg = f"🚀 Uploading '{title}' to YouTube ({pct}% complete)..."
                print(f"[UPLOAD PROGRESS] Video {video_id}: {pct}%")
                activity_tracker.update_video_progress(video_id, "UPLOADING", msg, pct)
        except (HttpError, ConnectionResetError, socket.timeout, httplib2.ServerNotFoundError) as e:
            if isinstance(e, HttpError) and e.resp.status == 403 and "quotaExceeded" in str(e):
                raise e
            if retries >= max_retries:
                raise e
            sleep_time = 5 * (2 ** retries)
            print(f"Network error: {e}. Retrying in {sleep_time}s (Attempt {retries + 1}/{max_retries})...")
            time.sleep(sleep_time)
            retries += 1
            
    activity_tracker.update_video_progress(video_id, "UPLOADED", f"✅ Successfully uploaded '{title}' to YouTube!", 100, active=False)
    return response

def scan_for_videos():
    """Scans videos_to_upload directory and all subfolders for any video files."""
    video_extensions = ('.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.flv', '.wmv', '.3gp', '.mpeg', '.mpg')
    base_dir = Path("videos_to_upload")
    queue = []
    
    if not base_dir.exists():
        return queue
        
    for p in base_dir.rglob("*"):
        if p.is_file() and p.name.lower().endswith(video_extensions) and not p.name.startswith("."):
            queue.append(p)
                
    queue.sort(key=lambda item: item.name)
    return queue

def main_loop(youtube_client, stop_event=None, wake_event=None):
    database.init_db()
    
    while True:
        if stop_event and stop_event.is_set():
            break
            
        cfg = config.load_config()
        max_quota = cfg.get("daily_upload_limit", 6)
        quota_data = load_quota()
        count = quota_data.get("count", 0)
        
        if count >= max_quota:
            sleep_seconds = get_seconds_until_midnight()
            hours = sleep_seconds / 3600
            print(f"Daily quota reached ({count}/{max_quota}). Sleeping for {hours:.2f} hours until midnight...")
            if wake_event:
                wake_event.wait(timeout=sleep_seconds)
                wake_event.clear()
            else:
                time.sleep(sleep_seconds)
            continue
            
        queue = scan_for_videos()
        if not queue:
            if wake_event:
                wake_event.wait(timeout=5)
                wake_event.clear()
            else:
                time.sleep(5)
            continue
            
        file_path = queue[0]
        original_title = file_path.stem
        privacy_status = file_path.parent.name if file_path.parent.name in ("Public", "Private", "Unlisted") else "unlisted"
        
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
                if wake_event:
                    wake_event.wait(timeout=5)
                    wake_event.clear()
                else:
                    time.sleep(5)
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
        if not os.path.exists(file_path):
            found = False
            candidates = [
                Path(os.path.expanduser(config.get_setting("return_directory", "~/Downloads"))) / file_path.name,
                Path("uploaded_archive") / file_path.name,
                Path("failed_to_upload") / file_path.name,
            ]
            for candidate in candidates:
                if candidate.exists():
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(candidate), str(file_path))
                    found = True
                    break
            if not found:
                err_msg = f"Video file '{file_path.name}' is not in staging. Drag and drop it onto the Web UI to upload."
                database.update_video_status(video_id, 'UPLOAD_FAILED', error_message=err_msg)
                print(f"⚠️ {err_msg}")
                continue

        import activity_tracker
        activity_tracker.set_activity("UPLOADING", f"🚀 Uploading '{original_title}' to YouTube...", progress=75)
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
            activity_tracker.clear_activity()
            
            return_dir = os.path.expanduser(config.get_setting("return_directory", "~/Downloads"))
            os.makedirs(return_dir, exist_ok=True)
            dest_path = os.path.join(return_dir, file_path.name)
            if str(file_path) != str(dest_path):
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                shutil.move(str(file_path), dest_path)
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

def process_single_video_upload(video_id):
    """Directly uploads a single video immediately on demand in a worker thread."""
    database.init_db()
    video_record = database.get_video_by_id(video_id)
    if not video_record:
        print(f"⚠️ Video #{video_id} not found.")
        return False
        
    original_title = video_record.get('title') or video_record.get('filename')
    file_path = Path(video_record['file_path'])
    
    # Locate candidate files if missing
    if not file_path.exists():
        candidates = [
            Path(os.path.expanduser(config.get_setting("return_directory", "~/Downloads"))) / file_path.name,
            Path("videos_to_upload/Unlisted") / file_path.name,
            Path("videos_to_upload/Public") / file_path.name,
            Path("videos_to_upload/Private") / file_path.name,
            Path("uploaded_archive") / file_path.name,
            Path("failed_to_upload") / file_path.name,
        ]
        for c in candidates:
            if c.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(c), str(file_path))
                break

    if not file_path.exists():
        err_msg = f"Video file '{file_path.name}' not found on disk."
        database.update_video_status(video_id, 'UPLOAD_FAILED', error_message=err_msg)
        print(f"⚠️ {err_msg}")
        return False

    database.update_video_status(video_id, 'UPLOADING')
    database.increment_upload_attempts(video_id)
    current_attempt = (video_record.get('upload_attempts') or 0) + 1
    
    import activity_tracker
    import metadata_generator
    import thumbnail_analyzer
    import analyzer
    import captions_generator
    import playlist_manager

    # Step 1: Ensure Video Metadata (Title, Description, Tags, Chapters) is generated with AI
    if not video_record.get('title') or not video_record.get('description') or video_record.get('title') == video_record.get('filename'):
        activity_tracker.update_video_progress(video_id, "VISION_AI", f"🤖 Generating AI Title, Description & Chapters...", 10)
        try:
            metadata_generator.generate_metadata(
                video_id, 
                file_path.name, 
                video_record.get('privacy') or 'unlisted', 
                user_context=video_record.get('user_context')
            )
            video_record = database.get_video_by_id(video_id)
        except Exception as e:
            print(f"⚠️ Metadata generation note: {e}")

    original_title = video_record.get('title') or file_path.name

    # Step 2: Ensure Local Preview & Best Thumbnail Exist
    best_thumb_path = Path(f"processing/thumbnails/{video_id}/best_thumb.jpg")
    if not best_thumb_path.exists():
        try:
            analyzer.analyze_video(video_id, str(file_path))
            thumbnail_analyzer.select_best_thumbnails(video_id)
        except Exception as e:
            print(f"⚠️ Thumbnail extraction note: {e}")

    # Step 3: Ensure Subtitles / Captions (.SRT) are generated from audio
    srt_path = Path(f"processing/captions/{video_id}.srt")
    if not srt_path.exists() and config.get_setting("transcription_enabled", True):
        activity_tracker.update_video_progress(video_id, "ANALYZING", f"🎙️ Generating Subtitles & Captions...", 20)
        try:
            captions_generator.generate_srt_captions(video_id, str(file_path))
        except Exception as e:
            print(f"⚠️ Subtitles note: {e}")

    activity_tracker.update_video_progress(video_id, "UPLOADING", f"🚀 Uploading '{original_title}' to YouTube (0%)...", 25)
    
    try:
        youtube_client = authenticate()
        response = upload_video(youtube_client, str(file_path), video_record)
        yt_id = response.get("id") if response else None
        yt_url = f"https://youtu.be/{yt_id}" if yt_id else None
        
        # 1. Custom Thumbnail Upload
        thumb_candidates = [
            Path(f"processing/custom_thumbnails/{video_id}.jpg"),
            Path(f"processing/thumbnails/{video_id}/best_thumb.jpg")
        ]
        for tc in thumb_candidates:
            if tc.exists() and yt_id:
                try:
                    from googleapiclient.http import MediaFileUpload
                    media_thumb = MediaFileUpload(str(tc), mimetype="image/jpeg", resumable=True)
                    youtube_client.thumbnails().set(videoId=yt_id, media_body=media_thumb).execute()
                    print(f"🎨 Custom thumbnail uploaded successfully for {yt_id}!")
                    break
                except Exception as e:
                    print(f"ℹ️ Custom thumbnail note (requires phone verification on channel): {e}")
                    break

        # 2. Captions / Subtitles Upload
        try:
            import captions_generator
            srt_path = Path(f"processing/captions/{video_id}.srt")
            if srt_path.exists() and yt_id:
                captions_generator.upload_captions_to_youtube(youtube_client, yt_id, str(srt_path))
        except Exception as e:
            print(f"ℹ️ Captions upload note: {e}")

        # 3. Smart Playlist Assignment
        try:
            import playlist_manager
            target_pl = video_record.get("playlist_id")
            if not target_pl and yt_id:
                playlists = playlist_manager.get_user_playlists(youtube_client)
                match = playlist_manager.auto_match_playlist(original_title, video_record.get("tags", "").split(","), playlists)
                if match:
                    target_pl = match["id"]
            if target_pl and yt_id:
                playlist_manager.add_video_to_playlist(youtube_client, target_pl, yt_id)
        except Exception as e:
            print(f"ℹ️ Playlist assignment note: {e}")

        # 4. Multilingual Localizations & Subtitle Upload (Spanish, Hindi, French, German, Japanese)
        try:
            import multilingual_manager
            localizations, translated_srts = multilingual_manager.generate_and_save_multilingual_assets(
                video_id, 
                original_title, 
                video_record.get('description') or ''
            )
            if localizations and yt_id:
                multilingual_manager.upload_localizations_to_youtube(youtube_client, yt_id, localizations)
            if translated_srts and yt_id:
                multilingual_manager.upload_multilingual_captions(youtube_client, yt_id, translated_srts)
        except Exception as e:
            print(f"ℹ️ Multilingual localization note: {e}")

        increment_quota()
        log_success(f"Successfully uploaded {original_title} (YouTube ID: {yt_id}).")
        database.update_video_status(video_id, 'UPLOADED', youtube_video_id=yt_id, youtube_url=yt_url)
        activity_tracker.update_video_progress(video_id, "UPLOADED", f"✅ Successfully uploaded '{original_title}' (100%)!", 100, active=False)
        
        return_dir = Path(os.path.expanduser(config.get_setting("return_directory", "~/Downloads")))
        return_dir.mkdir(parents=True, exist_ok=True)
        dest_path = return_dir / file_path.name
        if file_path != dest_path:
            if dest_path.exists():
                os.remove(dest_path)
            shutil.move(str(file_path), dest_path)
        database.update_video_status(video_id, 'UPLOADED', youtube_video_id=yt_id, youtube_url=yt_url)
        
        time.sleep(2.5)
        activity_tracker.clear_activity(video_id)
        return True
    except HttpError as e:
        err_msg = f"YouTube API Error {e.resp.status}: {str(e)}"
        log_error(err_msg)
        database.log_attempt(video_id, current_attempt, 'FAILED', error=err_msg)
        database.update_video_status(video_id, 'UPLOAD_FAILED', error_message=err_msg)
        activity_tracker.clear_activity(video_id)
        return False
    except Exception as e:
        err_msg = f"Unexpected error during upload of {original_title}: {str(e)}"
        log_error(err_msg)
        database.log_attempt(video_id, current_attempt, 'FAILED', error=err_msg)
        database.update_video_status(video_id, 'UPLOAD_FAILED', error_message=err_msg)
        activity_tracker.clear_activity(video_id)
        return False

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
