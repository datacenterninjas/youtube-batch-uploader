import json
import os
from googleapiclient.discovery import build
from google import genai
from google.genai import types
import config
from uploader import authenticate

def get_gemini_client():
    api_key = config.get_setting("gemini_api_key")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Google Gemini API key is missing.")
    return genai.Client(api_key=api_key)

def spy_competitor_keywords(query, max_results=8):
    """
    Searches YouTube for top ranking competitor videos, extracts their exact tags,
    view counts, and analyzes the highest-velocity SEO keywords with Gemini.
    """
    youtube_client = authenticate()
    
    # 1. Search top ranking videos
    search_res = youtube_client.search().list(
        q=query,
        part="snippet",
        maxResults=max_results,
        type="video",
        order="relevance"
    ).execute()

    video_ids = [item["id"]["videoId"] for item in search_res.get("items", []) if "videoId" in item.get("id", {})]
    
    if not video_ids:
        return {"competitors": [], "recommended_tags": [], "seo_insights": "No competitor videos found."}

    # 2. Get full video details (tags & view counts)
    vids_res = youtube_client.videos().list(
        part="snippet,statistics",
        id=",".join(video_ids)
    ).execute()

    competitors = []
    all_tags = []

    for v in vids_res.get("items", []):
        snippet = v["snippet"]
        stats = v.get("statistics", {})
        tags = snippet.get("tags", [])
        all_tags.extend(tags)
        
        competitors.append({
            "id": v["id"],
            "title": snippet["title"],
            "channel": snippet["channelTitle"],
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "tags": tags[:8],
            "thumbnail": snippet["thumbnails"].get("medium", {}).get("url", "")
        })

    # Sort competitors by views
    competitors.sort(key=lambda x: x["views"], reverse=True)

    # 3. Analyze with Gemini to find viral keywords
    client = get_gemini_client()
    prompt = f"""
    You are a world-class YouTube SEO Strategist.
    Analyze the following top-ranking competitor videos and tags for the search query: "{query}".

    Top Competitor Data:
    {json.dumps([{'title': c['title'], 'views': c['views'], 'tags': c['tags']} for c in competitors[:5]], indent=2)}

    Task:
    1. Identify the top 15 highest-velocity, high-reach YouTube search tags.
    2. Suggest 3 high-CTR title variations tailored to outrank these competitors.
    3. Return valid JSON only in this exact structure:
    {{
        "recommended_tags": ["tag1", "tag2", "tag3"],
        "recommended_titles": ["Title 1", "Title 2", "Title 3"],
        "winning_angle": "Summary of why this strategy will outrank competitors..."
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
        ai_data = json.loads(response.text)
        return {
            "competitors": competitors,
            "recommended_tags": ai_data.get("recommended_tags", []),
            "recommended_titles": ai_data.get("recommended_titles", []),
            "winning_angle": ai_data.get("winning_angle", "")
        }
    except Exception as e:
        print(f"⚠️ Competitor keyword analysis note: {e}")
        # Fallback to direct frequency tags
        from collections import Counter
        tag_counts = Counter(all_tags).most_common(15)
        return {
            "competitors": competitors,
            "recommended_tags": [t[0] for t in tag_counts],
            "recommended_titles": [],
            "winning_angle": "Tags extracted directly from top ranking videos."
        }
