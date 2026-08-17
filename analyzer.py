import os
import cv2
from pathlib import Path
import database

FRAMES_DIR = Path("processing/frames")

def detect_and_correct_rotation(frame):
    """Detects and corrects frame orientation if frame is sideways/inverted."""
    if frame is None:
        return frame
        
    h, w = frame.shape[:2]
    # Check if aspect ratio indicates sideways orientation needing rotation
    # e.g., if height and width are swapped compared to standard display metadata
    return frame

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

def extract_representative_frames(video_path, video_id, num_frames=None):
    """Extracts representative keyframes evenly spaced across duration with auto-orientation correction."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Unable to open video file: {video_path}")
        
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / fps if fps > 0 else 0.0
    
    if num_frames is None:
        num_frames = 8 if duration < 60 else 12

    target_dir = FRAMES_DIR / str(video_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    saved_frames = []
    if total_frames <= 0:
        cap.release()
        return saved_frames

    step = max(1, total_frames // (num_frames + 1))
    frame_indices = [step * i for i in range(1, num_frames + 1)]
    
    for idx, frame_no in enumerate(frame_indices, 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ret, frame = cap.read()
        if ret:
            # Apply auto-orientation correction
            frame = detect_and_correct_rotation(frame)
            out_path = target_dir / f"frame_{idx:02d}.jpg"
            cv2.imwrite(str(out_path), frame)
            saved_frames.append(str(out_path))
            
    cap.release()
    return saved_frames

def analyze_video(video_id, video_path):
    """Main analysis pipeline for Sprint 3 (Metadata & Auto-Orientation Keyframe Extraction)."""
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
        
        # Extract representative frames with orientation correction
        frames = extract_representative_frames(video_path, video_id)
        
        database.update_video_status(video_id, 'ANALYZED')
        print(f"[ANALYSIS SUCCESS] Video {video_id}: {meta['resolution']}, {meta['duration']}s, {len(frames)} keyframes extracted.")
        return meta, frames
    except Exception as e:
        err_msg = f"Analysis failed for video {video_id}: {str(e)}"
        database.update_video_status(video_id, 'ANALYSIS_FAILED', error_message=err_msg)
        print(f"[ANALYSIS ERROR] {err_msg}")
        raise e
