#!/usr/bin/env python3
"""Promote the most recently staged content check into the published draft
files (website_extract_draft.json, youtube_extract_draft.json).

Run from this directory, after reading the latest staging/review_summary_*.md:
    python3 publish_content.py

This does NOT touch knowledge/*.md or rebuild the RAG index — turning
reviewed draft content into what D3BOUUR actually says out loud stays a
separate, deliberate step (same as it's always been for the YouTube draft;
see docs/D3BOUUR_Project_Handoff.md §16 for why that separation matters —
it's what caught real WordPress demo content masquerading as AcaROBOTICS
courses). This command only updates the "reviewed and accepted as current"
baseline that the next check_for_updates.py run diffs against.
"""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
STAGING_DIR = PACKAGE_ROOT / "staging"
WEBSITE_DRAFT_PATH = PACKAGE_ROOT / "website_extract_draft.json"
YOUTUBE_DRAFT_PATH = PACKAGE_ROOT / "youtube_extract_draft.json"
PENDING_WEBSITE_PATH = STAGING_DIR / "pending_website_extract.json"
PENDING_YOUTUBE_PATH = STAGING_DIR / "pending_youtube_extract.json"


def main() -> None:
    if not PENDING_WEBSITE_PATH.exists() or not PENDING_YOUTUBE_PATH.exists():
        print("Nothing staged to publish — run check_for_updates.py first.", file=sys.stderr)
        sys.exit(1)

    WEBSITE_DRAFT_PATH.write_text(PENDING_WEBSITE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    YOUTUBE_DRAFT_PATH.write_text(PENDING_YOUTUBE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    PENDING_WEBSITE_PATH.unlink()
    PENDING_YOUTUBE_PATH.unlink()

    print(f"Published. {WEBSITE_DRAFT_PATH.name} and {YOUTUBE_DRAFT_PATH.name} updated.")
    print(
        "Reminder: knowledge/*.md was NOT touched — update it by hand "
        "(or ask for help turning this into clean content) if this changes what D3BOUUR should say."
    )


if __name__ == "__main__":
    main()
