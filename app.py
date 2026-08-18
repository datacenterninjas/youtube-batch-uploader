import os
import sys
import shutil
import datetime
import threading
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import database
import config
import engine_manager
import video_merger
import analyzer
import metadata_generator
import thumbnail_analyzer
import channel_manager
import activity_tracker
import uploader
import thumbnail_studio
import captions_generator
import playlist_manager

app = FastAPI(title="YouTube Auto Publisher V2")

# Ensure processing and static directories exist and mount routes
os.makedirs("processing", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/processing", StaticFiles(directory="processing"), name="processing")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

def is_uploader_running():
    if engine_manager.is_running():
        return True
    lock_file = "youtube_uploader.lock"
    if not os.path.exists(lock_file):
        return False
    try:
        if os.name == 'nt':
            import msvcrt
            f = open(lock_file, 'r+')
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            f.close()
            return False
        else:
            import fcntl
            f = open(lock_file, 'r+')
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            f.close()
            return False
    except (IOError, OSError, PermissionError):
        return True
    except Exception:
        return False

@app.on_event("startup")
def startup_event():
    database.init_db()
    engine_manager.start_engine()

def get_video_frames(video_id):
    """Returns list of web-accessible frame paths for a video."""
    frames_dir = Path(f"processing/frames/{video_id}")
    if not frames_dir.exists():
        return []
    return [f"/processing/frames/{video_id}/{f.name}" for f in sorted(frames_dir.glob("*.jpg"))]

def get_best_thumbnail(video_id):
    """Returns web path of best thumbnail if available (local frame without AI)."""
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
        
    stats = database.get_db_stats()
    cfg = config.load_config()
    
    awaiting_count = sum(stats.get(s, 0) for s in ["AWAITING_APPROVAL", "ANALYZED", "METADATA_READY", "DISCOVERED"])
    ready_count = stats.get("READY_TO_UPLOAD", 0)
    uploading_count = stats.get("UPLOADING", 0)
    uploaded_count = stats.get("UPLOADED", 0) + stats.get("ARCHIVED", 0)
    failed_count = stats.get("UPLOAD_FAILED", 0)
    rejected_count = stats.get("REJECTED", 0) + stats.get("DUPLICATE", 0)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "videos": videos,
            "uploader_running": is_uploader_running(),
            "quota_count": stats.get("UPLOADED", 0),
            "total_videos": len(videos),
            "approval_mode": cfg.get("approval_mode", "review"),
            "awaiting_count": awaiting_count,
            "ready_count": ready_count,
            "uploading_count": uploading_count,
            "uploaded_count": uploaded_count,
            "failed_count": failed_count,
            "rejected_count": rejected_count
        }
    )

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: bool = False):
    cfg = config.load_config()
    ch_profile = channel_manager.get_channel_profile()
    
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "config": cfg,
            "channel": ch_profile,
            "saved": saved
        }
    )

@app.post("/api/settings/save")
def save_settings(
    approval_mode: str = Form("review"),
    default_privacy: str = Form("unlisted"),
    daily_upload_limit: int = Form(6),
    return_directory: str = Form("~/Downloads"),
    default_category: str = Form("Travel & Events"),
    gemini_api_key: str = Form(""),
    ai_enabled: bool = Form(False),
    thumbnail_analysis_enabled: bool = Form(False)
):
    updates = {
        "approval_mode": approval_mode,
        "default_privacy": default_privacy,
        "daily_upload_limit": daily_upload_limit,
        "return_directory": return_directory,
        "default_category": default_category,
        "gemini_api_key": gemini_api_key.strip(),
        "ai_enabled": ai_enabled,
        "thumbnail_analysis_enabled": thumbnail_analysis_enabled
    }
    config.save_config(updates)
    engine_manager.restart_engine()
    return RedirectResponse(url="/settings?saved=true", status_code=303)

@app.post("/api/channel/switch")
def switch_channel():
    """Switches active YouTube channel via browser OAuth flow."""
    try:
        channel_manager.switch_youtube_channel()
        engine_manager.restart_engine()
    except Exception as e:
        print(f"⚠️ Channel switch error: {e}")
    return RedirectResponse(url="/settings?saved=true", status_code=303)

