# D3BOUUR — How the pieces actually connect

The top-level `README.md` is an entry point: what each package is, and how to
build/run it in isolation. This document is different — it's the "how does
the robot actually work end to end" map: the real data/command flow between
packages, which of those connections are proven today versus still
simulated or stubbed, and which machine (dev PC vs. the robot's Pi) each
piece actually runs on.

**Read this alongside each package's own README** for testing details and
citations — this document only covers the *connections*, not each package's
internals.

## The intended full loop

```
 ultrasonic sensors                                    visitor speech (STT)
        │                                                      │
        ▼                                                      ▼
   Arduino (.ino)                                    [NOT BUILT — no STT yet]
   reads 6x HC-SR04                                            │
        │ D:d1,d2,d3,d4,d5,d6                                  │
        │ (serial, 9600 baud)                                  │
        ▼                                                      ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │                    d3bouur_behavior (state machine)              │
  │                                                                   │
  │   MOVING ──person_detected()──> PERSON_DETECTED ──> ENGAGING     │
  │                                       │                  │       │
  │                             _orient_toward_person()  visitor_said(text)
  │                                  [STUB — print only]       │       │
  └───────────────────────────────────────┼──────────────────┼───────┘
                                           │                  ▼
                                           │        d3bouur_conversation
                                           │        ConversationBrain.chat()
                                           │        (Ollama primary, RAG-backed)
                                           │                  │
                                           ▼                  ▼
                                  onvif_camera/engage.py   PiperTTS.speak()
                                  (built, not wired here)      │
                                  turns camera, detects face    ▼
                                  ENGAGED → trigger_head_servo()  d3bouur_interface
                                  [STUB — print only, should      /kiosk face
                                   eventually send Arduino          mouth-syncs to
                                   "S:angle" over serial]           the real audio
```

## Walking the real flow, hop by hop — what's real vs. simulated

| Hop | Real today? | Detail |
|---|---|---|
| Ultrasonic sensors → Arduino | **Real** | `d3bouur_arduino.ino`'s `readAndSendSensors()` reads all 6 HC-SR04s and emits `D:d1,d2,d3,d4,d5,d6` over serial. 3 of 6 sensors were showing `-1` (no reading) in the most recent test session — needs a physical connection check. |
| Arduino sensor data → anything that acts on it | **Not built** | Nothing currently reads the Arduino's `D:` sensor stream and turns it into a `person_detected()` call or an ultrasonic-supplied direction for `engage.py`. This is the single biggest missing wire in the whole loop. |
| "Person detected" → `d3bouur_behavior` state machine | **Simulated** | Today, only `demo_state_machine.py` calling `sm.person_detected()` directly — no real sensor or camera signal triggers it. |
| State machine → head/camera orientation | **Stub** | `_orient_toward_person()` in `state_machine.py` only logs; no real servo command is sent. |
| State machine → conversation brain | **Real** | `visitor_said(text)` calls the real `ConversationBrain.chat()` — confirmed via `demo_state_machine.py` against real, locally running Ollama. |
| Visitor speech → `text` in `visitor_said(text)` | **Not built (no STT)** | Every test so far has typed the visitor's words in by hand or via a fixed test script. `onvif_camera/mic.py` can pull real audio off the camera's RTSP stream, but nothing currently transcribes that audio and feeds it in here. |
| Conversation brain → RAG knowledge base | **Real** | `ConversationBrain._build_messages()` calls `KnowledgeBase.search()` every turn — confirmed via the 9-question verification (see `d3bouur_conversation/README.md`). |
| Conversation brain → TTS | **Real** | `demo_chat.py` synthesizes every real reply via `PiperTTS`, confirmed generating real audio files. Playback itself is unverified on this dev machine (no audio device) and not yet tested on the Pi's real speaker. |
| TTS/conversation → kiosk face | **Real, but only via a debug trigger** | `d3bouur_interface`'s `/api/speak` synthesizes real audio for the browser to mouth-sync against, and `/api/rag-query` runs the real `KnowledgeBase.search()` to switch the kiosk's screen — both proven working, but both are fired by the kiosk page's own debug controls, not by a live conversation turn actually happening. |
| Ultrasonic direction → camera orientation → face detection | **Built, not wired** | `onvif_camera/engage.py` implements exactly this (turn camera toward a target, run face-presence detection with a persistence timer, decide `ENGAGED`/`RETURN_NO_FACE`/`RETURN_TIMEOUT`) — tested standalone against the real camera via `example.py`'s demos, but nothing calls it with a real ultrasonic-supplied direction yet. |
| `engage.py` → head servo | **Stub, twice over** | `engage.py`'s own `trigger_head_servo()` only prints. Even if it didn't, there is currently no code path from `onvif_camera/` (which only talks to the WiFi camera over ONVIF/RTSP) to the Arduino serial connection (which is what `d3bouur_behavior` would need to actually move the physical head servo via `S:angle`) — these are two separate packages that have never called each other. |
| HC-05 Bluetooth manual control | **Real, independent path** | `F`/`B`/`L`/`R`/`S` single-character commands drive the robot directly from a paired Bluetooth device, entirely bypassing the Pi and every package above — a separate, already-working manual-override path, not part of the autonomous loop this table otherwise describes. |

**In short**: every individual segment of the loop that can be tested without
new hardware wiring has been tested and works. The parts that don't yet work
are specifically the connective tissue between segments — sensor data into a
trigger, camera vision into a servo command, speech audio into text — each
of which was deliberately built as a clean, swappable function call (per
`state_machine.py`'s own design notes) specifically so this wiring can be a
later, focused step rather than a redesign.

## What runs where — Pi vs. dev machine

| Runs on | What |
|---|---|
| **Dev machine only, today** | Everything. All packages here have only ever been run/tested on this WSL2 dev machine — none have been deployed to or tested on the Pi yet. |
| **The robot's Raspberry Pi 5** (Debian, ROS 2 via Docker — see top-level README) | Where all of this is *meant* to eventually run for a live demo: `d3bouur_interface` (drives the real screen), `onvif_camera` (needs to be on the same network as the camera), the eventual ROS 2 node wrapping the behavior state machine, and whatever reads the Arduino's serial port. |
| **The Arduino UNO** (separate microcontroller, not "the Pi") | `d3bouur_arduino.ino` — flashed directly via the Arduino IDE, not part of any colcon build or Docker container. Talks to the Pi over USB serial at 9600 baud, and independently to a paired Bluetooth device via the HC-05 module on the same `Serial` object (the firmware can't tell which source a line came from — it doesn't need to). |
| **The camera itself** | Runs its own firmware; `onvif_camera/` only talks to it remotely over WiFi (ONVIF for PTZ, RTSP for video/audio) — no code from this repo runs on the camera. |
| **Could run on either** | `d3bouur_conversation` (Ollama can run locally on either machine — the Pi's CPU-only inference speed for this has not yet been measured; all latency numbers documented so far are from the dev machine). |

The practical implication: **nothing in this project has been proven to work
on the actual robot yet.** Every "confirmed working" claim across every
package README is confirmed on this dev machine, against real backends
(Ollama, the real V380 Pro camera over WiFi) where noted — but not on Pi
hardware, and not through the full loop end to end. Getting one clean
person-detected → conversation → servo-turn cycle running for real, on the
Pi, is the actual integration milestone every package here is currently
building toward.
