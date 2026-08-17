import os
import json
import re
from pathlib import Path
import database
import config

try:
    from PIL import Image
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

def clean_title(raw_title):
    """Sanitizes and formats a clean YouTube title."""
    t = raw_title.replace("_", " ").replace("-", " ")
    t = re.sub(r'[<>"\']', '', t)
    t = " ".join(word.capitalize() for word in t.split())
    return t[:95]

def generate_metadata_with_vision(video_id, frames):
    """Uses Gemini Vision AI to generate metadata from video keyframes."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or config.get_setting("gemini_api_key")
    if not api_key or api_key == "YOUR_API_KEY_HERE" or not GENAI_AVAILABLE or not frames:
        return None
        
    try:
        client = genai.Client(api_key=api_key)
        
        # Load up to 3 keyframe images
        images = []
        for frame_path in frames[:3]:
            if os.path.exists(frame_path):
                images.append(Image.open(frame_path))
                
        if not images:
            return None

        prompt = (
            "Analyze these representative video keyframes and generate structured JSON metadata for a YouTube upload.\n"
            "Format MUST be strict JSON with keys:\n"
            "{\n"
            '  "title": "Engaging descriptive title max 90 characters",\n'
            '  "description": "Natural detailed summary of what is happening in the video",\n'
            '  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],\n'
            '  "category": "Recommended YouTube category (e.g. Travel & Events, Gaming, People & Blogs, Tech, Entertainment)",\n'
            '  "summary": "Short 1-sentence overview of video content"\n'
            "}"
        )

        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=[*images, prompt]
        )
        
        text = response.text or ""
        # Extract JSON block
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            data["confidence"] = 0.95
            return data
    except Exception as e:
        print(f"⚠️ Gemini Vision AI note: {e}")
    return None

def generate_metadata(video_id, filename, folder_name, duration=None, extracted_frames=None):
    """Generates structured metadata for YouTube publication (Vision AI + Heuristic Fallback)."""
    clean_stem = Path(filename).stem
    fallback_title = clean_title(clean_stem)
    default_cat = config.get_setting("default_category", "Travel & Events")
    
    # Locate extracted frames if not passed
    if not extracted_frames:
        frames_dir = Path(f"processing/frames/{video_id}")
        if frames_dir.exists():
            extracted_frames = [str(f) for f in sorted(frames_dir.glob("*.jpg"))]

    # Attempt Vision AI generation first
    ai_metadata = generate_metadata_with_vision(video_id, extracted_frames)
    
    if ai_metadata and ai_metadata.get("title"):
        title = clean_title(ai_metadata["title"])
        description = ai_metadata.get("description") or f"{title}\n\nUploaded via YouTube Auto Publisher V2."
        tags_list = ai_metadata.get("tags") or []
        category = ai_metadata.get("category") or default_cat
        confidence = ai_metadata.get("confidence", 0.95)
        ai_model = "gemini-2.5-flash-vision"
        print(f"✨ [VISION AI SUCCESS] Generated Title: '{title}'")
    else:
        title = fallback_title
        description = f"{title}\n\nUploaded via YouTube Auto Publisher V2.\nCategory: {default_cat}\nFolder Context: {folder_name.title()}"
        words = [w.lower() for w in re.findall(r'\w+', clean_stem) if len(w) > 2]
        tags_list = list(dict.fromkeys(words + ["video", folder_name.lower(), "vlog"]))[:12]
        category = default_cat
        confidence = 0.70
        ai_model = "heuristic-v1"
        print(f"ℹ️ [HEURISTIC METADATA] Generated Title: '{title}'")

    tags_str = ",".join(tags_list)

    metadata_json = {
        "title": title,
        "description": description,
        "tags": tags_list,
        "category": category,
        "summary": description[:200],
        "confidence": confidence
    }

    # Save into SQLite database
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos 
            SET title = ?, description = ?, tags = ?, category = ?, ai_confidence = ?
            WHERE id = ?
        """, (title, description, tags_str, category, confidence, video_id))
        conn.commit()

    # Log to analysis table
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO analysis (video_id, analysis_type, result, model, confidence)
            VALUES (?, 'METADATA', ?, ?, ?)
        """, (video_id, json.dumps(metadata_json), ai_model, confidence))
        conn.commit()

    database.update_video_status(video_id, 'METADATA_READY')
    return metadata_json
