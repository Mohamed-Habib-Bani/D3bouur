"""Diffing + human-readable review summary for the content pipeline.

Comparing a newly fetched snapshot against the currently *published* draft
files (website_extract_draft.json, youtube_extract_draft.json) — those
files already represent "what a human has last reviewed and accepted", so
there's no separate hidden snapshot store to keep in sync with reality.
"""

import difflib
from dataclasses import dataclass, field

PLACEHOLDER_WATCH_KEYS = {"courses"}


@dataclass
class PageChange:
    key: str
    status: str  # "new", "changed", "unchanged", "removed"
    diff_lines: list = field(default_factory=list)


@dataclass
class VideoChange:
    status: str  # "new" or "changed"
    video_id: str
    title: str
    detail: str = ""


def diff_website(old: dict, new: dict) -> list[PageChange]:
    changes = []
    for key in sorted(set(old) | set(new)):
        new_entry = new.get(key)
        if new_entry is None:
            changes.append(PageChange(key, "removed"))
            continue

        new_text = new_entry["text"]
        if key not in old:
            changes.append(PageChange(key, "new", new_text.splitlines()))
            continue

        old_text = old[key]["text"]
        if old_text == new_text:
            changes.append(PageChange(key, "unchanged"))
            continue

        diff_lines = list(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile="published",
                tofile="fetched",
                lineterm="",
            )
        )
        changes.append(PageChange(key, "changed", diff_lines))
    return changes


def diff_youtube(old_videos: list, new_videos: list) -> list[VideoChange]:
    old_by_id = {v["video_id"]: v for v in old_videos}
    changes = []
    for v in new_videos:
        old = old_by_id.get(v["video_id"])
        if old is None:
            changes.append(VideoChange("new", v["video_id"], v["title"]))
        elif old["title"] != v["title"] or old["description"] != v["description"]:
            changes.append(
                VideoChange("changed", v["video_id"], v["title"], detail="title or description edited")
            )
    return changes


def render_summary(website_changes: list[PageChange], video_changes: list[VideoChange], fetched_at: str) -> str:
    lines = [f"# D3BOUUR content review — fetched {fetched_at}", ""]

    real_website_changes = [c for c in website_changes if c.status != "unchanged"]
    lines.append("## Website")
    if not real_website_changes:
        lines.append("No changes detected on any tracked page.")
    else:
        for c in real_website_changes:
            lines.append(f"\n### `{c.key}` — {c.status.upper()}")
            if c.status == "removed":
                lines.append("No longer found via homepage navigation discovery — may have moved or been removed.")
            elif c.status == "new":
                lines.append("```")
                lines.extend(c.diff_lines[:30])
                if len(c.diff_lines) > 30:
                    lines.append(f"... ({len(c.diff_lines) - 30} more lines)")
                lines.append("```")
            elif c.status == "changed":
                lines.append("```diff")
                lines.extend(c.diff_lines)
                lines.append("```")
                if c.key in PLACEHOLDER_WATCH_KEYS:
                    lines.append(
                        "\n**Note:** this page (`/ourcourses/`) was previously identified as WordPress LMS "
                        "demo content, not real AcaROBOTICS courses (see docs/D3BOUUR_Project_Handoff.md §16). "
                        "It changed — check carefully whether it's now real content before treating anything "
                        "here as fact."
                    )
    lines.append("")

    lines.append("## YouTube")
    if not video_changes:
        lines.append("No new or changed videos detected.")
    else:
        new_videos = [c for c in video_changes if c.status == "new"]
        changed_videos = [c for c in video_changes if c.status == "changed"]
        if new_videos:
            lines.append(f"\n**{len(new_videos)} new video(s):**")
            for c in new_videos:
                lines.append(f"- {c.title} (`{c.video_id}`)")
        if changed_videos:
            lines.append(f"\n**{len(changed_videos)} changed video(s):**")
            for c in changed_videos:
                lines.append(f"- {c.title} (`{c.video_id}`) — {c.detail}")

    return "\n".join(lines)
