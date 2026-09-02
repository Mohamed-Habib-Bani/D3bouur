# d3bouur_conversation

D3BOUUR's "brain": takes a visitor's message, decides what to say back, says
it as speech, and — separately — a pipeline for keeping what it knows about
AcaROBOTICS up to date.

## Status: **CONFIRMED WORKING** (with named limitations, below)

Verified by running `demo_chat.py` interactively and via the state machine's
`demo_state_machine.py` (see `d3bouur_behavior/README.md`), both against a
real, locally running Ollama, with the real RAG knowledge base loaded. Piper
TTS is confirmed generating real audio (`spoken_replies/*.wav`); playback
itself is unverified on this dev machine (no audio output device — see
[TTS](#4-tts--tts) below), not yet tested on the Pi's real speaker hardware.

**What's NOT yet wired:** no live STT anywhere — every test so far has typed
the visitor's words in as text. This module doesn't know or care where the
text came from, so wiring in real STT output later needs zero changes here.

## What each piece does

### 1. LLM routing (`llm_router.py` — `ConversationBrain`)

Sends each conversation turn to an LLM and manages fallback between two
providers:

- **Primary: local Ollama** (`llama3.2:3b`, default).
- **Secondary: OpenRouter** (cloud, free-tier models) — tried opportunistically
  only if Ollama fails.

**Why Ollama is primary, not OpenRouter** (this was reversed from the
original design): live testing of three different OpenRouter free models
against the real RAG setup found each one unreliable in a distinct way:

| Model | Failure found |
|---|---|
| `openai/gpt-oss-20b:free` | Garbled/corrupted output on ~half of longer responses, and on 2 of 3 trials **confidently fabricated a fake phone number and email domain** even with the real ones correctly retrieved and present in its prompt context. |
| `google/gemma-4-31b-it:free` | Mostly unusable — hit a shared free-tier quota pool on Google's backend (`limit_source: upstream_provider_shared_pool`). |
| `nvidia/nemotron-3-super-120b-a12b:free` | Leaked its own internal reasoning trace as the visible answer (e.g. *"Okay, the user is asking me to tell them more... Let me check the knowledge base..."*) — coherent English, so no content-based check would catch it, but nonsense to read aloud to a visitor. Also heavily rate-limited. |

Local Ollama, across all of this testing, was available every single time
and correct all but once. `LLMConfig.primary_provider` now defaults to
`"ollama"`; flip it back to `"openrouter"` if free-tier reliability ever
improves enough to revisit. Two providers are still kept (not just Ollama
alone) so a live demo survives either path being down — the same
"don't depend on one thing" principle as the robot's offline-first Wi-Fi
design, one layer up (making the *internet* dependency optional, not just
the local network one).

Also handles: conversation history (last 3 exchanges, trimmed in pairs so no
orphaned turns), mid-sentence truncation recovery (trims cleanly to the last
full sentence instead of cutting mid-word when `max_tokens` is hit — this
output is TTS-bound, so a chopped word is worse than a shorter answer), and
garbled-output detection (rejects any character outside expected French/Latin
typography — a single stray CJK/Cyrillic glyph fails the check, since even
one breaks a TTS read).

### 2. RAG knowledge base (`knowledge_base.py` — `KnowledgeBase`)

Local retrieval-augmented generation, and the actual fix for LLM hallucination
(see [How the RAG safety mechanism works](#how-the-rag-safety-mechanism-works)
below) — not just a "nicer answers" feature.

- Embeds text via Ollama's `nomic-embed-text` model (kept local — same
  offline-capability reasoning as the LLM routing above).
- Brute-force cosine similarity over an in-memory list, persisted as plain
  JSON (`knowledge_index.json`) — deliberately not a real vector database.
  At this scale (4 documents today, tens-to-low-hundreds ceiling for a single
  organization's own content) a vector DB would be infrastructure with
  nothing to justify it.
- An empty index is a valid, fully-supported state — `search()` just returns
  no results.

Rebuild the index after editing anything in `knowledge/`:

```bash
cd src/d3bouur_conversation
python3 build_index.py
```

### 3. Content pipeline (`content_pipeline/`, `check_for_updates.py`, `publish_content.py`)

Scheduled fetch-and-diff for the AcaROBOTICS website and YouTube channel, with
a mandatory human review gate before anything is accepted — see
`content_pipeline/README.md` for the full workflow and why the review step
is non-negotiable (it's what originally caught a WordPress demo "Courses"
page full of placeholder categories that was never real AcaROBOTICS content).
Deliberately does **not** touch `knowledge/*.md` or rebuild the RAG index —
turning reviewed draft content into what D3BOUUR actually says out loud stays
a separate, manual step.

### 4. TTS (`tts.py` — `PiperTTS`)

Piper (`fr_FR-siwis-medium` voice, `models/piper/` at the workspace root — see
that folder's README to download it) — chosen over espeak-ng after a listening
comparison (`scripts/tts_comparison/`, real result file included), clearly
more natural at the cost of being ~50x slower to generate. The voice is
loaded once and reused across calls (unlike the comparison script, which
reloads per call to keep espeak-ng's timing fair — a live conversation can't
afford that reload cost on every reply).

## How the RAG safety mechanism works

The core hallucination fix, found directly during LLM comparison testing
(`scripts/llm_comparison/`): with no real facts to draw on, **both** Ollama
and Groq confidently invented specific, wrong answers (a fake toilet
location, an invented school-visit date) instead of saying "I don't know."

RAG closes this by injecting an explicit fact statement into every turn's
prompt, not just "try to answer" — `_format_rag_context()` in `llm_router.py`:

- **If relevant chunks are found** (similarity ≥ 0.5, top 3): they're inserted
  verbatim with an instruction to use them if relevant and *"invent nothing
  not present above."*
- **If nothing is found**: the model is explicitly told no information exists
  in the knowledge base, and instructed to say so and offer to redirect to a
  team member — rather than leaving it to infer that from silence.

This is why an **empty knowledge base is a safe default**, not a degraded
one: it turns every query into the "nothing found, redirect" case, which is
exactly the safe behavior — closing the fabrication bug far more reliably
than a general "don't guess" instruction in the persona alone did.

## Real test results

**9-question full-pipeline verification** (after the knowledge base was
built out with company identity, AcaJunior/AcaSenior programs, and contact
info): covered every fact in the knowledge base plus the original "tell me
more" fabrication bug and a NextGen-event-date safety check (the knowledge
file explicitly withholds specific dates since source content was
potentially stale, and the model must not invent one). **All 9 passed** —
correct answers, zero fabrication, and Ollama (primary) succeeded on every
single call with no fallback needed.

## Known limitations (accepted, not yet fixed)

- **Markdown sometimes slips through.** One answer in the 9-question run
  included markdown bullets (`*`) despite the persona's plain-text
  instruction — content was accurate, formatting wasn't fully obeyed. Not
  fixed at the source; the plan is to defensively strip markdown at the
  eventual TTS integration point rather than relying on the model to never
  produce it.
- **RAG-match confidence overlap.** `d3bouur_interface`'s kiosk uses this
  same `KnowledgeBase.search()` to decide whether a visitor's typed question
  is "real" enough to switch the screen. Measured directly: real-topic and
  off-topic questions land in the *same* similarity range (0.50–0.61 both
  ways) at this knowledge-base size — e.g. an off-topic football-score
  question scored *higher* than a genuine training-program question. Raising
  the threshold (0.55, in `d3bouur_interface/app.py`) trims the worst false
  positives but doesn't cleanly separate the two — this needs a bigger
  knowledge base (the content pipeline above is the path to that) or a
  smarter relevance check, not more threshold tuning. Reproduced again
  during the most recent project audit: a live "formations" query returned
  `matched: false`.
- **Reasoning-trace leak is a known OpenRouter-secondary failure mode**, not
  something this code detects or filters — `nvidia/nemotron-3-super-120b-a12b:free`
  leaked internal reasoning as its visible answer during testing (see table
  above). Coherent, on-topic-looking text that happens to be the model
  thinking out loud isn't something the garbled-output or empty-content
  checks in `llm_router.py` are designed to catch, since nothing about it
  looks broken. Currently only avoided by Ollama being primary and reliable
  enough that the secondary rarely gets used at all.

## Testing

```bash
cd src/d3bouur_conversation

# Interactive manual test — type messages, see provider/latency per reply,
# hear (or find saved) the TTS output. Needs Ollama running locally.
python3 demo_chat.py

# Rebuild the RAG index after editing knowledge/*.md
python3 build_index.py

# Content pipeline (fetch + review-gated publish) — see content_pipeline/README.md
python3 check_for_updates.py
python3 publish_content.py
```

No colcon build is required for the demos — they import the package
directly. `colcon build` matters once this is wrapped into a ROS 2 node.
