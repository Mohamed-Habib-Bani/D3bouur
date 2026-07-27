# D3BOUUR — Phase 2: Power System Build & Validation (Full Detailed Version)

## Before you start — safety rules (read every time)
1. Never connect anything to the battery's balance connector (small white plug with many thin wires). Only ever use the main discharge connector (thick red + black wires, usually with a bigger connector like XT60).
2. Match polarity every single time: positive (red, usually marked `+`) to positive, negative (black, usually marked `-` or `GND`) to negative. Reversing this can destroy components instantly, with no warning first.
3. Multimeter set to **DC Voltage (V⎓)**, not AC (the symbol with a wavy line). Range covering at least 20V.
4. Work on **one connection at a time** and test with the multimeter before adding the next piece — don't wire the whole chain and test only at the end.
5. If anything feels warm, smells odd, smokes, or looks wrong at any point: disconnect the battery immediately.
6. Keep the multimeter's probes only touching the two points you intend to measure — never let probes bridge two different pins by accident.

---

## Part A — Inventory check
Confirm you have all of these physically in hand before starting:
- [ ] LiPo battery (3S, 11.1V, 5200mAh)
- [ ] XL4015 buck converter module (SKU:009291) — already calibrated to 5.0V output
- [ ] SPDT toggle/rocker switch (charge/run switch)
- [ ] Physical emergency-stop push button
- [x] Inline fuse holder + fuse — **confirmed: F1AL250V (1A, fast-acting, 250V rating)**. This is sized for the electronics branch only (Pi/screen/sensors via the buck converter) — a separate, higher-rated fuse (~3-5A, to be calculated) is still needed for the motor branch before Step 5 can be powered.
- [ ] USB-C cable (confirmed genuine USB-C on both ends)
- [ ] microSD card + card reader
- [ ] Multimeter
- [ ] Jumper wires, connectors, soldering gear, wire strippers
- [ ] Raspberry Pi 5 + fan
- [ ] Arduino UNO + HW-130 shield

---

## Part B — Prepare the SD card (do this before anything else)
This gets the Pi ready to be controlled over SSH the moment it's powered, with no monitor/keyboard needed.

1. Insert the microSD card into a card reader, plug into a PC.
2. Open **Raspberry Pi Imager**.
3. Choose Device: **Raspberry Pi 5**. Choose OS: **Raspberry Pi OS (64-bit)**. Choose Storage: your SD card.
4. Before writing, open the **advanced options (gear icon)**:
   - Enable SSH — use password authentication
   - Set a username and password you'll remember
   - Enter the WiFi network name and password you'll be using at the lab
   - Set hostname to something like `d3bouur`
5. Write the image. Wait for it to finish and verify.
6. Eject safely, keep the card ready to insert into the Pi later in this process.

---

## Part C — Build the power chain, step by step

### Step 1: Battery → Switch (fuse moved to Step 3, see note)
**Important change from the original plan**: the fuse we have (F1AL250V, 1A) is only rated for 1 amp — too low for the combined system (motors alone can pull several amps). Instead of placing it before the switch (protecting everything), it's placed later, specifically on the **buck converter's input line only** (Step 3), protecting just the Pi/screen/sensors branch. The motor branch (Step 6) remains unfused until a properly-rated fuse (~3-5A) is sourced, and stays unpowered until then.

**What connects to what:**
- Battery's main discharge connector **positive (red)** wire → switch's input terminal directly (no fuse yet at this point)
- Battery's negative (black) wire → switch's other terminal / ground path

**Do this:**
1. Connect the battery's red wire directly to the switch's input terminal (solder or a secure connector — never just twisted wires left loose).
2. Connect the battery's black wire to the switch's ground path (or straight through, depending on your switch type).
3. Flip the switch to the "run"/"on" position.

**Check with multimeter:**
- Red probe on switch output terminal, black probe on battery negative.
- Expected: **~11-12.6V** (confirms the switch is passing power through correctly).

---

### Step 2: Switch output → Fuse (F1AL250V, 1A) → Buck converter (XL4015)
**What connects to what:**
- Switch output (positive, ~11V) → one side of the **fuse holder** (with the 1A fuse inserted)
- Fuse holder's other side → buck converter's **IN+** terminal
- Battery negative (from switch, or straight through) → buck converter's **IN-** terminal directly (no fuse on the negative line)

**Do this:**
1. Connect switch output positive → fuse holder input.
2. Connect fuse holder output → buck converter **IN+**.
3. Connect negative line → buck converter **IN-**.

