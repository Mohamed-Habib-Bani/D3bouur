"""D3BOUUR screen web interface — FastAPI app.

This is the "browsing" mode of the screen (catalog / events / videos /
contact), separate from the face/conversation display mode mentioned in the
architecture doc's module map. Server-rendered Jinja2 templates rather than
a JSON API + JS frontend: this is a brochure-style, mostly-static site, not
a dynamic app, and server-side rendering is the lighter option to run
smoothly in kiosk mode on the Pi's screen.

templates/ and static/ live at the package root (sibling to this
d3bouur_interface/ subpackage), the same place d3bouur_conversation keeps
its knowledge/ directory — non-Python assets don't belong inside the
importable package.
"""

import sys
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .contact_store import ContactStore
from .content import (
    load_company_info,
    load_contact_info,
    load_training_programs,
    load_videos,
    page_url_for_source,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"
DATA_DIR = PACKAGE_ROOT / "data"

# d3bouur_conversation is a sibling package, not colcon-installed — same
# sys.path shim used by the demo/comparison scripts elsewhere in this
# project (e.g. d3bouur_behavior/demo_state_machine.py). Only needed for
# KnowledgeBase (RAG retrieval) and PiperTTS (speech synthesis); the catalog
# pages already read knowledge/*.md straight off disk in content.py without
# any Python import.
WORKSPACE_SRC = PACKAGE_ROOT.parent
sys.path.insert(0, str(WORKSPACE_SRC / "d3bouur_conversation"))

from d3bouur_conversation import KnowledgeBase, PiperTTS  # noqa: E402

NAV = [
    ("/", "Accueil"),
    ("/formations", "Formations"),
    ("/evenements", "Événements"),
    ("/videos", "Vidéos"),
    ("/contact", "Contact"),
]

app = FastAPI(title="D3BOUUR — Interface")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
contact_store = ContactStore(DATA_DIR / "contacts.db")
knowledge_base = KnowledgeBase()
piper_tts = PiperTTS()


def render(request: Request, template_name: str, **context):
    return templates.TemplateResponse(request=request, name=template_name, context={"nav": NAV, **context})


@app.get("/")
def index(request: Request):
    return render(request, "index.html", company_html=load_company_info())


@app.get("/formations")
def formations(request: Request):
    return render(request, "formations.html", programs=load_training_programs())


@app.get("/evenements")
def evenements(request: Request):
    return render(request, "evenements.html")


@app.get("/videos")
def videos(request: Request):
    return render(request, "videos.html", videos=load_videos())


@app.get("/contact")
def contact_get(request: Request, submitted: bool = False):
    return render(request, "contact.html", submitted=submitted, contact_html=load_contact_info())


@app.post("/contact")
def contact_post(name: str = Form(...), email: str = Form(...), message: str = Form(...)):
    contact_store.save(name=name.strip(), email=email.strip(), message=message.strip())
    return RedirectResponse(url="/contact?submitted=true", status_code=303)


# --- Kiosk face + screen-mode API -----------------------------------------
#
# /kiosk is deliberately not in NAV or extending base.html — it's a
# fullscreen standalone page (canvas + optional info-display iframe), not
# part of the browsable catalog site. The two POST endpoints below exist
# because there's no live STT/mic pipeline yet: they let the kiosk page's
# own test controls simulate "a visitor said X" (for RAG-triggered
# info-display mode) and "D3BOUUR is saying Y" (for real Piper audio to
# mouth-sync against) from a browser, same as every other hardware trigger
# simulated so far in this project.
#
# RAG_TRIGGER_MIN_SIMILARITY is higher than KnowledgeBase.search()'s own
# default (0.5, tuned for "is this worth including as LLM context" — a low-
# stakes decision since an irrelevant chunk just gets ignored by the model).
# Switching the whole screen is a more visible mistake, so this wants to be
# more conservative. Measured directly against this corpus (see commit
# message / chat log): real-topic queries scored 0.57-0.61 similarity,
# off-topic ones (weather, football scores, a pastry recipe) scored
# 0.50-0.57 — the two ranges OVERLAP. 0.55 trims the worst false positives
# without killing recall entirely, but this is NOT a clean separator with
# only 4 documents in the corpus.
#
# ACCEPTED AS A KNOWN LIMITATION for now, not blocking further work — this
# isn't a threshold-tuning problem, it's a "not enough content for the
# embedding space to separate topics" problem, and no amount of squinting
# at this one number fixes that. Revisit once the content pipeline
# (check_for_updates.py / publish_content.py) has grown knowledge/*.md
# past a handful of files — re-run the measurement in the chat log (or an
# equivalent script) against the bigger corpus before touching this number
# again; don't just nudge it further on vibes.
RAG_TRIGGER_MIN_SIMILARITY = 0.55


class SpeakRequest(BaseModel):
    text: str


class RagQueryRequest(BaseModel):
    text: str


@app.get("/kiosk")
def kiosk(request: Request):
    return templates.TemplateResponse(request=request, name="kiosk.html", context={})


@app.post("/api/speak")
def api_speak(payload: SpeakRequest):
    text = payload.text.strip()
    if not text:
        return Response(status_code=400, content="text must not be empty")
    wav_bytes = piper_tts.synthesize_bytes(text)
    return Response(content=wav_bytes, media_type="audio/wav")


@app.post("/api/rag-query")
def api_rag_query(payload: RagQueryRequest):
    text = payload.text.strip()
    if not text:
        return {"matched": False}

    results = knowledge_base.search(text, top_k=1, min_similarity=RAG_TRIGGER_MIN_SIMILARITY)
    if not results:
        return {"matched": False}

    top = results[0]
    page_url = page_url_for_source(top.source)
    return {
        "matched": page_url is not None,
        "source": top.source,
        "similarity": top.similarity,
        "page_url": page_url,
    }
