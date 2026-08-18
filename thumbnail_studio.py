import os
import cv2
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import database

CUSTOM_THUMBNAILS_DIR = Path("processing/custom_thumbnails")
FRAMES_DIR = Path("processing/frames")
THUMBNAILS_DIR = Path("processing/thumbnails")

def get_thumbnail_candidates(video_id: int):
    """Returns list of candidate keyframe image paths available for a video."""
    video_frames_dir = FRAMES_DIR / str(video_id)
    if not video_frames_dir.exists():
        return []
        
    frames = sorted(list(video_frames_dir.glob("*.jpg")))
    return [f"/static/frames/{video_id}/{f.name}" for f in frames]

def apply_thumbnail_overlay(video_id: int, base_image_rel_path: str, top_text: str = "", bottom_text: str = "", theme: str = "yellow_bold"):
    """
    Renders high-CTR viral text banner overlays on the selected video keyframe.
    Themes:
      - 'yellow_bold': Vivid yellow text with black stroke border
      - 'neon_cyan': Glowing cyan text with dark drop shadow
      - 'red_fire': Vibrant red/white alert banner
    """
    CUSTOM_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Resolve absolute path of base frame
    clean_path = base_image_rel_path.replace("/static/frames/", "processing/frames/").replace("/static/thumbnails/", "processing/thumbnails/")
    base_file = Path(clean_path)
    if not base_file.exists():
        # Fallback to looking in frames dir
        candidates = list((FRAMES_DIR / str(video_id)).glob("*.jpg"))
        if candidates:
            base_file = candidates[0]
        else:
            return None

    img = Image.open(base_file).convert("RGB")
    # Resize to standard YouTube thumbnail resolution (1280x720)
    img = img.resize((1280, 720), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(img)

    # Color palettes
    if theme == "neon_cyan":
        text_color = "#38bdf8"
        stroke_color = "#030712"
        banner_bg = (3, 7, 18, 180)
    elif theme == "red_fire":
        text_color = "#fef08a"
        stroke_color = "#7f1d1d"
        banner_bg = (185, 28, 28, 200)
    else: # yellow_bold default
        text_color = "#facc15"
        stroke_color = "#000000"
        banner_bg = (0, 0, 0, 180)

    # Try system fonts, fallback to default
    font_path = "/System/Library/Fonts/HelveticaNeue.ttc"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/Supplemental/Impact.ttf"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

    font_size = 54
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    def draw_banner_text(text, y_pos):
        if not text or not text.strip():
            return
        text = text.strip().upper()
        # Measure text
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (1280 - w) // 2

        # Draw semi-transparent background pill
        pad_x = 24
        pad_y = 12
        draw.rectangle(
            [x - pad_x, y_pos - pad_y, x + w + pad_x, y_pos + h + pad_y],
            fill=banner_bg
        )

        # Draw text with thick contrast border
        draw.text(
            (x, y_pos),
            text,
            font=font,
            fill=text_color,
            stroke_width=5,
            stroke_fill=stroke_color
        )

    if top_text:
        draw_banner_text(top_text, y_pos=35)
    if bottom_text:
        draw_banner_text(bottom_text, y_pos=590)

    output_path = CUSTOM_THUMBNAILS_DIR / f"{video_id}.jpg"
    img.save(output_path, "JPEG", quality=95)

    # Also update processing/thumbnails/{video_id}/best_thumb.jpg
    target_thumb_dir = THUMBNAILS_DIR / str(video_id)
    target_thumb_dir.mkdir(parents=True, exist_ok=True)
    best_thumb_path = target_thumb_dir / "best_thumb.jpg"
    img.save(best_thumb_path, "JPEG", quality=95)

    return f"/static/custom_thumbnails/{video_id}.jpg"