@app.get("/api/engine/activity")
def get_engine_activity():
    """Returns current active system task and progress."""
    return JSONResponse(activity_tracker.get_activity())

@app.get("/api/videos/merge/progress")
def get_merge_progress():
    """Returns real-time merge status & progress percentage."""
    return JSONResponse(video_merger.get_merge_progress())

@app.post("/api/videos/upload")
async def upload_video_files(
    files: list[UploadFile] = File(...),
    user_context: str = Form(None)
):
    """Stages uploaded video files, extracts keyframes, and automatically generates AI metadata for review-once."""
    target_dir = Path("videos_to_upload/Unlisted")
    target_dir.mkdir(parents=True, exist_ok=True)
    
    for file in files:
        if not file.filename:
            continue
        save_path = target_dir / file.filename
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        v_record, _ = database.register_video(save_path, "unlisted")
        v_id = v_record['id']
        
        if user_context:
            with database.get_connection() as conn:
                conn.cursor().execute("UPDATE videos SET user_context = ? WHERE id = ?", (user_context, v_id))
                conn.commit()

        # 1. Instant local OpenCV thumbnail & keyframe extraction
        try:
            analyzer.analyze_video(v_id, str(save_path))
            thumbnail_analyzer.select_best_thumbnails(v_id)
        except Exception as e:
            print(f"⚠️ Local thumbnail note for video #{v_id}: {e}")

        # 2. Auto-Pilot: Automatically generate Vision AI metadata (Titles, Location Description, Chapters, Tags)
        try:
            metadata_generator.generate_metadata(v_id, file.filename, "unlisted", user_context=user_context)
            approval_mode = config.get_setting("approval_mode", "review").lower()
            if approval_mode == "auto":
                database.update_video_status(v_id, "READY_TO_UPLOAD")
                threading.Thread(target=uploader.process_single_video_upload, args=(v_id,), daemon=True).start()
            else:
                database.update_video_status(v_id, "AWAITING_APPROVAL")
        except Exception as e:
            print(f"⚠️ Auto-Pilot metadata generation note: {e}")

    engine_manager.wake_engine()
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/approve_all")
def approve_all_pending_videos():
    """Batch approves all pending videos and launches background hands-off upload workers."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM videos WHERE status IN ('AWAITING_APPROVAL', 'ANALYZED', 'METADATA_READY', 'DISCOVERED', 'STABILIZING')")
        rows = cursor.fetchall()
        
    for r in rows:
        vid = r["id"]
        approve_video(vid)
        threading.Thread(target=uploader.process_single_video_upload, args=(vid,), daemon=True).start()
        
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/merge")
def merge_selected_videos(
    video_ids: list[int] = Form(...),
    user_context: str = Form(None)
):
    """Merges selected video records into a single video clip and stages it for AI context."""
    if len(video_ids) < 2:
        return RedirectResponse(url="/", status_code=303)

    paths_to_merge = []
    for vid in video_ids:
        v = database.get_video_by_id(vid)
        if v and os.path.exists(v['file_path']):
            paths_to_merge.append(v['file_path'])

    if len(paths_to_merge) >= 2:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_dir = Path("videos_to_upload/Unlisted")
        target_dir.mkdir(parents=True, exist_ok=True)
        merged_output_path = target_dir / f"merged_{ts}.mp4"
        
        # Merge videos with live progress
        video_merger.merge_videos(paths_to_merge, str(merged_output_path))
        
        # Register new merged video in DB
        v_record, _ = database.register_video(merged_output_path, "unlisted")
        v_id = v_record['id']
        
        if user_context:
            with database.get_connection() as conn:
                conn.cursor().execute("UPDATE videos SET user_context = ? WHERE id = ?", (user_context, v_id))
                conn.commit()

        # Extract local preview thumbnail for merged video immediately
        try:
            analyzer.analyze_video(v_id, str(merged_output_path))
            thumbnail_analyzer.select_best_thumbnails(v_id)
        except Exception as e:
            print(f"⚠️ Thumbnail note for merged video #{v_id}: {e}")

        # Automatically discard and cleanup individual source videos once merged
        for source_vid in video_ids:
            try:
                remove_video_files_and_cache(int(source_vid))
            except Exception as e:
                print(f"⚠️ Note cleaning up source video #{source_vid}: {e}")
                
        engine_manager.wake_engine()

    return RedirectResponse(url="/", status_code=303)

@app.get("/api/videos/{video_id}/thumbnail_candidates")
def get_video_thumbnail_candidates(video_id: int):
    """Returns candidate keyframe images for Thumbnail Studio."""
    candidates = thumbnail_studio.get_thumbnail_candidates(video_id)
    return JSONResponse({"candidates": candidates})

@app.post("/api/videos/{video_id}/apply_thumbnail_overlay")
def apply_custom_thumbnail_overlay(
    video_id: int,
    base_image: str = Form(...),
    top_text: str = Form(""),
    bottom_text: str = Form(""),
    theme: str = Form("yellow_bold")
):
    """Renders custom viral text overlay on selected keyframe thumbnail."""
    thumb_url = thumbnail_studio.apply_thumbnail_overlay(video_id, base_image, top_text, bottom_text, theme)
    return JSONResponse({"success": bool(thumb_url), "thumbnail_url": thumb_url})

@app.post("/api/videos/{video_id}/convert_to_shorts")
def convert_video_to_shorts(video_id: int):
    """Converts a video to 1080x1920 9:16 Shorts format with Apple Silicon M4 GPU acceleration."""
    video = database.get_video_by_id(video_id)
    if not video or not os.path.exists(video["file_path"]):
        return JSONResponse({"success": False, "error": "Video file not found"}, status_code=404)
    
    input_path = video["file_path"]
    p = Path(input_path)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = Path("videos_to_upload/Unlisted")
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"shorts_{ts}_{p.stem}.mp4"

    video_merger.convert_to_shorts_9_16(input_path, str(output_path))
    
    v_record, _ = database.register_video(output_path, video.get("privacy") or "unlisted")
    new_vid = v_record["id"]
    
    ctx = f"{video.get('user_context') or ''} #Shorts 9:16 vertical format".strip()
    with database.get_connection() as conn:
        conn.cursor().execute("UPDATE videos SET user_context = ? WHERE id = ?", (ctx, new_vid))
        conn.commit()

    try:
        analyzer.analyze_video(new_vid, str(output_path))
        thumbnail_analyzer.select_best_thumbnails(new_vid)
    except Exception:
        pass

    engine_manager.wake_engine()
    return JSONResponse({"success": True, "new_video_id": new_vid})

@app.get("/api/youtube/playlists")
def list_youtube_playlists():
    """Fetches user YouTube playlists for auto-organization."""
    try:
        yt = uploader.authenticate()
        playlists = playlist_manager.get_user_playlists(yt)
        return JSONResponse({"playlists": playlists})
    except Exception as e:
        return JSONResponse({"playlists": [], "error": str(e)})

@app.post("/api/videos/{video_id}/generate_captions")
def generate_captions(video_id: int):
    """Generates timestamped .srt subtitles from audio track using Gemini speech recognition."""
    video = database.get_video_by_id(video_id)
    if not video or not os.path.exists(video["file_path"]):
        return JSONResponse({"success": False, "error": "Video file not found"}, status_code=404)
    srt_file = captions_generator.generate_srt_captions(video_id, video["file_path"])
    return JSONResponse({"success": bool(srt_file), "srt_file": srt_file})

@app.post("/api/videos/{video_id}/regenerate_ai")
def regenerate_ai_metadata(
    video_id: int,
    request: Request,
    user_context: str = Form(None)
):
    """Runs Gemini Vision AI metadata generation incorporating creator context notes."""
    video = database.get_video_by_id(video_id)
    metadata = {}
    if video:
        with database.get_connection() as conn:
            conn.cursor().execute("UPDATE videos SET user_context = ? WHERE id = ?", (user_context, video_id))
            conn.commit()
            
        metadata = metadata_generator.generate_metadata(
            video_id, 
            video['filename'], 
            video.get('privacy') or 'unlisted',
            user_context=user_context
        )
        database.update_video_status(video_id, 'AWAITING_APPROVAL')

    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header or request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JSONResponse({"success": True, "metadata": metadata, "video_id": video_id})
        
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/uploader/restart")
def restart_uploader_engine():
    """Restarts the background uploader engine cleanly."""
    engine_manager.restart_engine()
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/approve")
def approve_video(video_id: int):
    video = database.get_video_by_id(video_id)
    if video:
        filename = video["filename"]
        privacy = (video.get("privacy") or "unlisted").title()
        if privacy not in ("Public", "Private", "Unlisted"):
            privacy = "Unlisted"
        staging_target = Path(f"videos_to_upload/{privacy}/{filename}")
        staging_target.parent.mkdir(parents=True, exist_ok=True)

        return_dir = Path(os.path.expanduser(config.get_setting("return_directory", "~/Downloads")))
        candidates = [
            staging_target,
            return_dir / filename,
            Path("uploaded_archive") / filename,
            Path("failed_to_upload") / filename
        ]
        for c in candidates:
            if c.exists() and c != staging_target:
                shutil.copy2(str(c), str(staging_target))
                break
                
        database.update_video_status(video_id, "READY_TO_UPLOAD")
    engine_manager.wake_engine()
    return RedirectResponse(url="/", status_code=303)

def remove_video_files_and_cache(video_id: int):
    """Helper to remove video file from staging and clean up generated frame/thumbnail caches."""
    video = database.get_video_by_id(video_id)
    if video:
        if video.get("file_path"):
            p = Path(video["file_path"])
            if p.exists():
                try:
                    os.remove(p)
                except OSError:
                    pass
        shutil.rmtree(f"processing/frames/{video_id}", ignore_errors=True)
        shutil.rmtree(f"processing/thumbnails/{video_id}", ignore_errors=True)
        database.delete_video(video_id)

@app.post("/api/videos/{video_id}/discard")
def discard_video(video_id: int):
    """Completely discards a video from queue and deletes local staging & caches."""
    remove_video_files_and_cache(video_id)
    engine_manager.wake_engine()
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/discard_batch")
def discard_batch_videos(video_ids: list[int] = Form(...)):
    """Discards multiple selected videos in batch."""
    for vid in video_ids:
        remove_video_files_and_cache(vid)
    engine_manager.wake_engine()
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/reject")
def reject_video(video_id: int):
    """Marks video as REJECTED and returns video file to ~/Downloads."""
    database.update_video_status(video_id, "REJECTED")
    video = database.get_video_by_id(video_id)
    if video:
        file_path = Path(video["file_path"])
        if file_path.exists():
            return_dir = Path(os.path.expanduser(config.get_setting("return_directory", "~/Downloads")))
            return_dir.mkdir(parents=True, exist_ok=True)
            target_path = return_dir / file_path.name
            if file_path != target_path:
                if target_path.exists():
                    os.remove(target_path)
                shutil.move(str(file_path), str(target_path))
    engine_manager.wake_engine()
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/retry")
def retry_video(video_id: int):
    """Resets video status and restores video file to staging folder for re-processing."""
    video = database.get_video_by_id(video_id)
    if not video:
        return RedirectResponse(url="/", status_code=303)
        
    filename = video["filename"]
    privacy = (video.get("privacy") or "unlisted").title()
    if privacy not in ("Public", "Private", "Unlisted"):
        privacy = "Unlisted"
        
    staging_target = Path(f"videos_to_upload/{privacy}/{filename}")
    staging_target.parent.mkdir(parents=True, exist_ok=True)

    return_dir = Path(os.path.expanduser(config.get_setting("return_directory", "~/Downloads")))
    download_file = return_dir / filename
    archive_path = Path(f"uploaded_archive/{filename}")
    failed_path = Path(f"failed_to_upload/{filename}")

    if download_file.exists():
        shutil.move(str(download_file), str(staging_target))
    elif archive_path.exists():
        shutil.move(str(archive_path), str(staging_target))
    elif failed_path.exists():
        shutil.move(str(failed_path), str(staging_target))

    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos 
            SET status = 'DISCOVERED', error_message = NULL, upload_attempts = 0, file_path = ?
            WHERE id = ?
        """, (str(staging_target), video_id))
        conn.commit()

    engine_manager.wake_engine()
    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/reupload")
