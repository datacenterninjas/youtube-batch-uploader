import os
import shutil
import subprocess
from pathlib import Path
import cv2
import activity_tracker

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

merge_state = {
    "status": "idle",
    "percent": 0,
    "message": "Ready"
}

def get_merge_progress():
    return merge_state

def set_merge_progress(status, percent, message):
    global merge_state
    merge_state = {
        "status": status,
        "percent": int(percent),
        "message": message
    }
    activity_tracker.set_activity("MERGING", message, progress=percent, active=(status == "merging"))

def get_video_duration(filepath):
    try:
        cap = cv2.VideoCapture(str(filepath))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        return frame_count / fps if fps > 0 else 0.0
    except Exception:
        return 0.0

def merge_videos_hardware_accelerated(video_paths, output_path):
    """
    Merges videos using Apple Silicon M-series Hardware Acceleration (VideoToolbox)
    or lossless Stream Copy Concat.
    """
    if not video_paths:
        raise ValueError("No video paths provided for merging.")

    set_merge_progress("merging", 10, f"Preparing Apple Silicon M4 GPU merge for {len(video_paths)} clips...")

    concat_list_file = Path(output_path).parent / f"concat_{os.getpid()}.txt"
    try:
        with open(concat_list_file, "w") as f:
            for vp in video_paths:
                f.write(f"file '{os.path.abspath(vp)}'\n")

        # Step 1: Try Lossless Stream Copy (takes ~0.2-1.0s, 0 quality loss)
        set_merge_progress("merging", 30, f"🚀 Executing lossless stream copy merge...")
        cmd_copy = [
            FFMPEG_BIN, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path)
        ]
        res = subprocess.run(cmd_copy, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
        
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            duration = get_video_duration(output_path)
            set_merge_progress("complete", 100, f"⚡ Fast Merge Complete ({duration:.1f}s)!")
            activity_tracker.clear_activity()
            print(f"🎬 [M4 FAST STREAM COPY SUCCESS] Merged {len(video_paths)} videos in <1s: '{output_path}'")
            return output_path, duration

        # Step 2: If stream copy fails (differing codecs/resolutions), use Apple M4 VideoToolbox GPU Encoder
        set_merge_progress("merging", 50, "⚡ Accelerating with Apple Silicon M4 VideoToolbox GPU...")
        cmd_gpu = [
            FFMPEG_BIN, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list_file),
            "-c:v", "h264_videotoolbox",
            "-b:v", "25M",
            "-allow_sw", "1",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path)
        ]
        res_gpu = subprocess.run(cmd_gpu, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        if res_gpu.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            duration = get_video_duration(output_path)
            set_merge_progress("complete", 100, f"⚡ Apple M4 GPU Merge Complete ({duration:.1f}s)!")
            activity_tracker.clear_activity()
            print(f"🎬 [M4 GPU VIDEOTOOLBOX SUCCESS] Merged {len(video_paths)} videos with GPU acceleration: '{output_path}'")
            return output_path, duration
            
    except Exception as e:
        print(f"ℹ️ Hardware acceleration note: {e}, attempting software fallback.")
    finally:
        if concat_list_file.exists():
            try:
                os.remove(concat_list_file)
            except OSError:
                pass

    # Step 3: Resilient OpenCV Fallback
    return merge_videos_opencv(video_paths, output_path)

def merge_videos_opencv(video_paths, output_path):
    """Concatenates multiple video files sequentially using OpenCV with progress tracking."""
    set_merge_progress("merging", 15, f"Analyzing {len(video_paths)} videos for frame merge...")

    total_expected_frames = 0
    first_cap = cv2.VideoCapture(str(video_paths[0]))
    if not first_cap.isOpened():
        raise ValueError(f"Could not open first video: {video_paths[0]}")

    width = int(first_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(first_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = first_cap.get(cv2.CAP_PROP_FPS) or 30.0
    first_cap.release()

    for vp in video_paths:
        c = cv2.VideoCapture(str(vp))
        fc = int(c.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        c.release()
        total_expected_frames += fc

    if total_expected_frames <= 0:
        total_expected_frames = 100

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out_writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    processed_frames = 0
    for i, v_path in enumerate(video_paths, 1):
        cap = cv2.VideoCapture(str(v_path))
        if not cap.isOpened():
            continue
            
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            h, w = frame.shape[:2]
            if (w, h) != (width, height):
                frame = cv2.resize(frame, (width, height))
            out_writer.write(frame)
            processed_frames += 1
            if processed_frames % 25 == 0:
                pct = min(95, int((processed_frames / total_expected_frames) * 90))
                set_merge_progress("merging", pct, f"Merging clip {i} of {len(video_paths)}: '{Path(v_path).name}' ({pct}%)...")
        cap.release()

    out_writer.release()
    set_merge_progress("complete", 100, "Merge complete! Staging video...")
    duration = processed_frames / fps if fps > 0 else 0.0
    activity_tracker.clear_activity()
    return output_path, duration

def merge_videos(video_paths, output_path):
    """Main entry point: executes Apple Silicon GPU merge with stream copy."""
    return merge_videos_hardware_accelerated(video_paths, output_path)

def convert_to_shorts_9_16(input_path: str, output_path: str):
    """
    Converts landscape / standard video to 9:16 vertical (1080x1920) YouTube Shorts format.
    Uses VideoToolbox Apple Silicon GPU acceleration with a modern blurred background stack.
    """
    set_merge_progress("merging", 15, "Converting video to 9:16 YouTube Shorts on Apple Silicon M4 GPU...")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    filter_complex = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
    )

    cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "h264_videotoolbox",
        "-b:v", "15M",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path)
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        set_merge_progress("complete", 100, "9:16 Shorts conversion complete!")
        activity_tracker.clear_activity()
        return output_path
    except Exception as e:
        cmd_fallback = [
            FFMPEG_BIN, "-y",
            "-i", str(input_path),
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "22",
            "-c:a", "aac",
            str(output_path)
        ]
        subprocess.run(cmd_fallback, capture_output=True, text=True, check=True)
        set_merge_progress("complete", 100, "9:16 Shorts conversion complete!")
        activity_tracker.clear_activity()
        return output_path
