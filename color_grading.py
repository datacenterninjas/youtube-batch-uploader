import os
import subprocess
from pathlib import Path
import imageio_ffmpeg

def get_ffmpeg():
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

LUT_PRESETS = {
    "golden_hour": {
        "title": "🌅 Golden Hour Warmth",
        "description": "Rich amber glow, enhanced warm skin tones and softened highlights",
        "filter": "eq=contrast=1.12:brightness=0.02:saturation=1.25,colorlevels=rimax=0.98:gimax=0.96:bimax=0.90"
    },
    "teal_orange": {
        "title": "🌊 Teal & Orange (Hollywood Cinema)",
        "description": "High-contrast blockbuster aesthetic with rich blues/teals and vibrant skin warmth",
        "filter": "eq=contrast=1.15:saturation=1.2,colorbalance=rs=0.15:gs=-0.05:bs=-0.1:rh=-0.1:gh=0.05:bh=0.15"
    },
    "vibrant_hdr": {
        "title": "💎 Vibrant HDR Pop",
        "description": "Hyper-punchy colors, crystal clarity, and enhanced local contrast",
        "filter": "eq=contrast=1.2:saturation=1.35:brightness=0.01,unsharp=5:5:0.8:5:5:0.0"
    },
    "moody_film": {
        "title": "🎥 Moody Vintage 35mm",
        "description": "Matte shadows, muted tones, and authentic nostalgic film look",
        "filter": "eq=contrast=1.08:saturation=0.85,colorlevels=rimin=0.05:gimin=0.04:bimin=0.03:rimax=0.92:gimax=0.92:bimax=0.90"
    }
}

def get_available_presets():
    """Returns list of available color grading LUT presets."""
    return [{"id": k, "title": v["title"], "description": v["description"]} for k, v in LUT_PRESETS.items()]

def apply_color_grading(input_video_path, preset_id="golden_hour", output_video_path=None):
    """
    Applies professional cinematic color grading preset using Apple Silicon M4 GPU acceleration.
    """
    input_p = Path(input_video_path)
    preset = LUT_PRESETS.get(preset_id, LUT_PRESETS["golden_hour"])
    video_filter = preset["filter"]

    if not output_video_path:
        out_p = input_p.parent / f"{input_p.stem}_graded_{preset_id}{input_p.suffix}"
    else:
        out_p = Path(output_video_path)

    ffmpeg = get_ffmpeg()

    cmd = [
        ffmpeg, "-y",
        "-i", str(input_p),
        "-vf", video_filter,
        "-c:v", "h264_videotoolbox",
        "-b:v", "8000k",
        "-c:a", "copy",
        str(out_p)
    ]

    print(f"🎬 Applying '{preset['title']}' color grading to '{input_p.name}'...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        # Fallback to software libx264
        fallback_cmd = [
            ffmpeg, "-y",
            "-i", str(input_p),
            "-vf", video_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "copy",
            str(out_p)
        ]
        res_fb = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res_fb.returncode != 0:
            raise RuntimeError(f"Color grading failed: {res_fb.stderr}")

    return str(out_p)
