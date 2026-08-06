#!/usr/bin/env python3
"""One-off extraction: pull video titles + descriptions (text only, no video
files) from the AcaROBOTICS YouTube channel via the official YouTube Data
API v3, for review before turning into knowledge/ content.

Run from this directory:
    python3 fetch_youtube_content.py

Writes the raw extracted text to youtube_extract_draft.json for review —
this script does NOT touch knowledge/ or the index itself.

For the scheduled version that also checks the website and produces a
review summary of what changed, see check_for_updates.py.
"""

import json
import os
import sys
from pathlib import Path

from d3bouur_conversation.content_pipeline.youtube_fetch import fetch_channel_videos
from d3bouur_conversation.llm_router import _default_env_path, _load_env_file

_load_env_file(_default_env_path())

API_KEY = os.environ.get("YOUTUBE_API_KEY")
OUTPUT_PATH = Path(__file__).resolve().parent / "youtube_extract_draft.json"


def main() -> None:
    if not API_KEY:
        print("ERROR: YOUTUBE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    videos = fetch_channel_videos(API_KEY)

    OUTPUT_PATH.write_text(json.dumps(videos, ensure_ascii=False, indent=2))
    print(f"\nFetched {len(videos)} videos. Written to {OUTPUT_PATH}")
    print("\n--- Titles ---")
    for v in videos:
        print(f"- {v['title']}")


if __name__ == "__main__":
    main()
