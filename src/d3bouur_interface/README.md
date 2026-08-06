# d3bouur_interface — screen web interface (browsing mode)

FastAPI + server-rendered Jinja2 templates + plain CSS. This is the
catalog/events/videos/contact-form browsing mode of the screen — separate
from the face/conversation display mode (not built yet).

## Run it

```bash
pip3 install --user fastapi uvicorn python-multipart markdown
cd src/d3bouur_interface
python3 run_server.py
```

Then open **http://localhost:8000** in a browser.

If you're testing from Windows against this WSL2 machine and `localhost`
doesn't reach it (WSL2 usually forwards `localhost` automatically, but
occasionally doesn't depending on config), use the WSL2 machine's IP
instead — find it with `hostname -I` inside WSL — e.g. `http://172.x.x.x:8000`.

## Pages

| Route | Content |
|---|---|
| `/` | Company presentation — rendered from `d3bouur_conversation/knowledge/company_identite.md` |
| `/formations` | AcaJunior + AcaSenior — rendered from the corresponding `knowledge/*.md` files |
| `/evenements` | Placeholder — no real event data yet |
| `/videos` | All entries from `d3bouur_conversation/youtube_extract_draft.json`, newest first, linked to YouTube |
| `/contact` | Contact info (from `knowledge/contact.md`) + a form that POSTs to the same URL and saves to SQLite |

## Why these choices

- **Server-rendered Jinja2, not a JSON API + JS frontend** — this is a
  brochure-style site, not a dynamic app, and SSR is the lighter option for
  something that needs to run smoothly in kiosk mode on the Pi's screen
  (1024x600 target, see `static/style.css`).
- **Content read directly from `d3bouur_conversation/knowledge/*.md`**, not
  duplicated — one source of truth for what D3BOUUR knows/says, whether
  spoken or shown on screen.
- **SQLite for contact submissions** (`data/contacts.db`, gitignored) — no
  new dependency (stdlib `sqlite3`), matches the config-DB direction already
  flagged in the handoff doc. No email sending yet — that's a deliberate
  future step, submissions just need to not be lost in the meantime.
- **Plain HTML form POST for contact**, no JS — simplest, most robust for a
  skeleton; can add no-reload JS submission later without changing the
  backend route.

## Not done here (by design — this is a skeleton)

- No face/conversation display mode (this is the browsing mode only).
- No kiosk-mode launch config for the actual screen.
- No email notification on contact submissions.
- Events page has no real data source yet.
- Video list is the raw extraction, not curated/featured.
