import os
import sys
import shutil
import subprocess
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import psutil

import database
import config

app = FastAPI(title="YouTube Auto Publisher V2")

# Ensure processing directory exists and mount static route
os.makedirs("processing", exist_ok=True)
app.mount("/processing", StaticFiles(directory="processing"), name="processing")

templates = Jinja2Templates(directory="templates")

def is_uploader_running():
    lock_file = "youtube_uploader.lock"
    if not os.path.exists(lock_file):
        return False
    try:
        if os.name == 'nt':
            import msvcrt
            f = open(lock_file, 'r+')
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            f.close()
            return False  # Lock acquired -> uploader is NOT running
        else:
            import fcntl
            f = open(lock_file, 'r+')
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            f.close()
            return False  # Lock acquired -> uploader is NOT running
    except (IOError, OSError, PermissionError):
        return True  # Lock acquisition failed -> uploader IS running!
    except Exception:
        return False

@app.on_event("startup")
def startup_event():
    database.init_db()

def get_video_frames(video_id):
    """Returns list of web-accessible frame paths for a video."""
    frames_dir = Path(f"processing/frames/{video_id}")
    if not frames_dir.exists():
        return []
    return [f"/processing/frames/{video_id}/{f.name}" for f in sorted(frames_dir.glob("*.jpg"))]

def get_best_thumbnail(video_id):
    """Returns web path of best thumbnail if available."""
    thumb_path = Path(f"processing/thumbnails/{video_id}/best_thumbnail.jpg")
    if thumb_path.exists():
        return f"/processing/thumbnails/{video_id}/best_thumbnail.jpg"
    frames = get_video_frames(video_id)
    return frames[0] if frames else None

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    database.init_db()
    
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos ORDER BY id DESC")
        rows = cursor.fetchall()
        videos = [dict(r) for r in rows]
        
    for v in videos:
        v["thumbnail_url"] = get_best_thumbnail(v["id"])
        v["frames"] = get_video_frames(v["id"])
        
    quota_data = database.get_db_stats()
    cfg = config.load_config()
    
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "videos": videos,
            "uploader_running": is_uploader_running(),
            "quota_count": quota_data.get("UPLOADED", 0),
            "total_videos": len(videos),
            "approval_mode": cfg.get("approval_mode", "review")
        }
    )

@app.post("/api/uploader/restart")
def restart_uploader_engine():
    """Kills existing uploader processes and starts a fresh uploader engine."""
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline') or []
            if any('uploader.py' in arg for arg in cmd) and proc.pid != os.getpid():
                proc.kill()
        except Exception:
            pass

    # Give lock file a moment to release
    import time
    time.sleep(1)

    # Launch uploader engine in background
    subprocess.Popen([sys.executable, "-u", "uploader.py"])
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/approve")
def approve_video(video_id: int):
    database.update_video_status(video_id, "READY_TO_UPLOAD")
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/reject")
def reject_video(video_id: int):
    database.update_video_status(video_id, "REJECTED")
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/retry")
def retry_video(video_id: int):
    """Resets video status and restores video file to staging folder for re-processing."""
    video = database.get_video_by_id(video_id)
    if not video:
        return RedirectResponse(url="/", status_code=303)
        
    file_path = Path(video["file_path"])
    filename = video["filename"]
    privacy = (video.get("privacy") or "unlisted").title()
    if privacy not in ("Public", "Private", "Unlisted"):
        privacy = "Unlisted"
        
    staging_target = Path(f"videos_to_upload/{privacy}/{filename}")
    staging_target.parent.mkdir(parents=True, exist_ok=True)

    # If file was moved to archive/failed, move it back to staging folder
    if not file_path.exists():
        archive_path = Path(f"uploaded_archive/{filename}")
        failed_path = Path(f"failed_to_upload/{filename}")
        if archive_path.exists():
            shutil.move(str(archive_path), str(staging_target))
        elif failed_path.exists():
            shutil.move(str(failed_path), str(staging_target))

    # Reset video DB record to DISCOVERED so engine re-analyzes & re-generates AI metadata
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos 
            SET status = 'DISCOVERED', error_message = NULL, upload_attempts = 0, file_path = ?
            WHERE id = ?
        """, (str(staging_target), video_id))
        conn.commit()

    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/update")
def update_video_metadata(
    video_id: int,
    title: str = Form(...),
    description: str = Form(...),
    tags: str = Form(...),
    category: str = Form(...)
):
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos 
            SET title = ?, description = ?, tags = ?, category = ?
            WHERE id = ?
        """, (title[:95], description, tags, category, video_id))
        conn.commit()
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
