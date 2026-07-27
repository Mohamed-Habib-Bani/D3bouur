# D3BOUUR — Complete Project Handoff Document

*Last updated: current as of this session. This document assumes no prior context — everything decided about this project is captured here.*

---

## 0. How This Project Is Worked On (read this first)

This section captures *how* the work has been done, not just *what* was decided — important for anyone continuing this project to keep the same approach.

### Working style requested by the project owner
- **Go slow, one step at a time.** Don't jump ahead or batch multiple steps together — confirm each step works before moving to the next.
- **Explain everything in detail at every step**: what we're doing, why, how to actually do it, and specifically:
  - What the alternative options were, and why this one was chosen over them
  - What real engineers/professionals/hobbyists typically use for this exact problem, so the choice can be judged against real-world practice, not just "what worked"
- **This is explicitly a learning project**, not just "get it working." The goal is for the project owner to genuinely understand ROS 2, robotics, and the full stack by the end — not just end up with a working robot they can't explain.
- **Solo builder, wants to learn to a professional standard** — earlier in the project, explicitly asked to be set up "the way every professional does it," not simplified for being a first-timer (this is why native Ubuntu/dual-boot was initially recommended over WSL2, before WSL2 was confirmed sufficient and adopted instead — see Section 7).

### Decision-making methodology used throughout
- **Never assume — ask clarifying questions before big decisions**, using concrete options rather than open-ended questions where possible.
- **Verify hardware claims physically** (photos of components, multimeter readings, labels) rather than assuming specs — this caught several real issues before they became mistakes (e.g. the battery's actual voltage configuration, the HW-130 being a shield not a separate board, the screen's true power connector type).
- **Safety-first on anything irreversible or hardware-related**: stopped and asked clarifying questions before any BIOS changes, before any soldering/wiring, before any destructive commands (e.g. confirmed explicitly before deleting the SD card contents, before touching partition tables during the dual-boot discussion).
- **Test/compare before committing to a tool choice** where a decision was genuinely close (e.g. planned LLM comparison test between Ollama, Google Gemini free tier, and Groq — not yet executed, deferred to when the conversation module is actually being built, per the project owner's explicit preference to "test all the options and see what is best for us" rather than pick from specs alone).
- **Component list was closed deliberately and explicitly** — went through a structured Q&A pass confirming every single part (down to checking for wheels/tires, a fuse, a microSD card) before locking the architecture, specifically to avoid discovering missing parts mid-build.

### How the plan was built
- The original spec (Section 1) came with an 8-week suggested timeline — this was **explicitly discarded** in favor of a phase-based plan with no fixed deadline, since the project owner has flexible time and prioritized doing navigation (and everything else) properly over hitting arbitrary weekly milestones.
- The plan was only finalized **after** every component was confirmed and every open technical decision (LLM, protocol, camera behavior, servo usage, etc.) was resolved through direct Q&A with the project owner — not assumed upfront.
- A **simulation phase (1.5)** was inserted into the plan mid-way, at the project owner's request, specifically to validate navigation and behavior logic cheaply before committing to physical wiring — this reflects a general preference for de-risking software logic before hardware work where possible.

---

## 1. Project Overview

**D3BOUUR** is an intelligent welcome/receptionist robot, built as an internship project ("Stage") for **AcaROBOTICS**, a company doing educational robotics and AI. This is based on an official "Cahier des charges" (specification document) provided by the internship supervisor.

### Official mission (from the spec)
Design and develop an intelligent welcome robot integrating computer vision, autonomous navigation, voice interaction, and artificial intelligence — meant to greet visitors at events, trade shows, schools, and businesses. It's explicitly framed as a **technology demonstration platform**, not just a functional tool — polish and reliability during live demos matter as much as raw capability.

### Required behaviors (from the spec's objectives)
1. Automatically welcome a person
2. Detect the presence of a human
3. Identify their face
4. Initiate a conversation
5. Respond vocally
6. Move autonomously

### Detailed mission breakdown (from the spec)

**Human-Robot Interaction:**
- Detect a person's arrival
- Automatically orient camera toward them
- Greet the visitor (example phrases given: "Bonjour, bienvenue chez AcaROBOTICS," "Comment puis-je vous aider ?", "Souhaitez-vous découvrir nos formations ?")
- Start a conversation, understand simple voice commands, respond via speech synthesis
- Display information on screen

**Computer Vision:**
- Person detection, face detection
- Automatic tracking of a person
- Face recognition — **explicitly marked OPTIONAL in the spec**
- Presence detection
- Suggested tech: OpenCV, MediaPipe, YOLO, Face Recognition libraries

**Autonomous Navigation:**
- Avoid obstacles (**required**)
- Move to a given point (**required**)
- Return automatically to starting position (**required**)
- Map its environment / SLAM — **explicitly marked OPTIONAL in the spec**

**Wi-Fi Navigation (remote control feature):**
- Robot must be controllable from smartphone/tablet/PC
- Functions: manual movement, return-to-station, emergency stop
- Real-time camera feed, speed control
- Communication: Wi-Fi / WebSocket / MQTT (spec lists both as options)

**AI:**
- Speech recognition, speech synthesis (TTS)
- Intelligent dialogue
- Connection to an LLM API (spec says "OpenAI or local model" — not a hard requirement for a specific provider)
- Automatic response generation

**User Interface (on the screen):**
- AcaROBOTICS company presentation
- Training program catalog ("formations")
- Events calendar/agenda
- Videos
- Contact form

**Required architecture modules (from spec):**
Module Vision, Module IA Conversationnelle, Module Navigation, Module Commande Vocale, Module Interface Graphique, Module Communication Wi-Fi, Base de données de configuration (config database)

**Required languages (from spec):** Python, C++, HTML/CSS, JavaScript
**Required frameworks (from spec):** ROS2, OpenCV, FastAPI, MQTT, MediaPipe

**Official deliverables (from spec):** Software architecture, electronic architecture, functional prototype, web interface, technical documentation, user manual, demo video, Git source code.

**Note on the spec's suggested 8-week timeline:** This was explicitly set aside — the person building this has flexible time with no fixed deadline, so the project is organized into **sequential phases** instead of calendar weeks (see Section 8).

---

## 2. Project Logistics

- **Solo project** — one person building this, no team collaborators currently (this handoff doc exists to fix that).
- **Timeline**: flexible, no fixed deadline — phases take as long as needed, especially navigation which was flagged as at-risk for being rushed under the original 8-week plan.
- **Testing space**: consistent physical space available throughout the project.
- **Development machine**: Windows PC, using WSL2 (Windows Subsystem for Linux) running Ubuntu 24.04 LTS — chosen over dual-boot Ubuntu for practicality; confirmed fully capable of running ROS 2, Gazebo, and GUI tools.

---

## 3. Final Component List

### Compute
| Component | Status |
|---|---|
| Raspberry Pi 5 (+ official fan) | Have, confirmed working via physical inspection |
| Arduino UNO + HW-130 motor control shield | Have — shield plugs directly onto Arduino, has M1-M4 terminals (controls all 4 motors) and a servo header |
| microSD card | Have |

### Sensors & Camera
| Component | Status |
|---|---|
| 6× ultrasonic sensors (fixed placement: front/back/left/right split) | Have |
| PTZ surveillance camera (head-mounted, 360° built-in rotation) | **Pending delivery** — exact model/control protocol unknown until it arrives |

### Movement
| Component | Status |
|---|---|
| 4× JGB37-520 DC motors (rated 6-24V, no built-in encoder — confirmed 2-wire versions) | Have, with wheels/tires ready |
| Continuous-rotation servo (head — turns screen toward visitors) | Have — imprecise (turns by time, not by degree angle) |

### Power
| Component | Status |
|---|---|
| LiPo battery, 3S, 11.1V nominal, 5200mAh | Have — confirmed 3S via balance connector pin count (4 pins) |
| XL4015 buck converter module (SKU:009291) | Have — calibrated, confirmed outputting clean 5.0V from ~11V input |
| Charge/run SPDT toggle switch | Have — used instead of true hot-swap/UPS to safely charge without removing the battery |
| Inline fuse + holder | Have — **F1AL250V (1A)**, used for the electronics branch only; a separate 3-5A fuse still needed for the motor branch |
| USB-C cable (for Pi power) | Uncertain — need to confirm/replace |
| microSD card reader (for flashing Pi OS from a PC without a card slot) | **Need to buy** |

### Interface
| Component | Status |
|---|---|
| 10.1" HDMI LCD screen (Waveshare, 1024x600, XPT2046 touch controller — **touch is broken**) | Have — power via micro-USB "Power Only" port, video via mini-HDMI "Display" port |
| Mouse + keyboard | Have — used by both staff and visitors since touchscreen is broken |
| USB microphone | **Pending delivery** |
| USB speaker | **Pending delivery** |

### Safety
| Component | Status |
|---|---|
| Physical emergency-stop push button | Have |

### Networking
| Component | Status |
|---|---|
| Wi-Fi | Built into Raspberry Pi 5 — no separate module needed |

### Dropped from the design (originally considered, no longer used)
- **HC-05 Bluetooth module** — no role in final design (Wi-Fi/WebSocket replaces it for remote control)
- **ESP32-CAM + programmer board** — replaced by the surveillance PTZ camera as the main vision sensor

### Development environment (not on-robot)
| Tool | Status |
|---|---|
| WSL2 + Ubuntu 24.04 LTS on Windows PC | Fully set up |
| VS Code (connected to WSL) | Fully set up |
| Git + GitHub account | Fully set up, identity configured |
| ROS 2 Jazzy Jalisco | **Installed and verified** (see Section 8) |
| Gazebo Harmonic (simulation) | **Installed and verified** (see Section 8) |

---

## 4. Power Architecture

**Design principle: the battery's raw voltage (~11V) and the 5V logic rail are kept on two completely separate branches, only sharing the battery/fuse/switch as a common source.**

```
LiPo Battery (11.1V)
      ↓
    Fuse (safety — breaks circuit on short/overcurrent)
      ↓
  Power Switch (charge/run selector — also doubles as main on/off)
      ↓
Emergency Stop Button (in-line, cuts everything downstream when pressed)
      ↓
      ├──────────────────────┐
      ↓                      ↓
Buck Converter (XL4015)   HW-130 Shield EXT_PWR terminal
  steps 11V → 5V            (raw ~11V, direct to motor driver)
      ↓                      ↓
  5V Devices:              4× Motors + wiring for head servo
  - Raspberry Pi 5
  - Screen (separate micro-USB power line)
  - USB mic/speaker (via Pi USB)
  - Sensors (via Arduino)
```

**Key wiring facts:**
- The **screen has its own separate power input** (micro-USB "Power Only" port) — it does NOT share the Pi's USB-C power line.
- The **HW-130's EXT_PWR terminal** must be fed directly from the switch output (~11V), NOT through the buck converter — motors need higher voltage than 5V to actually perform.
- There's a **jumper near HW-130's EXT_PWR terminal** (marked "PWR" on the board) that must be set to use external power, not the Arduino's own 5V rail — **this needs physical verification once at the bench**, was not fully confirmed remotely.
- Full detailed step-by-step wiring instructions with exact multimeter-check values exist in a separate document: **`D3BOUUR_Phase2_Power_System.md`** (already created, includes SD card prep, every connection point, and expected voltage readings at each step).

---

## 5. Software Architecture

### High-level module map
| Module (from spec) | Implementation plan |
|---|---|
| Module Vision | PTZ camera + MediaPipe/OpenCV/YOLO — person/face detection, tracking, optional face recognition |
| Module IA Conversationnelle | Local LLM (Ollama) + RAG with AcaROBOTICS content, speech-to-text, text-to-speech |
| Module Navigation | ROS 2 + Nav2 — obstacle avoidance, go-to-point, return-to-origin |
| Module Commande Vocale | Speech recognition (tool TBD — Vosk or local Whisper) |
| Module Interface Graphique | Screen: face/expression display + catalog/events/videos/contact-form browsing interface (FastAPI backend + HTML/CSS/JS frontend, kiosk-mode) |
| Module Communication Wi-Fi | Raspberry Pi's own Wi-Fi hotspot + WebSocket server for remote control |
| Base de données de configuration | Likely SQLite (not finalized) — stores robot settings, possibly interface content |

### Node-level architecture (ROS 2)
```
Sensors & Camera (ultrasonic via Arduino serial + PTZ camera)
      ↓
Behavior State Machine (central decision-maker)
      ↑ (override)
Remote Control (WebSocket)
      ↓ (commands out to three subsystems)
      ├── Navigation (ROS 2 Nav2 → Arduino → motors)
      ├── Conversation (STT → local LLM+RAG → TTS)
      └── Display (screen content + head servo aim)
```

### Arduino/Pi communication
The Arduino UNO **cannot run ROS 2 directly** (2KB RAM, too small even for micro-ROS). It runs simple firmware reading the 6 ultrasonic sensors and driving motors via basic serial text commands. A Python `rclpy` bridge node on the Pi translates between these serial messages and real ROS 2 topics. This is standard practice for hobby-scale robots.

### Camera communication
The PTZ camera likely uses either **RS485/Pelco-D serial protocol** (older analog-style PTZ) or **network/ONVIF commands** (modern IP PTZ). Unknown until the camera arrives — if RS485, an RS485-to-USB adapter will be needed (cheap, not yet purchased since protocol is unconfirmed).

---

## 6. Behavior Design — the core state machine

This is the actual moment-to-moment logic the robot runs:

1. **Moving / Mapping** — robot drives (autonomous navigation), PTZ camera sweeps and builds a visual map (via RTAB-Map or similar), 6 ultrasonic sensors watch for obstacles and feed Nav2's safety layer.
2. **Person detected** — via camera OR ultrasonic sensors (side/back sensors catch people the camera isn't facing yet) → **robot stops immediately**, even mid-transit.
3. **Engaging** — head servo turns the screen to roughly face the person (direction estimated from which ultrasonic sensor triggered), PTZ camera focuses in for face recognition, greeting/conversation begins.
4. **Two possible endings**:
   - Conversation finishes naturally → robot resumes moving/mapping.
   - **Timeout** — if no interaction happens within a set window (~5-10 seconds, to be tuned during testing) after stopping, the robot resumes moving on its own rather than waiting indefinitely. This was an explicit requirement added during design: the robot must not get permanently stuck waiting if a passerby isn't interested.
5. **Manual override** — remote control via WebSocket can take over at any point, fully overriding the autonomous state machine (used for teleoperation/demos).

**Screen vs. camera rotation — important distinction:**
- The **screen stays fixed forward** normally, but turns via the **head servo** to face whoever approaches, since visitors can arrive from any side.
- The **PTZ camera turns independently**, on its own built-in rotation mechanism (not the head servo) — it handles the mapping sweep and precise face-tracking/recognition job.
- These are two separate rotating systems with two separate jobs.

---

## 7. Key Technical Decisions & Rationale

| Decision | Choice | Why |
|---|---|---|
| ROS 2 distro | Jazzy Jalisco | Matches Ubuntu 24.04, the recommended current pairing |
| Simulator | Gazebo Harmonic | Standard ROS 2 pairing, most documentation/community support |
| LLM | Local (Ollama) — **still to be tested against free cloud options** | No budget for paid APIs; conversations are short/scripted so local is more viable than for general chat; genuinely free cloud options (Google Gemini free tier, Groq) exist but conflict with the offline hotspot design — comparison test planned but not yet executed |
| Company knowledge | RAG (retrieval-augmented generation) with AcaROBOTICS content, not fine-tuning | Free, achievable, directly solves "robot must know AcaROBOTICS-specific info" without training anything |
| Remote control protocol | WebSocket over MQTT | Simpler for one robot + one controller; MQTT better suited to multi-device/broadcast scenarios this project doesn't have |
| Networking mode | Pi runs its own Wi-Fi hotspot, NOT joining venue Wi-Fi | Removes dependency on unreliable venue networks during live demos — the highest-priority reliability concern for a "demo platform" robot |
| Return-to-origin without wheel encoders | Combination of camera-based mapping + ultrasonic + motor run-time estimation | Motors have no encoders (confirmed 2-wire only); pure dead-reckoning from motor timing alone is imprecise, so it's supplemented by the camera's mapping data |
| Battery charging approach | Switch-based charge/run selector, NOT true simultaneous charge+discharge | A proper UPS module (PiJuice, etc.) isn't available; true pass-through charging without one risks LiPo safety issues; the switch approach still avoids ever removing the battery (the original goal) while staying safe |
| Battery % display | Software-estimated from voltage readings | No fuel-gauge IC available; revisit if a UPS module is ever sourced |
| Pi OS strategy | Kept existing Debian 13, run ROS 2 via Docker (`ros:jazzy-ros-base` container) instead of reflashing to Ubuntu | Solves the ROS 2 official-package/Ubuntu-codename mismatch without needing a card reader immediately; genuinely valid professional pattern. Ubuntu Server 24.04 reflash remains a future improvement, not currently blocking. |
| Dev environment | WSL2 Ubuntu 24.04, not dual-boot | Fully capable of running ROS 2 + Gazebo + GUI tools (confirmed via testing); avoids USB/partitioning risk; dual-boot remains a fallback if GPU-heavy simulation or hardware passthrough ever becomes a real bottleneck |

---

## 8. Development Progress So Far

### Phase 1 — ROS 2 installation: ✅ COMPLETE
- ROS 2 Jazzy installed via apt (official package repository method — not source build, not Docker)
- Locale configured correctly (`en_US.UTF-8`)
- Verified working via the standard talker/listener test (`demo_nodes_cpp talker` + `demo_nodes_py listener`) — confirmed real inter-node communication
- `ros2 doctor` — all 5 checks passed

### Phase 1.5 — Simulation setup: ✅ MOSTLY COMPLETE (paused by choice before final step)
- Gazebo Harmonic (v8.11.0) installed via `ros-jazzy-ros-gz`
- Verified visually — empty world loads correctly, full GUI interactivity confirmed (rotate/pan/zoom working)
- Created a proper ROS 2 workspace: `~/d3bouur/ros2_ws/src/d3bouur_description`
- Built a URDF/xacro model of D3BOUUR: simple box chassis (0.4 × 0.3 × 0.15m) with 4 cylinder wheels via a reusable xacro macro (front_left, front_right, rear_left, rear_right at correct relative positions)
- xacro file expanded and validated successfully into plain URDF, no errors
- `CMakeLists.txt` updated to install the `urdf` and `launch` folders
- Package builds cleanly with `colcon build`
- Launch file (`display.launch.py`) written — combines `robot_state_publisher` + Gazebo + entity spawner in one command (standard 3-piece ROS2+Gazebo pattern)
- **Paused here by choice** — the actual "spawn D3BOUUR into the running Gazebo scene" step was written but not executed/verified. This is NOT blocking — later phases don't require simulation to be finished.
- **All work committed to Git**: `~/d3bouur/ros2_ws` is a git repository, with a commit: *"Phase 1 & 1.5: ROS 2 install verified, Gazebo verified, initial D3BOUUR URDF model created"*

### Phase 2 — Power system build & validation: IN PROGRESS
A complete, detailed step-by-step document exists separately: **`D3BOUUR_Phase2_Power_System.md`** — covers SD card preparation, and every wiring step from battery through to motors, with exact expected multimeter readings at each stage. Updated to reflect a two-branch fuse design (see below).

**Progress so far:**
- **SD card audited**: found to already have an OS installed by the previous team — turned out to be **Debian 13 (trixie)**, not Raspberry Pi OS, confirmed running on genuine Raspberry Pi 5 Model B Rev 1.0, 8GB RAM. No project-relevant software (ROS, Docker, Arduino tools) was pre-installed, effectively a clean slate.
- **Hostname changed** from the old team's `Khalil` to **`d3bouur`**.
- **New clean user account created**: `d3bouur`, with sudo rights, confirmed fully working over SSH. Old account (`khalilklai`) locked (password disabled, shell set to nologin) rather than fully deleted, due to a stuck background process blocking deletion — acceptable to leave locked for now; full removal deferred to the eventual fresh OS reflash.
- **Real login credentials now known and owned by the project**, not dependent on the old team.
- **Docker installed and verified working** on the Pi (`sudo docker run hello-world` succeeded), user added to the `docker` group for sudo-free usage.
- **ROS 2 Jazzy verified running on the Pi itself**, via the official multi-architecture `ros:jazzy-ros-base` Docker image (confirmed ARM64-compatible) — `ros2 doctor` passed all checks inside the container. This solves the Debian-vs-Ubuntu package mismatch problem: rather than needing to reflash the Pi to Ubuntu just for ROS 2 compatibility, ROS 2 runs inside an Ubuntu-based container regardless of the host OS underneath.
- **Fuse situation resolved differently than planned**: only fuse available is rated **F1AL250V (1A, fast-acting)** — too low for the whole system. Redesigned to a **two-branch fuse approach**: this 1A fuse protects the buck converter/electronics branch only; the motor branch (via HW-130 EXT_PWR) remains deliberately unfused and unpowered until a properly-rated fuse (~3-5A) is sourced.
- **Still not done**: actual battery/fuse/switch/buck-converter/Pi wiring steps (Steps 1-4 of the Phase 2 document) have not yet been physically executed — today's work was entirely about auditing and preparing the Pi's software environment, not the physical power chain.
- **Card reader still not obtained** — a full OS reflash (to Ubuntu Server 24.04 LTS, the originally preferred choice for native ROS 2 support and better performance via no desktop environment) remains a good future improvement once a USB microSD card reader is sourced, but is **no longer urgent/blocking** now that Docker solves the ROS 2 compatibility concern on the current Debian install.

**Decision on OS strategy**: Ubuntu Server 24.04 LTS remains the theoretically ideal choice (native ROS 2 support, no desktop overhead) if a fresh reflash happens later. For now, the Debian 13 + Docker approach is a fully valid, working alternative and does not block progress.

---

## 9. Full Phase Plan (all phases, current status)

1. **ROS 2 installation** — ✅ Done
2. **Simulation setup & testing** — ✅ Mostly done (paused before final spawn test)
3. **Power system build & validation** — 📋 Planned in detail, not started
4. **Physical chassis assembly** — Not started
5. **Basic movement** (Arduino↔Pi serial bridge, drive commands) — Not started
6. **Ultrasonic sensors & reflex safety** — Not started
7. **Navigation (Nav2) on real hardware** — Not started
8. **Camera integration** — Blocked on delivery
9. **Conversation brain** (LLM comparison test, STT/TTS, RAG) — Not started
10. **Screen & head servo** — Not started
11. **Behavior state machine on real hardware** — Not started
12. **Remote control** (hotspot + WebSocket + control app) — Not started
13. **Interface content & config database** — Blocked on content availability (training catalog/events/videos exist in folders, not yet reviewed for what's usable)
14. **Full integration, polish & documentation** — Not started

---

## 10. Open Items / Unresolved Questions

- **Camera exact model/control protocol** — unknown until delivery arrives; determines RS485 vs. network integration approach.
- **Mic/speaker exact models** — unknown until delivery; likely USB.
- **Speech recognition tool** — options open (Vosk vs. local Whisper), decision deferred to testing phase.
- **Text-to-speech tool** — options open (espeak vs. Piper), decision deferred.
- **Face recognition library** — options open (`face_recognition` vs. lighter MediaPipe-based approach), decision deferred.
- **Config database contents/tech** — not finalized (likely SQLite).
- **LLM final choice** — comparison test (Ollama vs. Google Gemini free tier vs. Groq) was planned but not yet executed. Note the cloud options require internet, which conflicts with the Pi-hotspot-only networking design — a hybrid fallback approach was discussed as a possible resolution.
- **Fuse for motor branch** — still needed (~3-5A rating), the 1A fuse on hand only covers the electronics branch.
- **USB microSD card reader** — no longer urgent (Docker solved the ROS2/OS mismatch), but still worth getting eventually for a clean Ubuntu Server reflash and to fully remove the old locked user account.
- **HW-130 EXT_PWR jumper position** — needs physical, in-person verification before wiring motor power (see Section 4).
- **Interface content readiness** — folders of event photos/videos exist, but haven't been reviewed for what's actually usable in the final interface.
- **LLM budget conversation with boss** — recommended but not yet confirmed: whether AcaROBOTICS will cover a small API cost (a few dollars total) vs. staying fully local/free.

---

## 11. Files Referenced in This Project
- `D3BOUUR_Phase2_Power_System.md` — full detailed wiring/build guide for Phase 2
- `~/d3bouur/ros2_ws/` — ROS 2 workspace (Git repository), contains `d3bouur_description` package (URDF, launch file)
- Original spec document: "Cahier des charges — Stage 4, Edge IA/Robotique" from AcaROBOTICS Technologies

---

## 12. Recommended Immediate Next Steps
1. Buy remaining components: fuse+holder, confirm/replace USB-C cable, microSD card reader.
2. Prepare the SD card using Raspberry Pi Imager (SSH + Wi-Fi pre-configured) — can be done before lab access.
3. Execute Phase 2 (power system build) using the detailed document, including in-person verification of the HW-130 jumper.
4. Push the `ros2_ws` Git repository to GitHub, and add any collaborators for real shared, versioned access going forward (this handoff document should live there too, e.g. in a `docs/` folder).
5. When the camera and mic/speaker arrive, identify their exact specs/protocols and update this document accordingly.
