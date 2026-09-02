# D3BOUUR — Consolidated Testing Checklist

One ordered checklist across every package, grouped by what hardware access
each group needs. This document doesn't duplicate any package's own test
commands — each item links to the specific README section that has them.
Use this to know **what to run, in what order, and what you need on hand**
to run it; use the package READMEs for the actual commands and to interpret
the results.

Order matters within each group: later items depend on earlier ones passing
first (e.g. the state machine's demo builds a real `ConversationBrain`, so
there's no point running it before the conversation brain itself is
confirmed working).

---

## Group 1 — Dev machine only (no Pi, no camera, no Arduino, no HC-05)

Anyone can run this whole group on a laptop. Do these in order.

- [ ] **Start Ollama locally** and confirm it's reachable
  (`http://localhost:11434`) — every item below except `d3bouur_description`
  and the `onvif_camera` import check depends on this being up first.
- [ ] **`d3bouur_description`** — model parses and validates. No dependency
  on Ollama or anything else; safe to run any time.
  → [`src/d3bouur_description/README.md`](../src/d3bouur_description/README.md#testing)
- [ ] **`onvif_camera` import/syntax check** — proves the code is
  well-formed with no camera attached. No dependency on Ollama; safe to run
  any time.
  → [`src/onvif_camera/README.md`](../src/onvif_camera/README.md#testing)
- [ ] **`d3bouur_conversation` — build the RAG index**
  (`build_index.py`) — needs Ollama's `nomic-embed-text` embedding model
  pulled and running. Do this before the conversation demo below, since an
  unbuilt index just silently tests the "empty knowledge base" path instead
  of the real RAG behavior.
  → [`src/d3bouur_conversation/README.md`](../src/d3bouur_conversation/README.md#2-rag-knowledge-base-knowledge_basepy--knowledgebase)
- [ ] **`d3bouur_conversation` — conversation brain + TTS**
  (`demo_chat.py`) — needs Ollama's chat model (`llama3.2:3b`) and the index
  built above. Confirms LLM routing, RAG retrieval, and Piper TTS synthesis
  together.
  → [`src/d3bouur_conversation/README.md`](../src/d3bouur_conversation/README.md#testing)
- [ ] **`d3bouur_behavior` — state machine demo** (`demo_state_machine.py`)
  — depends on the conversation brain above working, since it builds a real
  `ConversationBrain` internally rather than a stub.
  → [`src/d3bouur_behavior/README.md`](../src/d3bouur_behavior/README.md#testing)
- [ ] **`d3bouur_interface` — kiosk web app** (`run_server.py`) — depends on
  the RAG index (above) and Piper model being in place, since the app loads
  a real `KnowledgeBase` and `PiperTTS` at startup and will fail to start
  otherwise.
  → [`src/d3bouur_interface/README.md`](../src/d3bouur_interface/README.md#testing)

---

## Group 2 — Requires the real Pi (no camera, no Arduino, no HC-05)

- [ ] Repeat Group 1's `d3bouur_conversation` and `d3bouur_behavior` demos
  **on the Pi itself**, inside the ROS 2 Docker container — this is the one
  measurement flagged as missing in `ARCHITECTURE.md`: Ollama's real
  CPU-only inference speed on the Pi has never been measured, only on the
  dev machine.
  → [top-level README](../README.md#2-the-robots-raspberry-pi-debian--ros-2-runs-in-docker-not-sourced-directly) for how to get ROS 2 running there at all.
- [ ] Run `d3bouur_interface` on the Pi in actual kiosk mode, on the real
  10.1" Waveshare screen — never done yet; only browser-tested on the dev
  machine so far.
  → [`src/d3bouur_interface/README.md`](../src/d3bouur_interface/README.md)

---

## Group 3 — Requires the Pi + Arduino (USB serial link)

**Read the safety precautions in `docs/D3BOUUR_Phase2_Power_System.md` before
any motor test** — the motor branch is still unfused by deliberate decision,
with mandatory manual precautions (continuity check every session, one motor
at a time first, stay present with a hand on the switch).

- [ ] Flash/verify `d3bouur_arduino.ino` is on the board.
  → [`src/d3bouur_arduino/README.md`](../src/d3bouur_arduino/README.md)
- [ ] Confirm the serial link at 9600 baud, and exercise the `M:`/`S:`/`X`
  protocol (motors, head servo, stop) from the Pi side.
  → [`src/d3bouur_arduino/README.md`](../src/d3bouur_arduino/README.md)
- [ ] Confirm all 6 ultrasonic sensors read real distances via the `D:`
  stream — per `ARCHITECTURE.md`, 3 of 6 were showing `-1` (no reading) in
  the most recent session and need a physical connection check.
  → [`src/d3bouur_arduino/README.md`](../src/d3bouur_arduino/README.md)

---

## Group 4 — Requires the Pi + Arduino + HC-05

- [ ] Confirm the HC-05 Bluetooth manual-control path (`F`/`B`/`L`/`R`/`S`
  single-character commands) drives the robot independently of the Pi —
  this is a separate manual-override path, not part of the autonomous loop
  in `ARCHITECTURE.md`.
  → [`src/d3bouur_arduino/README.md`](../src/d3bouur_arduino/README.md)

---

## Group 5 — Requires the Pi + camera (real V380 Pro, same network)

- [ ] Run every `example.py` demo against the real camera (PTZ movement,
  `home()`, `find_level_tilt()`, microphone recording, room sweep +
  panorama, room sweep + object detection, face-presence engagement) — see
  the onvif_camera README's status section for exactly which of these were
  last confirmed working and when.
  → [`src/onvif_camera/README.md`](../src/onvif_camera/README.md#what-each-file-does)
- [ ] The live WiFi-drop test — physically disconnect the camera or the Pi
  mid-move / mid-record and confirm `ptz.py`/`mic.py`'s retry/reconnect
  logic actually recovers. Explicitly **not yet done**, per the
  onvif_camera README.
  → [`src/onvif_camera/README.md`](../src/onvif_camera/README.md#reliability-hardening--done-the-live-drop-test--not-done)

---

## Group 6 — The full loop (Pi + camera + Arduino together)

The actual integration milestone the whole project is building toward, per
`ARCHITECTURE.md`'s closing line: **one clean person-detected → conversation
→ servo-turn cycle, running for real, on the Pi.** Not achievable until
every wiring gap `ARCHITECTURE.md` lists is closed — this checklist item is
here so it's tracked as one explicit goal rather than left implicit.

- [ ] A real ultrasonic reading (Group 3) triggers `d3bouur_behavior`'s
  `person_detected()` — currently only simulated by a test script calling it
  directly.
- [ ] `_orient_toward_person()` calls `onvif_camera/engage.py`'s real
  engagement logic (Group 5) instead of its current stub print.
- [ ] `engage.py` reaching `ENGAGED` sends a real Arduino `S:angle` command
  (Group 3) instead of `trigger_head_servo()`'s current stub print.
- [ ] Real visitor speech (still no STT anywhere in the project) feeds
  `visitor_said(text)` instead of typed/scripted text.
- [ ] With all of the above wired: **one full cycle** — a person approaches,
  the robot notices, turns to face them, has a real conversation via Ollama
  + RAG, speaks the reply through Piper on real speaker hardware, and
  returns to `MOVING` on Natural End or Timeout — completes without manual
  intervention at any step.

Until every box above is checked, "the robot works" means each piece works
**on its own** — not that the robot has ever done this loop for real.
