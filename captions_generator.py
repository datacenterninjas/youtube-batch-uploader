import os
import shutil
import subprocess
from pathlib import Path
from google import genai
import config
import database

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

CAPTIONS_DIR = Path("processing/captions")

def extract_audio(video_path: str, output_audio_path: str):
    """Extracts lightweight MP3 audio from a video file for transcription."""
    Path(output_audio_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "64k",
        str(output_audio_path)
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return output_audio_path
    except Exception as e:
        print(f"⚠️ Audio extraction note: {e}")
        return None

def generate_srt_captions(video_id: int, video_path: str):
    """Uses Gemini to generate synchronized .srt subtitles from video audio."""
    CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    srt_output_path = CAPTIONS_DIR / f"{video_id}.srt"
    audio_path = CAPTIONS_DIR / f"{video_id}_temp.mp3"

    extracted = extract_audio(video_path, str(audio_path))
    if not extracted or not os.path.exists(extracted) or os.path.getsize(extracted) < 1000:
        return None

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or config.get_setting("gemini_api_key")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        return None

    try:
        client = genai.Client(api_key=api_key)
        
        # Upload audio file to Gemini Files API
        audio_file = client.files.upload(file=str(audio_path))
        
        prompt = (
            "Transcribe all speech from this audio into standard SRT subtitle format.\n"
            "Format rules:\n"
            "1\n00:00:00,000 --> 00:00:03,500\nSpoken words here\n\n"
            "Output ONLY valid raw SRT format with no markdown code fences, no explanations."
        )

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[audio_file, prompt]
        )

        srt_text = response.text or ""
        srt_text = srt_text.replace("```srt", "").replace("```", "").strip()

        if srt_text:
            with open(srt_output_path, "w", encoding="utf-8") as f:
                f.write(srt_text)
            
            # Clean up temp audio
            if os.path.exists(audio_path):
                os.remove(audio_path)
            return str(srt_output_path)
    except Exception as e:
        print(f"⚠️ Caption transcription note: {e}")
    finally:
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass
    return None

def upload_captions_to_youtube(youtube_client, yt_video_id: str, srt_file_path: str):
    """Uploads .srt caption track to published YouTube video."""
    if not os.path.exists(srt_file_path):
        return None

    from googleapiclient.http import MediaFileUpload
    try:
        media = MediaFileUpload(str(srt_file_path), mimetype="application/x-subrip", resumable=True)
        request = youtube_client.captions().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": yt_video_id,
                    "language": "en",
                    "name": "English (Auto-Transcribed)",
                    "isDraft": False
                }
            },
            media_body=media
        )
        response = request.execute()
        print(f"✅ Captions uploaded to YouTube for {yt_video_id}!")
        return response
    except Exception as e:
        print(f"⚠️ YouTube Caption upload note: {e}")
        return None
