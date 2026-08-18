import os
import subprocess
from pathlib import Path
import imageio_ffmpeg
import config

def get_ffmpeg():
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def generate_endscreen_description(existing_description, channel_title="Our Channel", playlist_id=None, related_video_id=None):
    """
    Appends high-conversion End Screen & Interactive Links to the bottom of the video description.
    """
    cta_blocks = [
        "\n\n═══════════════════════════════════════",
        f"🔔 SUBSCRIBE FOR MORE: Thanks for watching {channel_title}!",
        "👉 Drop a like and subscribe to stay tuned for upcoming videos."
    ]

    if playlist_id:
        cta_blocks.append(f"🎬 WATCH THE FULL PLAYLIST: https://www.youtube.com/playlist?list={playlist_id}")

    if related_video_id:
        cta_blocks.append(f"📌 WATCH NEXT: https://youtu.be/{related_video_id}")

    cta_blocks.append("═══════════════════════════════════════\n")

    endscreen_text = "\n".join(cta_blocks)
    if "═══════════════════════════════════════" not in existing_description:
        return existing_description.rstrip() + endscreen_text
    return existing_description

def append_endscreen_outro(input_video_path, output_video_path=None, duration_seconds=5):
    """
    Generates and appends a 5-second cinematic End Screen outro bumper with
    'THANKS FOR WATCHING' & 'SUBSCRIBE' layout to the video using Apple Silicon M4 GPU acceleration.
    """
    input_p = Path(input_video_path)
    if not output_video_path:
        out_p = input_p.parent / f"{input_p.stem}_endscreen{input_p.suffix}"
    else:
        out_p = Path(output_video_path)

    ffmpeg = get_ffmpeg()
    
    # Filter graph:
    # 1. Take the last frame of the video and freeze it for 5s with dark cinematic blur
    # 2. Draw styled text overlays for YouTube End Screen elements
    # 3. Concatenate video + outro with a smooth audio fade-out
    filter_complex = (
        f"[0:v]split=2[v_main][v_end];"
        f"[v_end]trim=start_frame=0:end_frame=1,loop=loop={duration_seconds*30}:size=1:start=0,"
        f"boxblur=luma_radius=15:luma_power=2,colorlevels=rimin=0.1:gimin=0.1:bimin=0.1:rimax=0.6:gimax=0.6:bimax=0.6,"
        f"drawtext=text='THANKS FOR WATCHING':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=120:shadowcolor=black:shadowx=2:shadowy=2,"
        f"drawtext=text='SUBSCRIBE & WATCH NEXT':fontcolor=#38bdf8:fontsize=32:x=(w-text_w)/2:y=200:shadowcolor=black:shadowx=2:shadowy=2[v_outro];"
        f"[v_main][0:a][v_outro][0:a]concat=n=2:v=1:a=1[v_out][a_out]"
    )

    cmd = [
        ffmpeg, "-y",
        "-i", str(input_p),
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        "-map", "[a_out]",
        "-c:v", "h264_videotoolbox",
        "-b:v", "8000k",
        "-c:a", "aac",
        "-b:a", "192k",
        str(out_p)
    ]

    print(f"🎬 Creating and appending 5s End Screen outro for '{input_p.name}'...")
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        # Fallback to software encoder if videotoolbox filter fails
        fallback_cmd = [
            ffmpeg, "-y",
            "-i", str(input_p),
            "-filter_complex", filter_complex,
            "-map", "[v_out]",
            "-map", "[a_out]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "192k",
            str(out_p)
        ]
        res_fb = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res_fb.returncode != 0:
            raise RuntimeError(f"End screen generation failed: {res_fb.stderr}")

    return str(out_p)
