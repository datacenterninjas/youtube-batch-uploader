import json
import os
from pathlib import Path
from google import genai
from google.genai import types
from googleapiclient.http import MediaFileUpload
import config

SUPPORTED_LANGUAGES = {
    "es": "Spanish (Español)",
    "hi": "Hindi (हिंदी)",
    "fr": "French (Français)",
    "de": "German (Deutsch)",
    "ja": "Japanese (日本語)",
    "pt": "Portuguese (Português)"
}

def get_client():
    api_key = config.get_setting("gemini_api_key")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Google Gemini API key is missing.")
    return genai.Client(api_key=api_key)

def translate_metadata(title, description, target_languages=None):
    """
    Translates title and description into multiple target languages using Gemini.
    Returns a dict formatted for YouTube's `localizations` parameter:
    {
        "es": {"title": "...", "description": "..."},
        "hi": {"title": "...", "description": "..."}
    }
    """
    if target_languages is None:
        target_languages = ["es", "hi", "fr", "ja", "de"]

    client = get_client()
    lang_prompts = ", ".join([f"{code} ({SUPPORTED_LANGUAGES.get(code, code)})" for code in target_languages])

    prompt = f"""
    You are an expert YouTube localization translator.
    Translate the following YouTube video Title and Description into these languages: {lang_prompts}.

    Original Title: {title}
    Original Description: {description}

    Translation Guidelines:
    1. Keep titles high-CTR, exciting, and natural for local native speakers (under 95 characters).
    2. Preserve all hashtags, links, and timestamp formatting (e.g. 00:00, 01:30) in the description.
    3. Return ONLY valid JSON in this exact structure:
    {{
        "localizations": {{
            "es": {{
                "title": "Spanish Title",
                "description": "Spanish Description..."
            }},
            "hi": {{
                "title": "Hindi Title",
                "description": "Hindi Description..."
            }}
        }}
    }}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json"
            )
        )
        data = json.loads(response.text)
        return data.get("localizations", {})
    except Exception as e:
        print(f"⚠️ Multilingual translation error: {e}")
        return {}

def translate_srt(srt_text, target_language_code):
    """
    Translates an SRT subtitle content string into the target language while keeping exact timestamps.
    """
    if not srt_text.strip():
        return ""

    client = get_client()
    lang_name = SUPPORTED_LANGUAGES.get(target_language_code, target_language_code)

    prompt = f"""
    Translate the following SubRip (.SRT) subtitle text into {lang_name}.

    CRITICAL RULES:
    1. Keep ALL timestamp numbers and arrow lines EXACTLY untouched (e.g. "00:00:01,000 --> 00:00:04,500").
    2. Keep subtitle numbering intact (1, 2, 3, etc.).
    3. Translate only the spoken text lines naturally and accurately into {lang_name}.
    4. Output ONLY the translated raw SRT text.

    Original SRT:
    {srt_text}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2
            )
        )
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ SRT translation error for {target_language_code}: {e}")
        return ""

def generate_and_save_multilingual_assets(video_id, title, description, target_languages=None):
    """
    Generates translated metadata and translated SRT tracks, saving them to disk under processing/multilingual/{video_id}/.
    """
    if target_languages is None:
        target_languages = ["es", "hi", "fr", "ja", "de"]

    out_dir = Path(f"processing/multilingual/{video_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Translate Metadata
    localizations = translate_metadata(title, description, target_languages)
    with open(out_dir / "localizations.json", "w", encoding="utf-8") as f:
        json.dump(localizations, f, ensure_ascii=False, indent=2)

    # 2. Translate Subtitles if master SRT exists
    master_srt_path = Path(f"processing/captions/{video_id}.srt")
    translated_srts = {}
    if master_srt_path.exists():
        with open(master_srt_path, "r", encoding="utf-8") as f:
            master_srt = f.read()

        for lang in target_languages:
            trans_srt = translate_srt(master_srt, lang)
            if trans_srt:
                srt_file = out_dir / f"subtitles_{lang}.srt"
                with open(srt_file, "w", encoding="utf-8") as f:
                    f.write(trans_srt)
                translated_srts[lang] = str(srt_file)

    print(f"🌍 Generated multilingual assets for video #{video_id} across {len(localizations)} languages!")
    return localizations, translated_srts

def upload_localizations_to_youtube(youtube_client, yt_video_id, localizations):
    """
    Updates YouTube video resource with multilingual localized titles & descriptions.
    """
    if not localizations or not yt_video_id:
        return

    try:
        # Get existing video snippet
        vid_res = youtube_client.videos().list(part="snippet,localizations", id=yt_video_id).execute()
        if not vid_res.get("items"):
            return

        item = vid_res["items"][0]
        snippet = item["snippet"]
        snippet["defaultLanguage"] = snippet.get("defaultLanguage") or "en"

        youtube_client.videos().update(
            part="snippet,localizations",
            body={
                "id": yt_video_id,
                "snippet": {
                    "categoryId": snippet.get("categoryId", "22"),
                    "title": snippet["title"],
                    "description": snippet["description"],
                    "defaultLanguage": snippet["defaultLanguage"]
                },
                "localizations": localizations
            }
        ).execute()
        print(f"🌍 YouTube localizations applied for {yt_video_id} ({list(localizations.keys())})!")
    except Exception as e:
        print(f"⚠️ YouTube localizations update note: {e}")

def upload_multilingual_captions(youtube_client, yt_video_id, translated_srts):
    """
    Uploads all translated SRT subtitle tracks to YouTube Captions API.
    """
    for lang_code, srt_path in translated_srts.items():
        if not Path(srt_path).exists():
            continue
        try:
            lang_name = SUPPORTED_LANGUAGES.get(lang_code, lang_code)
            media = MediaFileUpload(str(srt_path), mimetype="application/x-subrip", resumable=True)
            youtube_client.captions().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": yt_video_id,
                        "language": lang_code,
                        "name": lang_name,
                        "isDraft": False
                    }
                },
                media_body=media
            ).execute()
            print(f"🎙️ Uploaded {lang_name} subtitles to YouTube for {yt_video_id}!")
        except Exception as e:
            print(f"ℹ️ Captions upload note for {lang_code}: {e}")
