import cv2
import os
import json
from pathlib import Path
import database

THUMBNAILS_DIR = Path("processing/thumbnails")

def score_frame(frame_path):
    """Scores a frame for sharpness, contrast, and brightness."""
    img = cv2.imread(str(frame_path))
    if img is None:
        return 0.0
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Sharpness: Laplacian variance
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
    
    # Contrast: Standard deviation of pixel intensities
    contrast = gray.std()
    
    # Brightness penalty (avoid too dark or overexposed)
    brightness = gray.mean()
    brightness_score = 100 - abs(brightness - 128)
    
    # Combined score
    score = (sharpness * 0.5) + (contrast * 0.3) + (brightness_score * 0.2)
    return round(score, 2)

def select_best_thumbnails(video_id, frames_dir=None):
    """Scores all extracted frames and selects top candidates."""
    if frames_dir is None:
        frames_dir = Path(f"processing/frames/{video_id}")
        
    if not frames_dir.exists():
        print(f"Warning: Frames directory {frames_dir} does not exist.")
        return []
        
    frame_files = list(frames_dir.glob("*.jpg"))
    if not frame_files:
        return []
        
    scored = []
    for f in frame_files:
        s = score_frame(f)
        scored.append({"path": str(f), "filename": f.name, "score": s})
        
    # Sort descending by score
    scored.sort(key=lambda x: x["score"], reverse=True)
    
    # Copy best candidate to thumbnails directory
    target_dir = THUMBNAILS_DIR / str(video_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    best_candidate = scored[0]
    best_img = cv2.imread(best_candidate["path"])
    if best_img is not None:
        out_file = target_dir / "best_thumbnail.jpg"
        cv2.imwrite(str(out_file), best_img)
        best_candidate["best_path"] = str(out_file)

    # Store analysis result in SQLite DB
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO analysis (video_id, analysis_type, result, model, confidence)
            VALUES (?, 'THUMBNAIL_SCORING', ?, 'opencv-laplacian-v1', ?)
        """, (video_id, json.dumps(scored), scored[0]["score"] if scored else 0.0))
        conn.commit()

    print(f"[THUMBNAIL SELECTION] Video {video_id}: Selected '{scored[0]['filename']}' (Score: {scored[0]['score']})")
    return scored
