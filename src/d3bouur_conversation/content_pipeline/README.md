# Content pipeline — scheduled fetch with a review gate

Checks the AcaROBOTICS website and YouTube channel for new or changed
content, stages it separately from the live knowledge base, and produces a
plain-language summary for review before anything is accepted. Built after
a real incident: the original manual content review caught a WordPress
"Courses" page full of generic demo categories (Business, Finance,
JavaScript, PHP...) that was never real AcaROBOTICS content (see
`docs/D3BOUUR_Project_Handoff.md` §16). Automating the fetch without
keeping that review step would risk exactly that slipping through
unnoticed.

## Workflow

```bash
cd src/d3bouur_conversation
python3 check_for_updates.py   # fetch + diff + write a review summary
# ... read staging/review_summary_<timestamp>.md ...
python3 publish_content.py     # accept it as the new baseline
```

`check_for_updates.py` only writes to `staging/` (gitignored) — it never
touches anything else. `publish_content.py` only updates
`website_extract_draft.json` and `youtube_extract_draft.json` — the same
"raw draft, human-reviewed but not yet curated" role `youtube_extract_draft.json`
already had before this existed. **It does not touch `knowledge/*.md` or
rebuild the RAG index.** Turning reviewed draft content into what D3BOUUR
actually says out loud stays a separate, deliberate step — that's the
judgment call that caught the fake courses page, and it's the one thing
this pipeline deliberately does not automate.

## Scheduling it weekly

This only makes sense running somewhere always-on — on this WSL2 dev
machine, a cron job wouldn't fire reliably since the machine isn't always
running. Once deployed on the Pi 5, add to crontab (`crontab -e`):

```cron
0 6 * * 1 cd /path/to/ros2_ws/src/d3bouur_conversation && /usr/bin/python3 check_for_updates.py >> staging/cron.log 2>&1
```

Runs every Monday at 06:00. It still only stages + summarizes — publishing
stays a manual step you run after reading the summary, on the Pi or
remotely.

## How page discovery works

`website_fetch.py` doesn't hardcode page URLs — it fetches the homepage and
finds the real links for AcaJunior/AcaSenior/Contact/Courses by matching
URL slugs in the nav, falling back to the last-confirmed URL (verified
2026-08-06) only if a link can't be found. This is more resilient to the
site's menu changing than hardcoded paths, and avoids guessing URLs that
might not exist.

The `/ourcourses/` page — the one previously found to be WordPress demo
content — is deliberately still tracked. If it's ever replaced with real
courses, that shows up as a flagged "changed" page with an explicit note in
the review summary, not a silent update.
