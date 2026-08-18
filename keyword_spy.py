import json
import os
import re
import urllib.request
import urllib.parse
import ssl
from google import genai
from google.genai import types
import config

def get_gemini_client():
    api_key = config.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Google Gemini API key is missing.")
    return genai.Client(api_key=api_key)

def fetch_public_youtube_competitors(query, max_results=8):
    """Fetches real live YouTube search competitor rankings without consuming OAuth quota."""
    competitors = []
    try:
        ctx = ssl._create_unverified_context()
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.youtube.com/results?search_query={encoded_query}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        })
        html = urllib.request.urlopen(req, context=ctx, timeout=8).read().decode("utf-8")
        
        match = re.search(r'var ytInitialData = ({.*?});</script>', html)
        if match:
            data = json.loads(match.group(1))
            contents = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
            for section in contents:
                for item in section.get("itemSectionRenderer", {}).get("contents", []):
                    v = item.get("videoRenderer")
                    if v and len(competitors) < max_results:
                        title = v.get("title", {}).get("runs", [{}])[0].get("text", "")
                        vid_id = v.get("videoId", "")
                        channel = v.get("ownerText", {}).get("runs", [{}])[0].get("text", "")
                        view_text = v.get("viewCountText", {}).get("simpleText", "0 views")
                        
                        # Parse approximate view number
                        views_digits = re.sub(r"[^\d]", "", view_text)
                        views_count = int(views_digits) if views_digits else 0
                        
                        thumb = v.get("thumbnail", {}).get("thumbnails", [{}])[-1].get("url", "")
                        
                        competitors.append({
                            "id": vid_id,
                            "title": title,
                            "channel": channel,
                            "views": views_count,
                            "views_formatted": view_text,
                            "likes": 0,
                            "thumbnail": thumb
                        })
    except Exception as e:
        print(f"⚠️ YouTube public search note: {e}")
        
    return competitors

def spy_competitor_keywords(query, max_results=8):
    """
    Searches YouTube for top ranking competitor videos, extracts their titles,
    and analyzes the highest-velocity SEO keywords with Gemini 3.6 Flash.
    """
    if not query or not query.strip():
        query = "Travel and Entertainment Vlog"
        
    query = query.strip()
    competitors = fetch_public_youtube_competitors(query, max_results=max_results)

    # If public search returned 0 items, construct generic search context
    competitor_titles = [c["title"] for c in competitors] if competitors else [query]

    # Analyze with Gemini 3.6 Flash to find viral keywords & winning SEO strategy
    try:
        client = get_gemini_client()
        prompt = f"""
        You are a world-class YouTube SEO & Growth Strategist.
        Analyze these top-ranking YouTube competitor videos for the search niche: "{query}".

        Top Competitor Titles:
        {json.dumps(competitor_titles, indent=2)}

        Task:
        1. Identify the top 15 highest-velocity, viral YouTube search tags for this topic.
        2. Suggest 3 high-CTR title variations tailored to outrank these competitors.
        3. Identify the winning content angle to get more views and CTR.

        Respond ONLY with valid JSON in this exact structure:
        {{
            "recommended_tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10", "tag11", "tag12", "tag13", "tag14", "tag15"],
            "recommended_titles": ["Title 1", "Title 2", "Title 3"],
            "winning_angle": "Summary of winning content & SEO angle to outrank competitors"
        }}
        """

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt
        )

        text = response.text.strip()
        text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)

        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            ai_data = json.loads(json_match.group(0))
            return {
                "competitors": competitors,
                "recommended_tags": ai_data.get("recommended_tags", []),
                "recommended_titles": ai_data.get("recommended_titles", []),
                "winning_angle": ai_data.get("winning_angle", f"Optimized keywords for '{query}'")
            }
    except Exception as e:
        print(f"⚠️ Competitor keyword analysis note: {e}")

    # Heuristic Fallback
    words = [w.lower() for w in re.findall(r'\w+', query) if len(w) > 2]
    fallback_tags = list(dict.fromkeys(words + [f"{query} vlog", f"best {query}", f"{query} guide", "youtube shorts", "trending"]))
    return {
        "competitors": competitors,
        "recommended_tags": fallback_tags[:15],
        "recommended_titles": [f"Ultimate {query.title()} Guide", f"Top Highlights of {query.title()}"],
        "winning_angle": f"Target high-interest search keywords around '{query}'."
    }
