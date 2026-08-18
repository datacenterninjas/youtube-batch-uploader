import os
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE = "token.pickle"

def get_youtube_client():
    """Builds and returns authenticated YouTube API service."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            try:
                creds = pickle.load(token)
            except Exception:
                creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_FILE, "wb") as token:
                    pickle.dump(creds, token)
            except Exception:
                return None
        else:
            return None
            
    try:
        return build("youtube", "v3", credentials=creds)
    except Exception:
        return None

def get_channel_profile():
    """Fetches details about currently authenticated YouTube Channel."""
    yt = get_youtube_client()
    if not yt:
        return {
            "authenticated": False,
            "title": "Not Connected",
            "custom_url": "",
            "thumbnail": "",
            "subscriber_count": 0,
            "video_count": 0
        }
        
    try:
        response = yt.channels().list(part="snippet,statistics", mine=True).execute()
        items = response.get("items", [])
        if items:
            ch = items[0]
            snippet = ch.get("snippet", {})
            stats = ch.get("statistics", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb_url = thumbnails.get("default", {}).get("url") or thumbnails.get("medium", {}).get("url") or ""
            
            return {
                "authenticated": True,
                "id": ch.get("id"),
                "title": snippet.get("title", "YouTube Channel"),
                "custom_url": snippet.get("customUrl", ""),
                "description": snippet.get("description", ""),
                "thumbnail": thumb_url,
                "subscriber_count": stats.get("subscriberCount", "Hidden"),
                "video_count": stats.get("videoCount", 0)
            }
    except Exception as e:
        print(f"ℹ️ Channel profile note: {e}")
        
    return {
        "authenticated": True,
        "title": "YouTube Account Connected",
        "custom_url": "(Upload Access Active)",
        "thumbnail": "",
        "subscriber_count": "Active",
        "video_count": "Active"
    }

def switch_youtube_channel():
    """Removes existing token and initiates OAuth flow in browser to connect another channel."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        
    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise FileNotFoundError("client_secrets.json not found.")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "wb") as token:
        pickle.dump(creds, token)
        
    return get_channel_profile()
