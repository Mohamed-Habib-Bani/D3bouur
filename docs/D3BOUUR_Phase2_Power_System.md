# D3BOUUR — Phase 2: Power System Build & Validation (v3 — Four-Branch Design)

## Before you start — safety rules (read every time)
1. Never connect anything to the battery's balance connector (small white plug with many thin wires). Only ever use the main discharge connector (thick red + black wires).
2. Match polarity every single time: positive to positive, negative to negative. Reversing this can destroy components instantly.
3. Multimeter set to **DC Voltage (V⎓)**, not AC. Range covering at least 20V.
4. Work on **one connection at a time** and test with the multimeter before adding the next piece.
5. If anything feels warm, smells odd, smokes, or looks wrong at any point: disconnect the battery immediately.
6. A switch controls ONLY the positive line. Negative/ground never passes through a switch — it runs as one continuous wire to the common ground point. (This was the cause of an earlier incident — a switch shorted when negative was mistakenly wired through it.)

---

## Part A — Inventory check

**Have, confirmed working:**
- [x] LiPo battery (3S, 11.1V, 5200mAh)
- [x] XL4015 buck converter module (SKU:009291) — repurposed: now powers head servo + ultrasonic sensors, NOT the Pi
- [x] New power switch — tested clean continuity, confirmed working
- [x] Inline fuse holder + fuse — F1AL250V (1A) — covers the servo/sensor branch only
- [x] Raspberry Pi 5 + fan
- [x] Arduino UNO + HW-130 shield
- [x] Multimeter
- [x] Jumper wires, connectors, soldering gear, wire strippers
- [x] microSD card (already has a working OS on it — see Part B note)

**Still needed:**
- [ ] **Waveshare UPS Module 3S** — dedicated PD-negotiated 5V/5A power for Pi 5 + screen (solves the red-LED/undervoltage problem)
- [ ] **Arduino barrel jack power cable** — feeds Arduino directly from the LiPo
- [ ] USB-C cable (UPS module → Pi)
- [ ] microSD card reader (for a future clean reflash — not urgent, current Debian+Docker setup works)

**Motor branch fuse — confirmed unobtainable, running unfused:**
- [x] **Decision**: the motor branch will run with NO fuse at all (real fuse unobtainable, DIY wire fuse also declined). The 1A fuse stays exclusively on the servo/sensor branch, where it belongs — a shared fuse covering both branches isn't viable, since the 4 motors alone draw more than 1A during normal operation and would blow a shared fuse immediately even with no fault present. Running the motor branch unfused means the precautions in Step 4 below are not optional — they are the only protection this branch has.

**No longer needed / dropped:**
- ~~Emergency stop button~~ — skipped for now per decision; main switch/battery disconnect is the current safety fallback. Can be added later without redoing other wiring.

---

## Part B — Pi software status (already done)
The Pi's SD card already has a working setup — no need to reflash unless you want to:
- OS: Debian 13 (trixie), confirmed genuine Raspberry Pi 5 Model B Rev 1.0, 8GB RAM
- Hostname: `d3bouur`
- User: `d3bouur`, sudo access confirmed
- Docker installed and verified
- ROS 2 Jazzy verified working via `ros:jazzy-ros-base` Docker container
- EEPROM config: `PSU_MAX_CURRENT=5000` already set (from troubleshooting the XL4015 power issue)
- Still to add: `usb_max_current_enable=1` in `/boot/firmware/config.txt` (belt-and-suspenders alongside the UPS module)

---

## Part C — The four power branches

```
LiPo Battery (11.1V) → Fuse → Switch
      │
      ├─ Branch 1: HW-130 EXT_PWR → 4 Motors          (needs its own 3-5A fuse)
      ├─ Branch 2: Waveshare UPS Module 3S → 5V/5A PD  → Pi 5 (USB-C) + Screen (micro-USB)
      ├─ Branch 3: XL4015 (1A fuse, already wired)     → Head servo + 6 ultrasonic sensors
      └─ Branch 4: Arduino UNO's own barrel jack        (self-regulating, 7-12V input, independent)

USB mic + speaker → powered through Pi's own USB ports (no separate wiring needed)
PTZ camera → power source TBD, pending delivery
```

**Why split this way**: isolates high-current/noisy loads (motors) from PD-sensitive loads (Pi+screen) from moderate simple loads (servo+sensors) from self-regulating loads (Arduino) — a problem in one branch can't disturb the others.

---

## Part D — Build sequence

### Step 1: Battery → Switch (positive only) — ALREADY DONE, VERIFIED
Battery positive → switch terminal 1. Switch terminal 2 → output, tested ON=~11-12.6V, OFF=0V. Battery negative goes straight to a common ground point, never through the switch.

