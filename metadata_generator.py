import os
import json
import re
from pathlib import Path
import database
import config
import activity_tracker
import analyzer

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

def generate_metadata_with_vision(video_id, frames, user_context=None):
    """Uses Gemini Vision AI + Creator Context to generate high-reach, SEO-optimized metadata from video keyframes."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or config.get_setting("gemini_api_key")
    if not api_key or api_key == "YOUR_API_KEY_HERE" or not GENAI_AVAILABLE or not frames:
        return None
        
    try:
        client = genai.Client(api_key=api_key)
        
        # Pick the top 3 sharpest, highest-contrast frames for minimal payload and max clarity
        best_frames = analyzer.get_sharpest_frames(frames, top_n=3)
        if not best_frames:
            best_frames = frames[:3]

        images = []
        for frame_path in best_frames:
            if os.path.exists(frame_path):
                images.append(Image.open(frame_path))
                
        if not images:
            return None

        prompt = (
            "You are a world-class YouTube Growth & SEO Strategist. "
            "Analyze these representative video keyframes and craft high-reach, viral-optimized metadata for a YouTube upload.\n\n"
            "🎯 GOALS FOR MAXIMUM ORGANIC REACH & DISCOVERY:\n"
            "1. TITLE OPTIMIZATION (60-85 characters):\n"
            "   - Must be high-CTR, click-worthy, and engaging (NOT boring generic labels).\n"
            "   - Fuse the core action/subject with location hints (landmarks, venues, mall names, city, nature spot, country).\n"
            "   - Structure: [Catchy Hook / Action] at [Specific Location or Setting] | [Search Keyword]\n"
            "   - Examples: 'Thrilling Space Robot Ride at M5 Mall E-City Play Zone! 🤖' or 'Incredible Nilgiri Langur Encounter in Forest | Wildlife Safari Vlog'\n\n"
            "2. DESCRIPTION OPTIMIZATION (Engaging & SEO-Rich with Timestamps):\n"
            "   - First 2 lines: Compelling search snippet hook describing the highlight.\n"
            "   - Location & Scene Details: Explicitly highlight the venue, city, region, landmarks, and atmosphere.\n"
            "   - Chapters / Timestamps: Include a clean YouTube chapters list (e.g., '00:00 - Highlight / Overview', '00:30 - Main Action', etc.).\n"
            "   - Creator Notes: Seamlessly blend any creator notes provided below.\n"
            "   - End with 4-6 high-traffic, relevant hashtags including location tags (e.g., #TravelDiaries #Bangalore #Wildlife #Vlog #Shorts).\n\n"
            "3. TAGS:\n"
            "   - Provide 10-15 targeted tags: specific subject, activity, location/city/region names, and broad category keywords.\n"
        )
        
        if user_context and user_context.strip():
            prompt += (
                f"\n📌 CREATOR'S CONTEXT & LOCATION NOTES:\n"
                f"\"{user_context.strip()}\"\n"
                f"Carefully incorporate this location and creator context into the title, description, and tags.\n"
            )

        prompt += (
            "\nRespond ONLY with valid JSON in this exact structure:\n"
            "{\n"
            '  "title": "High-CTR SEO Title with Location Hint (Max 90 chars)",\n'
            '  "description": "Engaging 2-paragraph description with location highlights, story breakdown, and hashtags",\n'
            '  "tags": ["tag1", "location_tag", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8"],\n'
            '  "category": "Best fitting YouTube Category (e.g. Travel & Events, Entertainment, People & Blogs, Gaming, Science & Technology)",\n'
            '  "summary": "1-sentence quick summary of the video content"\n'
            "}"
        )

        models_to_try = ['gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-flash-latest']
        response = None
        for m in models_to_try:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=[*images, prompt]
                )
                if response and response.text:
                    break
            except Exception as me:
                print(f"⚠️ Vision AI model {m} note: {me}")
                continue
        
        if not response or not response.text:
            return None

        text = response.text.strip()
        # Strip markdown ```json ``` wraps if present
        text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
        
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            data["confidence"] = 0.95
            return data
    except Exception as e:
        print(f"⚠️ Gemini Vision AI note: {e}")
    return None

def generate_metadata(video_id, filename, folder_name, duration=None, extracted_frames=None, user_context=None):
    """Generates structured metadata for YouTube publication (Vision AI + Creator Context + Fallback)."""
    clean_stem = Path(filename).stem
    fallback_title = clean_title(clean_stem)
    default_cat = config.get_setting("default_category", "Travel & Events")
    
    # Check if video has user_context stored in DB
    if user_context is None:
        video_rec = database.get_video_by_id(video_id)
        if video_rec and video_rec.get("user_context"):
            user_context = video_rec["user_context"]

    # Locate extracted frames if not passed
    if not extracted_frames:
        frames_dir = Path(f"processing/frames/{video_id}")
        if frames_dir.exists():
            extracted_frames = [str(f) for f in sorted(frames_dir.glob("*.jpg"))]

    # Attempt Vision AI generation first with user_context
    activity_tracker.set_activity("VISION_AI", f"🤖 Gemini 3.6 Flash: Generating structured metadata for '{clean_stem}'...", progress=65)
    ai_metadata = generate_metadata_with_vision(video_id, extracted_frames, user_context=user_context)
    
    if ai_metadata and ai_metadata.get("title"):
        title = clean_title(ai_metadata["title"])
        description = ai_metadata.get("description") or f"{title}\n\nUploaded via YouTube Auto Publisher V2."
        tags_list = ai_metadata.get("tags") or []
        category = ai_metadata.get("category") or default_cat
        confidence = ai_metadata.get("confidence", 0.95)
        ai_model = "gemini-3.6-flash-vision"
        print(f"✨ [VISION AI SUCCESS] Generated Title: '{title}'")
    else:
        title = fallback_title
        description = f"{title}\n\nUploaded via YouTube Auto Publisher V2.\nCategory: {default_cat}\nFolder Context: {folder_name.title()}"
        if user_context:
            description += f"\n\nCreator Notes: {user_context}"
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
        "confidence": confidence,
        "user_context": user_context
    }

    # Save into SQLite database
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos 
            SET title = ?, description = ?, tags = ?, category = ?, ai_confidence = ?, user_context = ?
            WHERE id = ?
        """, (title, description, tags_str, category, confidence, user_context, video_id))
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
    activity_tracker.clear_activity()
    return metadata_json
