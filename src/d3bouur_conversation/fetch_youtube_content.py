#!/usr/bin/env python3
"""One-off extraction: pull video titles + descriptions (text only, no video
files) from the AcaROBOTICS YouTube channel via the official YouTube Data
API v3, for review before turning into knowledge/ content.

Run from this directory:
    python3 fetch_youtube_content.py

Writes the raw extracted text to youtube_extract_draft.json for review —
this script does NOT touch knowledge/ or the index itself.
"""

import json
import sys
from pathlib import Path

import requests

from d3bouur_conversation.llm_router import _load_env_file, _default_env_path

_load_env_file(_default_env_path())

import os

API_KEY = os.environ.get("YOUTUBE_API_KEY")
CHANNEL_HANDLE = "acarobotics4006"
API_BASE = "https://www.googleapis.com/youtube/v3"
OUTPUT_PATH = Path(__file__).resolve().parent / "youtube_extract_draft.json"


def get_uploads_playlist_id(handle: str) -> str:
    resp = requests.get(
        f"{API_BASE}/channels",
        params={"part": "contentDetails,snippet", "forHandle": handle, "key": API_KEY},
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


def fetch_all_videos(uploads_playlist_id: str) -> list:
    videos = []
    page_token = None
    while True:
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": 50,
            "key": API_KEY,
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


def main() -> None:
    if not API_KEY:
        print("ERROR: YOUTUBE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    uploads_playlist_id = get_uploads_playlist_id(CHANNEL_HANDLE)
    videos = fetch_all_videos(uploads_playlist_id)

    OUTPUT_PATH.write_text(json.dumps(videos, ensure_ascii=False, indent=2))
    print(f"\nFetched {len(videos)} videos. Written to {OUTPUT_PATH}")
    print("\n--- Titles ---")
    for v in videos:
        print(f"- {v['title']}")


if __name__ == "__main__":
    main()