def reupload_video(video_id: int):
    """Initiates immediate direct YouTube upload in background thread."""
    video = database.get_video_by_id(video_id)
    if not video:
        return RedirectResponse(url="/", status_code=303)
        
    filename = video["filename"]
    original_title = video.get("title") or filename
    privacy = (video.get("privacy") or "unlisted").title()
    if privacy not in ("Public", "Private", "Unlisted"):
        privacy = "Unlisted"
        
    staging_target = Path(f"videos_to_upload/{privacy}/{filename}")
    staging_target.parent.mkdir(parents=True, exist_ok=True)

    return_dir = Path(os.path.expanduser(config.get_setting("return_directory", "~/Downloads")))
    download_file = return_dir / filename
    archive_path = Path(f"uploaded_archive/{filename}")
    failed_path = Path(f"failed_to_upload/{filename}")

    if download_file.exists():
        shutil.copy2(str(download_file), str(staging_target))
    elif archive_path.exists():
        shutil.copy2(str(archive_path), str(staging_target))
    elif failed_path.exists():
        shutil.copy2(str(failed_path), str(staging_target))

    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos 
            SET status = 'UPLOADING', error_message = NULL, file_path = ?
            WHERE id = ?
        """, (str(staging_target), video_id))
        conn.commit()

    activity_tracker.update_video_progress(video_id, "UPLOADING", f"🚀 Uploading '{original_title}' to YouTube (0%)...", 5)

    # Launch immediate upload worker thread
    threading.Thread(target=uploader.process_single_video_upload, args=(video_id,), daemon=True).start()

    return RedirectResponse(url="/", status_code=303)

@app.post("/api/videos/{video_id}/update")
def update_video_metadata(
    video_id: int,
    title: str = Form(...),
    description: str = Form(...),
    tags: str = Form(...),
    category: str = Form(...),
    privacy: str = Form("unlisted"),
    user_context: str = Form(None)
):
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos 
            SET title = ?, description = ?, tags = ?, category = ?, privacy = ?, user_context = ?
            WHERE id = ?
        """, (title[:95], description, tags, category, privacy.lower(), user_context, video_id))
        conn.commit()
    engine_manager.wake_engine()
    return RedirectResponse(url="/", status_code=303)

