"""Fetches known AcaROBOTICS site pages and extracts their visible text.

Page URLs are discovered from the homepage's own navigation links (matched
by URL slug), not hardcoded — resilient to the site restructuring its menu,
and avoids guessing URLs that might not exist. Falls back to the
last-confirmed URL (verified reachable 2026-08-06) if discovery can't find
a page, and logs clearly when that happens rather than failing silently.

"courses" (/ourcourses/) is tracked deliberately: docs/D3BOUUR_Project_
Handoff.md §16 identifies this page as WordPress LMS demo content, not real
AcaROBOTICS courses, as of the original content review. If it ever changes,
that's exactly the kind of thing this pipeline exists to surface for
review, not to silently accept — see diffing.py's special-case note for it.
"""

import logging
import re
from typing import NamedTuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://acaroboticsplatform.com"
USER_AGENT = "Mozilla/5.0 (compatible; D3BOUUR-ContentBot/1.0)"
REQUEST_TIMEOUT = 15

PAGE_SPECS = {
    "accueil": {
        "slug_pattern": re.compile(r"^/?$"),
        "fallback": f"{BASE_URL}/",
    },
    "acajunior": {
        "slug_pattern": re.compile(r"acarobotics-junior", re.I),
        "fallback": f"{BASE_URL}/acarobotics-junior/",
    },
    "acasenior": {
        "slug_pattern": re.compile(r"acarobotics-senior", re.I),
        "fallback": f"{BASE_URL}/acarobotics-senior/",
    },
    "contact": {
        "slug_pattern": re.compile(r"^/contacts?/?$", re.I),
        "fallback": f"{BASE_URL}/contacts/",
    },
    "courses": {
        "slug_pattern": re.compile(r"ourcourses", re.I),
        "fallback": f"{BASE_URL}/ourcourses/",
    },
}


class PageResult(NamedTuple):
    url: str
    text: str


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup.find(id="content") or soup.body
    if main is None:
        return ""
    for tag in main.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    lines = [line.strip() for line in main.get_text(separator="\n").splitlines()]
    return "\n".join(line for line in lines if line)


def discover_page_urls() -> dict[str, str]:
    resp = requests.get(BASE_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    discovered: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if BASE_URL not in href:
            continue
        path = href[len(BASE_URL):]
        for key, spec in PAGE_SPECS.items():
            if key not in discovered and spec["slug_pattern"].search(path):
                discovered[key] = href

    urls = {}
    for key, spec in PAGE_SPECS.items():
        if key in discovered:
            urls[key] = discovered[key]
        else:
            logger.warning(
                "could not discover URL for %r via homepage nav links — using last-known fallback %s",
                key,
                spec["fallback"],
            )
            urls[key] = spec["fallback"]
    return urls


def fetch_pages() -> dict[str, dict]:
    """Returns {page_key: {"url": ..., "text": ...}}, JSON-serializable."""
    urls = discover_page_urls()
    pages: dict[str, dict] = {}
    for key, url in urls.items():
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("failed to fetch %r (%s): %s", key, url, exc)
            continue
        pages[key] = {"url": url, "text": _extract_text(resp.text)}
    return pages