### Step 2: Switch output → Fuse (1A) → XL4015 — ALREADY DONE, VERIFIED
Switch output → fuse → XL4015 IN+. Common ground → XL4015 IN-. Confirmed OUT+/OUT- = 5.0V.

**Important — XL4015's new job**: this branch now feeds the **head servo and 6 ultrasonic sensors**, not the Pi. Do NOT reconnect the Pi to this branch — it lacks the USB-C PD negotiation the Pi 5 requires (confirmed via testing: Pi's LED stayed red on this branch even at max current trimmer).

### Step 3: Pi 5 Power — BLOCKED, no working solution currently available
**Status: genuine unresolved hardware gap.** Every locally-available option has been tried and ruled out:
- XL4015 buck converter — confirmed unstable under load (enters charging-mode behavior, LED changes color, current climbs erratically rather than holding steady); firmware overrides (`PSU_MAX_CURRENT=5000`, `usb_max_current_enable=1`) both set and confirmed not sufficient to fix it
- Waveshare UPS Modules (1S, 2S, 4S variants on hand) — all are cell-count-specific battery management boards designed for direct-wired individual 18650 cells, not compatible with the assembled 3S LiPo pack; none match the pack's 3S/11.1V configuration
- L298N — misidentified attempt, this is a motor driver, not a voltage regulator, cannot do this job
- No generic buck converter (e.g. LM2596-style) available locally
- No online ordering possible

**Current workaround for continued development**: a borrowed phone charger (with its own intact USB-C cable, providing genuine PD negotiation) is used to power the Pi during all software/development work. This is fully legitimate for development purposes — it does not need to be the final power solution to make progress on ROS 2, Docker, code, etc.

**What's actually needed to unblock this for the real robot**: any ONE of —
1. A genuine 3S-compatible or wide-input Raspberry Pi 5 PD power module (e.g. Geekworm RPi5-5V5A-PD or equivalent) — not locally available, would need ordering
2. A plain generic buck converter (non-charging-logic type, e.g. LM2596/MP1584-based) rated 5.1V/3A+, combined with the firmware overrides already set — not yet found locally
3. Any other Waveshare/UPS module genuinely matched to a 3S configuration

**Action item**: flag this to project supervisor/coworkers — a compatible part may be available through AcaROBOTICS or via an ordering channel not currently accessible to the intern personally. This is a parts-availability blocker, not a technical or skill gap.

### Step 4: Motor power path (HW-130 EXT_PWR) — WIRED, VERIFIED, NO FUSE, NOT YET FULLY POWERED
Switch output (a third wire, splitting from the same point) → HW-130 EXT_PWR "+M" — **no fuse in this branch**. Common ground → EXT_PWR "GND". Confirmed ~11-12.6V present at this terminal.

**This branch has NO fuse protection at all. The following precautions are the ONLY safety measure on this branch — treat them as mandatory, not optional:**
1. Continuity check (battery disconnected, multimeter on continuity mode) across the full motor branch before every single power-on, every time
2. When testing motors (Phase 4), power one motor briefly first — never all four simultaneously under sustained load on a first test
3. Stay physically present the entire time motors are powered, hand ready on the switch, ready to disconnect immediately
4. Watch/feel for heat along motor wiring and at the HW-130 board during any test
5. Visually inspect all motor branch connections before each session for anything loose, exposed, or different from last time

**Do NOT power the motors yet in Phase 2** — this step is wiring and voltage verification only. Also still needs the "PWR" jumper near EXT_PWR checked/photographed to confirm it's set to external power, not the Arduino's own 5V.

### Step 5: Arduino power — NEW, NOT YET DONE
Arduino UNO has its own onboard voltage regulator. Feed it directly from the battery (post-fuse, post-switch) via its DC barrel jack input — no additional regulation needed, the Arduino handles this internally. Keep this as an independent connection, not sharing a rail with the motors or the Pi.

---

## Part E — What "done" looks like for Phase 2
- [x] Switch tested clean, wired correctly (positive only)
- [x] Fuse + XL4015 branch verified at 5.0V, now serving servo/sensors
- [x] Motor branch (EXT_PWR) wired and confirmed at ~11V — jumper position still needs physical verification
- [ ] **BLOCKED**: Pi 5 dedicated power module — all local options exhausted, needs to be sourced externally (see Step 3 for details); using borrowed phone charger for development in the meantime
- [ ] Motor branch confirmed unfused by decision — real motor testing (Phase 4) only proceeds with ALL mandatory precautions in place, every single time, given zero automatic protection on this branch
- [ ] Arduino wired to its own barrel jack power, confirmed running independently

---

## Notes / observations (fill in as you go)
_(space for anything unexpected while working)_