@app.get("/api/audio/tracks")
def list_audio_tracks():
    """Returns available royalty-free stock music tracks."""
    import audio_enhancer
    return JSONResponse({"tracks": audio_enhancer.get_available_tracks()})

@app.post("/api/videos/{video_id}/enhance_audio")
def enhance_video_audio(video_id: int):
    """Cleans up voice audio, removes background noise, and normalizes broadcast loudness."""
    import audio_enhancer
    video = database.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    src_path = Path(video["file_path"])
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found")
        
    try:
        temp_out = src_path.parent / f"temp_enh_{src_path.name}"
        audio_enhancer.enhance_speech_and_denoise(str(src_path), str(temp_out))
        # Replace source file
        shutil.move(str(temp_out), str(src_path))
        
        # Re-extract clean audio subtitles if needed
        try:
            import captions_generator
            captions_generator.generate_srt_captions(video_id, str(src_path))
        except Exception:
            pass
            
        return JSONResponse({"success": True, "message": "Audio enhanced and normalized to YouTube broadcast standard!"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/api/videos/{video_id}/mix_music")
def mix_video_music(
    video_id: int,
    music_track: str = Form(...),
    music_volume: float = Form(0.20),
    auto_ducking: bool = Form(True)
):
    """Mixes royalty-free background music into the video with auto-ducking during speech."""
    import audio_enhancer
    video = database.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    src_path = Path(video["file_path"])
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found")
        
    try:
        temp_out = src_path.parent / f"temp_music_{src_path.name}"
        audio_enhancer.mix_background_music(
            str(src_path),
            music_track,
            str(temp_out),
            music_volume=music_volume,
            auto_ducking=auto_ducking
        )
        # Replace source file
        shutil.move(str(temp_out), str(src_path))
        return JSONResponse({"success": True, "message": f"Successfully mixed background music '{music_track}'!"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/api/videos/{video_id}/generate_multilingual")
def generate_video_multilingual(video_id: int):
    """Translates title, description, and subtitles into Spanish, Hindi, French, German, and Japanese."""
    import multilingual_manager
    video = database.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    title = video.get("title") or video.get("filename")
    description = video.get("description") or ""
    
    try:
        localizations, translated_srts = multilingual_manager.generate_and_save_multilingual_assets(
            video_id, title, description
        )
        return JSONResponse({
            "success": True, 
            "message": f"Translated into {len(localizations)} languages (Spanish, Hindi, French, German, Japanese)!",
            "languages": list(localizations.keys())
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/api/videos/{video_id}/add_endscreen")
def add_video_endscreen(video_id: int):
    """Appends a 5-second cinematic End Screen Outro bumper using Apple Silicon M4 GPU acceleration."""
    import endscreen_manager
    video = database.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    src_path = Path(video["file_path"])
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found")
        
    try:
        temp_out = src_path.parent / f"temp_endscreen_{src_path.name}"
        endscreen_manager.append_endscreen_outro(str(src_path), str(temp_out))
        # Replace source file
        shutil.move(str(temp_out), str(src_path))
        return JSONResponse({"success": True, "message": "5-second End Screen outro bumper added successfully!"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/api/videos/{video_id}/burn_kinetic_captions")
def burn_video_kinetic_captions(video_id: int):
    """Generates and burns bold kinetic word-by-word subtitles directly into the video."""
    import kinetic_captions
    video = database.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    src_path = Path(video["file_path"])
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found")
        
    try:
        temp_out = src_path.parent / f"temp_kinetic_{src_path.name}"
        kinetic_captions.burn_kinetic_captions(video_id, str(src_path), str(temp_out))
        shutil.move(str(temp_out), str(src_path))
        return JSONResponse({"success": True, "message": "Kinetic subtitles burned into video with M4 GPU acceleration!"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.get("/api/color_grading/presets")
def list_color_grading_presets():
    """Returns list of cinematic color grading LUT presets."""
    import color_grading
    return JSONResponse({"presets": color_grading.get_available_presets()})

@app.post("/api/videos/{video_id}/apply_color_grade")
def apply_video_color_grade(video_id: int, preset: str = Form("golden_hour")):
    """Applies professional cinematic color grading LUT filter to the video."""
    import color_grading
    video = database.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    src_path = Path(video["file_path"])
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found")
        
    try:
        temp_out = src_path.parent / f"temp_graded_{src_path.name}"
        color_grading.apply_color_grading(str(src_path), preset_id=preset, output_video_path=str(temp_out))
        shutil.move(str(temp_out), str(src_path))
        return JSONResponse({"success": True, "message": f"Applied '{preset}' cinematic color grading successfully!"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/api/videos/{video_id}/spy_keywords")
def spy_video_keywords(video_id: int, custom_query: str = Form(None)):
    """Searches YouTube competitor videos, extracts top ranking tags, and generates AI keyword strategy."""
    import keyword_spy
    video = database.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    query = custom_query or video.get("title") or video.get("category") or "travel vlogs"
    try:
        data = keyword_spy.spy_competitor_keywords(query)
        return JSONResponse({"success": True, "data": data})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.post("/api/videos/{video_id}/generate_community")
def generate_video_community_post(video_id: int):
    """Generates a 3-second animated teaser GIF and YouTube Community Tab post with interactive poll."""
    import community_generator
    video = database.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    src_path = Path(video["file_path"])
    title = video.get("title") or video.get("filename")
    description = video.get("description") or ""
    
    try:
        community_data = community_generator.create_community_package(
            video_id, str(src_path), title, description
        )
        return JSONResponse({"success": True, "data": community_data})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
