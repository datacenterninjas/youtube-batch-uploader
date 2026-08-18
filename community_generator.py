import os
import subprocess
import json
from pathlib import Path
from google import genai
from google.genai import types
import imageio_ffmpeg
import config

COMMUNITY_DIR = Path("processing/community")
COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)

def get_ffmpeg():
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def get_gemini_client():
    api_key = config.get_setting("gemini_api_key")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Google Gemini API key is missing.")
    return genai.Client(api_key=api_key)

def generate_teaser_gif(input_video_path, output_gif_path=None, start_sec=2, duration_sec=3):
    """
    Extracts a smooth, optimized 15fps animated preview GIF from the video using ffmpeg palettegen.
    """
    input_p = Path(input_video_path)
    if not output_gif_path:
        out_p = COMMUNITY_DIR / f"{input_p.stem}_teaser.gif"
    else:
        out_p = Path(output_gif_path)

    ffmpeg = get_ffmpeg()
    
    # Two-pass high-quality GIF generation filter
    filter_complex = (
        f"[0:v]fps=15,scale=480:-1:flags=lanczos,split[s0][s1];"
        f"[s0]palettegen=max_colors=128[p];"
        f"[s1][p]paletteuse=dither=bayer"
    )

    cmd = [
        ffmpeg, "-y",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", str(input_p),
        "-filter_complex", filter_complex,
        str(out_p)
    ]

    print(f"🖼️ Generating 3s animated teaser GIF for '{input_p.name}'...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"GIF generation failed: {res.stderr}")

    return str(out_p)

def generate_community_post_and_poll(title, description):
    """
    Generates a YouTube Community Tab post with an engaging text hook and an interactive 4-option poll.
    """
    client = get_gemini_client()
    prompt = f"""
    You are a YouTube Community Tab growth expert.
    Based on the following video title and description, write an engaging YouTube Community Tab Post with an Interactive Poll to hype up the video!

    Video Title: {title}
    Video Description: {description}

    Task:
    1. Write a short, punchy community post (with emojis, hook, and call to action).
    2. Write an interactive 4-option poll question related to the video highlights.
    3. Return valid JSON only in this exact structure:
    {{
        "community_post_text": "Short post text here...",
        "poll_question": "Poll question here...",
        "poll_options": ["Option 1", "Option 2", "Option 3", "Option 4"]
    }}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"⚠️ Community post generation note: {e}")
        return {
            "community_post_text": f"🔥 New video dropping! '{title}' - What are you most excited to see? Drop a comment below! 👇",
            "poll_question": "What kind of video should we film next?",
            "poll_options": ["More Travel & Vlogs ✈️", "Behind the Scenes 🎬", "Food & Places 🍔", "Q&A / Special Highlights ✨"]
        }

def create_community_package(video_id, input_video_path, title, description):
    """
    Generates teaser GIF and community tab post + poll, returning dict of assets.
    """
    gif_out = COMMUNITY_DIR / f"{video_id}_teaser.gif"
    try:
        generate_teaser_gif(input_video_path, str(gif_out))
        gif_url = f"/processing/community/{video_id}_teaser.gif"
    except Exception as e:
        print(f"⚠️ Teaser GIF note: {e}")
        gif_url = None

    post_data = generate_community_post_and_poll(title, description)
    return {
        "gif_url": gif_url,
        "community_post_text": post_data.get("community_post_text"),
        "poll_question": post_data.get("poll_question"),
        "poll_options": post_data.get("poll_options", [])
    }
