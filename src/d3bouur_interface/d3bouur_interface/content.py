"""Content loading for the browsing interface.

Reuses the real content already gathered for the conversation brain's RAG
knowledge base (d3bouur_conversation/knowledge/*.md) instead of duplicating
it here — one source of truth for what D3BOUUR knows and says about
AcaROBOTICS, whether spoken or shown on screen. Read directly from that
package's directory on disk; no import of d3bouur_conversation's Python
code is needed, just its knowledge/ files, so this package stays decoupled
from that one at the code level.

Videos come from youtube_extract_draft.json, the same raw extraction used
to seed the knowledge base (see d3bouur_conversation/fetch_youtube_content.py)
— shown as-is (title + link), not curated, since picking which videos are
"featured" is an editorial decision for later, not part of this skeleton.
"""

import json
import logging
from pathlib import Path
from typing import NamedTuple

import markdown as markdown_lib

logger = logging.getLogger(__name__)

_WORKSPACE_SRC = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = _WORKSPACE_SRC / "d3bouur_conversation" / "knowledge"
YOUTUBE_DRAFT_PATH = _WORKSPACE_SRC / "d3bouur_conversation" / "youtube_extract_draft.json"


class TrainingProgram(NamedTuple):
    slug: str
    title: str
    html: str


class Video(NamedTuple):
    title: str
    url: str
    published_at: str


def _render_markdown_file(path: Path) -> str:
    if not path.exists():
        logger.warning("content file not found: %s", path)
        return "<p><em>Contenu indisponible pour le moment.</em></p>"
    return markdown_lib.markdown(path.read_text(encoding="utf-8"), extensions=["nl2br"])


def load_company_info() -> str:
    return _render_markdown_file(KNOWLEDGE_DIR / "company_identite.md")


def load_contact_info() -> str:
    return _render_markdown_file(KNOWLEDGE_DIR / "contact.md")


def load_training_programs() -> list[TrainingProgram]:
    return [
        TrainingProgram(
            "acajunior", "AcaJunior", _render_markdown_file(KNOWLEDGE_DIR / "programme_acajunior.md")
        ),
        TrainingProgram(
            "acasenior", "AcaSenior", _render_markdown_file(KNOWLEDGE_DIR / "programme_acasenior.md")
        ),
    ]


# Maps a knowledge base source filename (RetrievedChunk.source, from
# d3bouur_conversation's RAG search) to the catalog page that covers that
# same content — used by the kiosk's info-display mode to show the right
# page when a visitor's question gets a real RAG match. Kept as an explicit
# table rather than inferred from the filename, since the mapping is a
# content decision, not a mechanical one.
SOURCE_TO_PAGE = {
    "company_identite.md": "/",
    "programme_acajunior.md": "/formations#acajunior",
    "programme_acasenior.md": "/formations#acasenior",
    "contact.md": "/contact",
}


def page_url_for_source(source: str) -> str | None:
    return SOURCE_TO_PAGE.get(source)


def load_videos() -> list[Video]:
    if not YOUTUBE_DRAFT_PATH.exists():
        logger.warning("youtube extract not found: %s", YOUTUBE_DRAFT_PATH)
        return []
    try:
        entries = json.loads(YOUTUBE_DRAFT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("could not parse %s", YOUTUBE_DRAFT_PATH)
        return []

    videos = [
        Video(
            title=entry["title"],
            url=f"https://www.youtube.com/watch?v={entry['video_id']}",
            published_at=entry.get("published_at", ""),
        )
        for entry in entries
    ]
    videos.sort(key=lambda v: v.published_at, reverse=True)
    return videos
