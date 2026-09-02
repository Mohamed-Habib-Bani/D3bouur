# d3bouur_arduino

The firmware that runs on the Arduino UNO + HW-130 motor shield — motor
control, head servo, the 6 ultrasonic sensors, and the HC-05 Bluetooth
manual-control mode. This is **not** a ROS 2 package and is **not** built by
colcon — it lives under `ros2_ws/src/` only so it sits next to the rest of
the D3BOUUR codebase in one repo, not because colcon does anything with it.

## Why this isn't a colcon package

`.ino` sketches are compiled and flashed by the Arduino IDE (or
`arduino-cli`), which has its own toolchain and its own rule for where code
must live: **the sketch's folder name must exactly match its main `.ino`
file's name.** That's why the structure here is one level deeper than a
normal ROS 2 package:

```
d3bouur_arduino/
├── README.md              (this file)
└── d3bouur_arduino/
    └── d3bouur_arduino.ino   ← the actual sketch
```

## How to open / upload it

1. Install the Arduino IDE (or `arduino-cli`) if it isn't already.
2. Open `d3bouur_arduino/d3bouur_arduino.ino` directly in the Arduino IDE —
   opening the `.ino` file (not the outer folder) is what makes the IDE
   recognize it as a sketch.
3. Select **Board: Arduino Uno** and the correct **Port** (the Arduino
   appears as a USB serial device — on the Pi this is typically
   `/dev/ttyUSB0` or `/dev/ttyACM0`).
4. Upload. The Pi↔Arduino serial link (same USB cable, **9600 baud** — see
   `Serial.begin(9600)` in the sketch; any Pi-side serial code must match
   this) is unaffected by anything in the rest of
   `ros2_ws/` — flashing this only touches the Arduino, not the Pi's ROS 2
   workspace.

## What's in the sketch

Single `.ino` file, no additional libraries beyond `AFMotor_R4` (HW-130
motor shield driver, the "R4"-suffixed fork rather than stock Adafruit
`AFMotor` — check this specific library is installed, not the original)
and the standard `Servo` library. Runs at **9600 baud** (not 115200 — update
the README's earlier upload note above and any Pi-side serial code to
match). All input, from either the Pi (USB serial) or the HC-05 module
(also just a serial UART on the same `Serial` object — the Arduino can't
tell the two apart, it's whatever's connected to RX/TX), is read into one
line buffer and dispatched by `processLine()`.

- **Motor control** — 4× `AF_DCMotor`, one per HW-130 terminal (M1-M4).
  `setMotor(index, value)` takes a signed value (-255..255) and applies a
  `reversed[]` compensation table before calling `run(FORWARD/BACKWARD)` +
  `setSpeed()` — `reversed = {true, false, true, false}` for
  motors 1/2/3/4, i.e. **motor indices 0 and 2 (M1, M3) are flipped in
  software**, matching the physical M1/M3-spin-backward wiring documented
  in `CLAUDE.md`. `M:v1,v2,v3,v4` over serial (comma-separated, parsed with
  `strtok`) drives all 4 motors in one command; any motor set to 0 releases
  (coasts) rather than braking.
- **Head servo** — one `Servo` on pin 10, initialized to 90° (center) in
  `setup()`. `S:angle` over serial sets it directly, `constrain()`-clamped
  to 0-180°. Also recentered to 90° by `stopAllMotors()` (see below).
- **Stop** — `X` over serial (Pi protocol) releases all 4 motors and
  recenters the servo to 90°. Functionally identical to the Bluetooth `S`
  command below (both call `stopAllMotors()`).
- **Ultrasonic sensor stream** — all 6 sensors share one trigger pin
  (`trigPin = 9`) but have individual echo pins, read in a fixed order:
  `echoPins[6] = {A4, A5, A0, A1, A2, A3}` (Neck-Front, Neck-Back,
  Neck-Left, Neck-Right, Base-Left, Base-Right — matches `CLAUDE.md`'s pin
  map). Every 250ms (`sensorInterval`, not driven by an incoming request —
  it's a free-running push), `readAndSendSensors()` pulses the shared
  trigger once per sensor, times each echo with `pulseIn()` (30ms timeout),
  converts to cm, and prints one `D:d1,d2,d3,d4,d5,d6` line. A sensor that
  times out (`pulseIn` returns 0, i.e. no echo/no reading) reports `-1` for
  that slot rather than a bogus distance — this is what a caller should
  watch for on the "flaky sensor" pins noted in `CLAUDE.md`.
- **HC-05 Bluetooth manual control** — single-character commands with no
  colon/argument, checked before the `M:`/`S:` protocol so they can't
  collide with it: `F` (forward, all 4 motors +150), `B` (backward, all 4
  motors -150), `L` (turn left — left-side motors -100, right-side +150),
  `R` (turn right — mirror of `L`), `S` (stop — same `stopAllMotors()` as
  `X`). These are plain ASCII letters sent over the HC-05's Bluetooth
  serial link (e.g. from a phone BLE terminal app or a custom controller),
  giving a way to drive the robot manually without going through the Pi at
  all — useful for a bring-up/demo fallback if the Pi or its software
  stack isn't up. Turn speeds (100/150) are fixed constants, not
  configurable from the remote side.

Treat `CLAUDE.md` (project root) as the source of truth for current pin
assignments, protocol details, and hardware status — this README only
explains how to build/open the sketch, not the wiring.
