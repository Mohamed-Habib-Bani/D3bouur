"""YouTube Data API v3 fetch logic.

Extracted out of fetch_youtube_content.py (the original one-off extraction
script) so this same fetching code can be shared between that script and
the scheduled content pipeline (check_for_updates.py) without duplication.
fetch_youtube_content.py now just calls fetch_channel_videos().
"""

import requests

API_BASE = "https://www.googleapis.com/youtube/v3"
CHANNEL_HANDLE = "acarobotics4006"


def get_uploads_playlist_id(api_key: str, handle: str = CHANNEL_HANDLE) -> str:
    resp = requests.get(
        f"{API_BASE}/channels",
        params={"part": "contentDetails,snippet", "forHandle": handle, "key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", [])
    if not items:
        raise RuntimeError(f"no channel found for handle @{handle}: {data}")
    channel = items[0]
    print(f"Resolved channel: {channel['snippet']['title']} (id={channel['id']})")
    return channel["contentDetails"]["relatedPlaylists"]["uploads"]


def fetch_all_videos(api_key: str, uploads_playlist_id: str) -> list[dict]:
    videos = []
    page_token = None
    while True:
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(f"{API_BASE}/playlistItems", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            snippet = item["snippet"]
            videos.append(
                {
                    "video_id": snippet["resourceId"]["videoId"],
                    "title": snippet["title"],
                    "description": snippet["description"],
                    "published_at": snippet["publishedAt"],
                }
            )

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos


def fetch_channel_videos(api_key: str, handle: str = CHANNEL_HANDLE) -> list[dict]:
    uploads_playlist_id = get_uploads_playlist_id(api_key, handle)
    return fetch_all_videos(api_key, uploads_playlist_id)