**Check with multimeter:**
- Red probe on the fuse holder's output side, black probe on negative line. Expected: **~11-12.6V** (confirms the fuse is intact and passing power).
- Red probe on buck converter's **OUT+**, black probe on **OUT-**.
- Expected: **5.0V exactly** (we calibrated this before — this step confirms it's still correct after being moved/rewired).
- If it's drifted: small careful adjustments to the CV trimmer on the board, rechecking after each small turn, until it reads 5.0V again.

---

### Step 3: Buck converter output → Raspberry Pi 5 (first real-load test)
**What connects to what:**
- Buck converter **OUT+/OUT-** → USB-C cable → Raspberry Pi 5's USB-C power port

**Do this:**
1. Insert the pre-configured SD card into the Pi (from Part B).
2. Connect the USB-C cable from the buck converter output to the Pi.
3. Power on (flip the switch on if not already).
4. Watch the Pi's onboard status LEDs — a small green LED should flash during boot (SD card activity), settling after ~30-60 seconds.
5. From your laptop, connected to the same WiFi network you configured, open a terminal and run:
   ```
   ssh yourusername@d3bouur.local
   ```
   (replace `yourusername` with what you set in the Imager)
6. Enter the password you set. You should land in a Pi terminal prompt.
7. Run:
   ```
   vcgencmd get_throttled
   ```
   Expected result: `throttled=0x0` (means no undervoltage ever detected — power supply is solid).
8. If it shows anything else: the buck converter's current limit (CC trimmer) is likely set too low. Adjust it higher, power-cycle the Pi, and retest.
9. Let the Pi run for several minutes over SSH (run a few commands, `ls`, `top`, etc.) — confirm it doesn't randomly disconnect or restart.

---

### Step 4: Emergency stop button
**What connects to what:**
- Wired in-line on the main positive power path, positioned **before** the buck converter and the motor power line both branch off — meaning: Switch output → **through the emergency stop button** → then splits to buck converter and motor power.

**Do this:**
1. Insert the emergency-stop button in-line on the positive wire, between the switch and the point where it splits toward the fused buck-converter branch (Step 2) and the still-unfused HW-130 EXT_PWR branch (Step 5).
2. In its normal (not pressed) state, it should allow power through.
3. When pressed, it should physically break the circuit, cutting power to everything downstream at once.

**Check with multimeter (or just observe the Pi):**
1. With everything running normally (Pi powered, SSH connected), press the emergency stop button.
2. Expected: the Pi loses power immediately, SSH session drops.
3. Release/reset the button (many are twist-to-release or pull-to-release), confirm power returns and the Pi can be turned back on normally.

---

### Step 5: Motor power path (HW-130 EXT_PWR) — wiring only, not testing motors yet
**What connects to what:**
- Switch output (battery voltage, ~11V, **after** the emergency stop button, but **NOT** through the buck converter) → HW-130's **EXT_PWR "+M"** terminal
- Battery negative → HW-130's **EXT_PWR "GND"** terminal

**Do this:**
1. Locate the EXT_PWR terminal on the HW-130 (the small 2-pin screw terminal near where "SBX" is printed on the board).
2. Locate the small jumper near it (marked "PWR" in the photo we looked at) — **this must be set to use external power, not the Arduino's own 5V.** Take a clear close-up photo of this jumper before touching it, and check its current position against the board's silkscreen labeling (the printed text on the board itself usually indicates which position means what).
3. Connect switch output (positive) → EXT_PWR "+M".
4. Connect battery negative → EXT_PWR "GND".
5. **Do not power on the motors yet.** This step is purely confirming the wiring path is physically correct and ready — actual motor testing happens in Phase 4, once we're also ready to handle a robot that can suddenly move.

**Check with multimeter:**
- Red probe on EXT_PWR "+M" terminal, black probe on "GND" terminal, with switch ON.
- Expected: **~11-12.6V** present at this terminal, confirming motor power is correctly available, separate from the Pi's 5V line.

---

## Part D — What "done" looks like for Phase 2
- [ ] SD card prepared with SSH + WiFi pre-configured
- [ ] Battery → switch chain confirmed at ~11-12.6V
- [ ] Switch → 1A fuse → buck converter confirmed: fuse output ~11-12.6V, buck converter output steady 5.0V
- [ ] Pi boots, reachable via SSH, `vcgencmd get_throttled` shows `0x0`
- [ ] Emergency stop button confirmed to cut power to everything when pressed
- [ ] Motor power path (EXT_PWR) wired and confirmed at ~11V, jumper position verified — but motors NOT yet powered (still unfused — a 3-5A fuse must be sourced for this branch before Step 5 can be energized)

---

## Notes / observations (fill in as you go)
_(space for anything unexpected while working)_

