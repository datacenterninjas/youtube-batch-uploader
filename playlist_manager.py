import os
import json
from googleapiclient.errors import HttpError
import database

def get_user_playlists(youtube_client):
    """Fetches list of playlists owned by the authenticated YouTube channel."""
    try:
        request = youtube_client.playlists().list(
            part="snippet,contentDetails",
            mine=True,
            maxResults=50
        )
        response = request.execute()
        items = response.get("items", [])
        playlists = []
        for item in items:
            playlists.append({
                "id": item["id"],
                "title": item["snippet"]["title"],
                "description": item["snippet"].get("description", ""),
                "item_count": item.get("contentDetails", {}).get("itemCount", 0)
            })
        return playlists
    except Exception as e:
        print(f"⚠️ Playlist fetch note: {e}")
        return []

def add_video_to_playlist(youtube_client, playlist_id: str, yt_video_id: str):
    """Adds a published YouTube video to a specific playlist."""
    try:
        request = youtube_client.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": yt_video_id
                    }
                }
            }
        )
        response = request.execute()
        print(f"✅ Video {yt_video_id} added to playlist {playlist_id}!")
        return response
    except Exception as e:
        print(f"⚠️ Add to playlist note: {e}")
        return None

def auto_match_playlist(title: str, tags: list, playlists: list):
    """Finds best matching playlist based on word overlap in title and tags."""
    if not playlists:
        return None

    title_lower = (title or "").lower()
    tags_lower = [t.lower() for t in tags] if tags else []

    best_match = None
    max_score = 0

    for pl in playlists:
        pl_title = pl["title"].lower()
        score = 0
        
        # Check direct title contains
        for word in pl_title.split():
            if len(word) > 3:
                if word in title_lower:
                    score += 2
                for tag in tags_lower:
                    if word in tag:
                        score += 1
                        
        if score > max_score and score >= 2:
            max_score = score
            best_match = pl

    return best_match
