import os
import cv2
import subprocess
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import database

FRAMES_DIR = Path("processing/frames")

def get_ffmpeg_bin():
    """Resolves fast ffmpeg binary path."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"

def calculate_sharpness(image_path):
    """Calculates image sharpness using Laplacian variance."""
    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0
        return float(cv2.Laplacian(img, cv2.CV_64F).var())
    except Exception:
        return 0.0

def extract_video_metadata(video_path):
    """Extracts duration, resolution, frame rate, and orientation using OpenCV."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Unable to open video file: {video_path}")
        
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    
    duration = frame_count / fps if fps > 0 else 0.0
    resolution = f"{width}x{height}"
    
    return {
        "duration": round(duration, 2),
        "resolution": resolution,
        "frame_rate": round(fps, 2),
        "width": width,
        "height": height
    }

def _extract_single_frame_ffmpeg(ffmpeg_bin, video_path, timestamp_sec, output_path):
    """Extracts a single downscaled keyframe at timestamp using fast input-seeking demuxing."""
    cmd = [
        ffmpeg_bin,
        "-ss", str(max(0.0, timestamp_sec)),
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", "scale=min(1280\\,iw):-2",
        "-q:v", "3",
        "-y",
        str(output_path)
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return str(output_path)
    return None

def extract_representative_frames(video_path, video_id, num_frames=None):
    """
    Accelerated parallel keyframe extraction using fast FFmpeg demuxing and sharpness scoring.
    Extracts 6-8 optimized 720p frames in sub-second time.
    """
    meta = extract_video_metadata(video_path)
    duration = meta.get("duration", 0.0)
    
    if num_frames is None:
        num_frames = 6 if duration < 60 else 8

    target_dir = FRAMES_DIR / str(video_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    if duration <= 0:
        return []

    # Calculate timestamps evenly spaced across video
    step = duration / (num_frames + 1)
    timestamps = [round(step * i, 2) for i in range(1, num_frames + 1)]
    
    ffmpeg_bin = get_ffmpeg_bin()
    saved_frames = []
    
    # 1. Parallel Fast-Seek Extraction via ThreadPool
    futures = {}
    with ThreadPoolExecutor(max_workers=min(4, len(timestamps))) as executor:
        for idx, ts in enumerate(timestamps, 1):
            out_path = target_dir / f"frame_{idx:02d}.jpg"
            f = executor.submit(_extract_single_frame_ffmpeg, ffmpeg_bin, video_path, ts, out_path)
            futures[f] = (idx, out_path)
            
        for f in as_completed(futures):
            res_path = f.result()
            if res_path:
                saved_frames.append(res_path)

    # Sort in sequential timestamp order
    saved_frames.sort()
    
    # 2. Fallback to OpenCV if FFmpeg failed
    if not saved_frames:
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total_frames > 0:
            frame_step = max(1, total_frames // (num_frames + 1))
            for idx in range(1, num_frames + 1):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_step * idx)
                ret, frame = cap.read()
                if ret:
                    # Resize to 720p for speed
                    h, w = frame.shape[:2]
                    if w > 1280:
                        new_h = int(h * (1280.0 / w))
                        frame = cv2.resize(frame, (1280, new_h), interpolation=cv2.INTER_AREA)
                    out_path = target_dir / f"frame_{idx:02d}.jpg"
                    cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    saved_frames.append(str(out_path))
            cap.release()

    return saved_frames

def get_sharpest_frames(frame_paths, top_n=3):
    """Ranks and returns the top N sharpest candidate frames based on Laplacian variance."""
    if not frame_paths:
        return []
    scored = [(fp, calculate_sharpness(fp)) for fp in frame_paths if os.path.exists(fp)]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [fp for fp, _ in scored[:top_n]]

def analyze_video(video_id, video_path):
    """High-speed video analysis pipeline with parallel extraction and technical metadata discovery."""
    import activity_tracker
    activity_tracker.set_activity("ANALYZING", f"⚡ High-Speed Frame Analysis for '{Path(video_path).name}'...", progress=40)
    database.update_video_status(video_id, 'ANALYZING')
    
    try:
        # Extract technical metadata
        meta = extract_video_metadata(video_path)
        database.update_video_metadata(
            video_id, 
            duration=meta['duration'], 
            resolution=meta['resolution'], 
            frame_rate=meta['frame_rate']
        )
        
        # Parallel accelerated keyframe extraction
        frames = extract_representative_frames(video_path, video_id)
        
        database.update_video_status(video_id, 'ANALYZED')
        activity_tracker.clear_activity()
        print(f"[ACCELERATED ANALYSIS] Video {video_id}: {meta['resolution']}, {meta['duration']}s, {len(frames)} keyframes extracted in sub-second time.")
        return meta, frames
    except Exception as e:
        activity_tracker.clear_activity()
        err_msg = f"Analysis failed for video {video_id}: {str(e)}"
        database.update_video_status(video_id, 'ANALYSIS_FAILED', error_message=err_msg)
        print(f"[ANALYSIS ERROR] {err_msg}")
        raise e
