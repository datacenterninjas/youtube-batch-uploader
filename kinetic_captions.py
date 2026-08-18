import os
import subprocess
from pathlib import Path
import imageio_ffmpeg
import captions_generator

def get_ffmpeg():
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def srt_to_ass(srt_path, ass_path):
    """
    Converts an SRT file into a styled ASS subtitle file with MrBeast / Hormozi style bold kinetic typography.
    """
    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HormoziYellow, Impact, 68, &H0000FFFF, &H00FFFFFF, &H00000000, &H80000000, 1, 0, 0, 0, 100, 100, 1, 0, 1, 4, 3, 2, 40, 40, 280, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if not Path(srt_path).exists():
        raise FileNotFoundError(f"SRT file not found: {srt_path}")

    with open(srt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    events = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.isdigit():
            i += 1
            if i >= len(lines):
                break
            time_line = lines[i].strip()
            if "-->" in time_line:
                start_str, end_str = time_line.split("-->")
                start_ass = format_time_ass(start_str.strip())
                end_ass = format_time_ass(end_str.strip())
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip() and not lines[i].strip().isdigit():
                    text_lines.append(lines[i].strip())
                    i += 1
                raw_text = " ".join(text_lines).upper()
                # Highlight with bold styling
                styled_text = f"{{\\b1\\c&H0000FFFF&}}{raw_text}"
                events.append(f"Dialogue: 0,{start_ass},{end_ass},HormoziYellow,,0,0,0,,{styled_text}")
        else:
            i += 1

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header + "\n".join(events) + "\n")

    return ass_path

def format_time_ass(srt_time_str):
    """Converts 00:00:01,500 to 0:00:01.50"""
    parts = srt_time_str.replace(",", ".").split(":")
    hours = int(parts[0])
    mins = int(parts[1])
    secs = float(parts[2])
    return f"{hours}:{mins:02d}:{secs:05.2f}"

def burn_kinetic_captions(video_id, input_video_path, output_video_path=None):
    """
    Generates and burns high-impact kinetic word-by-word subtitles into the video
    using Apple Silicon M4 GPU acceleration.
    """
    input_p = Path(input_video_path)
    srt_path = Path(f"processing/captions/{video_id}.srt")
    
    # Ensure SRT exists or generate on the fly
    if not srt_path.exists():
        captions_generator.generate_srt_captions(video_id, str(input_p))

    ass_path = Path(f"processing/captions/{video_id}.ass")
    srt_to_ass(str(srt_path), str(ass_path))

    if not output_video_path:
        out_p = input_p.parent / f"{input_p.stem}_kinetic{input_p.suffix}"
    else:
        out_p = Path(output_video_path)

    ffmpeg = get_ffmpeg()
    
    # Burn ASS subtitles with Apple Silicon VideoToolbox
    cmd = [
        ffmpeg, "-y",
        "-i", str(input_p),
        "-vf", f"ass={str(ass_path)}",
        "-c:v", "h264_videotoolbox",
        "-b:v", "8000k",
        "-c:a", "copy",
        str(out_p)
    ]

    print(f"⚡ Burning kinetic captions onto '{input_p.name}'...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        # Fallback to software libx264
        fallback_cmd = [
            ffmpeg, "-y",
            "-i", str(input_p),
            "-vf", f"ass={str(ass_path)}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "copy",
            str(out_p)
        ]
        res_fb = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res_fb.returncode != 0:
            raise RuntimeError(f"Burning kinetic captions failed: {res_fb.stderr}")

    return str(out_p)
