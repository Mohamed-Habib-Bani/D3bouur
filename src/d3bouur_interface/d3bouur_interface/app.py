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

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .contact_store import ContactStore
from .content import load_company_info, load_contact_info, load_training_programs, load_videos

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"
DATA_DIR = PACKAGE_ROOT / "data"

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
