# d3bouur_interface

The FastAPI web app that runs on D3BOUUR's screen: a server-rendered kiosk
site (company info, training catalog, events, videos, contact form) plus a
separate fullscreen "face" mode that reacts to conversation/speech state.

## Status: **CONFIRMED WORKING** (locally, in a browser) — **NOT tested on the real Pi screen**

Verified by starting `run_server.py` and curling every route — all returned
HTTP 200:

`/`, `/formations`, `/evenements`, `/videos`, `/contact`, `/kiosk`,
`/api/rag-query`

Everything below has only ever been exercised in a regular desktop browser on
this dev machine. It has never run in kiosk mode on the robot's actual 10.1"
Waveshare touchscreen — layout, performance, and Piper audio playback on real
speaker hardware are all still open questions there.

## What it actually does

- **`/`, `/formations`, `/contact`** — real content: company info and the
  AcaJunior/AcaSenior training programs, sourced from the same
  `d3bouur_conversation/knowledge/*.md` files the conversation brain uses (via
  `content.py`, reading them straight off disk — no RAG/embedding involved for
  these pages, just Markdown rendering). The contact form (`POST /contact`)
  writes real submissions to a SQLite database (`data/contacts.db`).
- **`/kiosk`** — the animated face display (`static/face.js`, `static/kiosk.js`).
  A standalone fullscreen page, not part of the browsable catalog nav — reacts
  to robot state and mouths along with real synthesized speech.
  - `POST /api/speak` — synthesizes text via the real `PiperTTS` and returns
    WAV bytes for the browser to play + mouth-sync against.
  - `POST /api/rag-query` — the kiosk's "visitor asked a question" trigger.
    Runs the real `KnowledgeBase.search()` (same RAG index as
    `d3bouur_conversation`) and, on a match, tells the kiosk to switch to an
    `<iframe>` of the relevant catalog page.
  - Both endpoints exist only because there's no live STT/mic pipeline yet —
    the kiosk page's own debug controls simulate "a visitor said X" and
    "D3BOUUR is saying Y" from a browser, the same pattern used for every
    other not-yet-real hardware trigger in this project.

## Known gaps

- **`/evenements` is a placeholder** — no real data source wired in yet.
- **The video list is uncurated.** `/videos` reads directly from the raw
  YouTube extraction (`youtube_extract_draft.json`, ~40 entries) with no
  filtering — it mixes genuinely relevant AcaROBOTICS content with unrelated
  entries (e.g. podcast episodes) that haven't been reviewed for the catalog.
- **RAG-match confidence overlap directly affects `/api/rag-query`.** This is
  the actual place the limitation documented in
  [`d3bouur_conversation/README.md`](../d3bouur_conversation/README.md#known-limitations-accepted-not-yet-fixed)
  gets used — see that section for the real numbers and why it's not simply a
  threshold-tuning problem. `RAG_TRIGGER_MIN_SIMILARITY` here (0.55) is set
  higher than `KnowledgeBase.search()`'s own default (0.5) specifically
  because switching the whole screen is a more visible mistake than including
  an irrelevant chunk in an LLM prompt — but it's a mitigation, not a fix.
- **Everything here is browser-tested only** — never run in kiosk mode on the
  real screen, and every trigger (`/api/speak`, `/api/rag-query`) is still
  fired from a debug control, not real hardware/STT.

## Testing

```bash
cd src/d3bouur_interface
python3 run_server.py
# then, in another terminal:
curl http://localhost:8000/
curl http://localhost:8000/kiosk
curl -X POST http://localhost:8000/api/rag-query -H "Content-Type: application/json" -d '{"text": "quelles formations proposez-vous ?"}'
```

Needs `d3bouur_conversation`'s dependencies available (sibling package,
imported via `sys.path`, not colcon-installed) since this app loads a real
`KnowledgeBase` and `PiperTTS` at startup — see that package's README for
setup. No colcon build required to run the server directly.
