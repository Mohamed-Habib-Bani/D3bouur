#!/usr/bin/env python3
"""Weekly content check for D3BOUUR's knowledge sources.

Run from this directory (no colcon build needed):
    python3 check_for_updates.py

Fetches the AcaROBOTICS website's known pages and the YouTube channel, and
compares them against the currently *published* draft files
(website_extract_draft.json, youtube_extract_draft.json) — the ones a human
has already reviewed and accepted. This script does NOT touch those files,
knowledge/*.md, or the RAG index. It only writes:

    staging/pending_website_extract.json   (the newly fetched snapshot)
    staging/pending_youtube_extract.json   (the newly fetched snapshot)
    staging/review_summary_<timestamp>.md  (what changed, in plain language)

Read the summary, then run publish_content.py to accept it as the new
baseline. See README.md in this folder for adding this to a weekly cron job
once running on the always-on Pi 5 — on this dev machine, just run it
on demand.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from d3bouur_conversation.content_pipeline.diffing import diff_website, diff_youtube, render_summary
from d3bouur_conversation.content_pipeline.website_fetch import fetch_pages
from d3bouur_conversation.content_pipeline.youtube_fetch import fetch_channel_videos
from d3bouur_conversation.llm_router import _default_env_path, _load_env_file

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

PACKAGE_ROOT = Path(__file__).resolve().parent
STAGING_DIR = PACKAGE_ROOT / "staging"
WEBSITE_DRAFT_PATH = PACKAGE_ROOT / "website_extract_draft.json"
YOUTUBE_DRAFT_PATH = PACKAGE_ROOT / "youtube_extract_draft.json"
PENDING_WEBSITE_PATH = STAGING_DIR / "pending_website_extract.json"
PENDING_YOUTUBE_PATH = STAGING_DIR / "pending_youtube_extract.json"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    _load_env_file(_default_env_path())
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY")
    if not youtube_api_key:
        print("ERROR: YOUTUBE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    STAGING_DIR.mkdir(exist_ok=True)

    print("Fetching website pages...")
    new_website = fetch_pages()
    old_website = _load_json(WEBSITE_DRAFT_PATH, {})

    print("Fetching YouTube channel...")
    new_videos = fetch_channel_videos(youtube_api_key)
    old_videos = _load_json(YOUTUBE_DRAFT_PATH, [])

    website_changes = diff_website(old_website, new_website)
    video_changes = diff_youtube(old_videos, new_videos)

    fetched_at = datetime.now(timezone.utc).isoformat()
    summary = render_summary(website_changes, video_changes, fetched_at)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = STAGING_DIR / f"review_summary_{timestamp}.md"
    summary_path.write_text(summary, encoding="utf-8")

    changed_count = sum(1 for c in website_changes if c.status != "unchanged") + len(video_changes)

    print(f"\n{summary}\n")
    print(f"Summary written to {summary_path}")
    if changed_count:
        PENDING_WEBSITE_PATH.write_text(json.dumps(new_website, ensure_ascii=False, indent=2), encoding="utf-8")
        PENDING_YOUTUBE_PATH.write_text(json.dumps(new_videos, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{changed_count} change(s) detected. Review the summary above, then run:")
        print("    python3 publish_content.py")
    else:
        print("\nNo changes detected — nothing to publish.")


if __name__ == "__main__":
    main()
