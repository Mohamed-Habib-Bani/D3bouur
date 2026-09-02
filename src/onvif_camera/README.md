# onvif_camera

Control code for D3BOUUR's camera — a **V380 Pro**, a consumer WiFi camera
(not the industrial RS485/Pelco-D unit originally assumed). Plain Python
scripts, not yet wrapped in a ROS 2 node.

## Status: **BUILT, NOT YET VERIFIED** — read this section before trusting any specific claim below

This package's overall status is "not yet verified" because **the real
camera is not connected to this dev machine**, so nothing here can be
re-tested today. Every claim in this README falls into exactly one of two
buckets — read carefully, since they mean very different things:

- **"Confirmed working against the real camera"** — this happened in a past
  session, against the actual V380 Pro, with real results. It is not
  re-verified today and could regress without anyone noticing until the
  camera is reconnected.
- **"Import/syntax-tested today"** — verified just now, on this dev machine,
  with no camera attached: all five `.py` files parse with no syntax errors,
  and all dependencies (`onvif-zeep`, `opencv-python-headless`/`opencv-contrib-python`,
  `mediapipe`, plus system `ffmpeg`/`ffprobe`/`aplay`) import/resolve cleanly.
  This proves the code is well-formed and runnable — it does **not** prove
  any camera-facing behavior actually works right now.

## What each file does

- **`ptz.py`** — ONVIF pan/tilt control (`ContinuousMove`) with
  heartbeat-sustained movement, dead-reckoning position tracking (the camera
  reports no absolute position via ONVIF, so this tracks it in software from
  known move durations), and interactive calibration. Includes `home()`
  (drives both axes to a real physical extreme rather than just declaring a
  position) and `find_level_tilt()` (measures the actual room-level tilt
  fraction — confirmed via testing that it isn't 0.5, the naive assumption).
  **Confirmed working against the real camera**: PTZ pan/tilt movement,
  confirmed in a past session.
- **`mic.py`** — Microphone access via the RTSP stream's own audio track
  (H264 video + AAC 16kHz mono audio share one RTSP URL; ffprobe/ffmpeg
  discover the audio track directly even though the camera's ONVIF profile
  doesn't formally declare one). No separate USB mic needed.
  **Confirmed working against the real camera**: microphone recording,
  confirmed in a past session, same session as the PTZ test above (movement
  + recording both succeeded in one run).
- **`room_sweep.py`** — Room-awareness from a fixed-mount camera: drives a
  pan sweep, captures frames (stop-and-shoot via `capture_sweep()`, or a
  continuous-video variant via `capture_sweep_video()`), stitches a panorama
  with OpenCV's `Stitcher`, and runs MediaPipe object detection across the
  sweep to build a rough "angular map" (e.g. "a chair was seen at ~62% pan").
  **Tested standalone against the real camera** via `example.py`'s demo
  functions in a past session — not integrated into anything else.
- **`engage.py`** — Face-presence engagement: turns the camera toward a
  given pan/tilt target (from an ultrasonic-supplied direction, in the
  eventual design), runs MediaPipe face detection with a persistence timer,
  and decides `ENGAGED` / `RETURN_NO_FACE` / `RETURN_TIMEOUT`. This is the
  real logic meant to eventually replace `d3bouur_behavior`'s
  `_orient_toward_person()` stub. **`trigger_head_servo()` is itself still a
  stub** — it only prints, it does not send a real Arduino `S:angle`
  command. **Tested standalone against the real camera** via `example.py`'s
  demo functions in a past session — not wired to real ultrasonic input, the
  behavior state machine, or the servo.
- **`example.py`** — Demo functions exercising every module above
  (`demo_movement`, `demo_home`, `demo_find_level_tilt`, `demo_microphone`,
  `demo_sweep_with_audio`, `demo_room_sweep_panorama`,
  `demo_room_sweep_panorama_continuous`, `demo_room_sweep_detect`,
  `demo_engagement`) — this is how everything above has actually been
  exercised so far; there is no automated test suite.

## The digital-pan discovery — a correction to earlier assumptions

Earlier project notes (and an earlier version of the top-level `CLAUDE.md`)
described this camera as having "motorized pan-tilt" / "360° built-in
rotation," implying a physically rotating turret. That's now known to be
**inaccurate**: this camera's "PTZ" pan is a **digital sensor-crop pan**, not
physical rotation. This was discovered while building `room_sweep.py`'s
panorama stitching — OpenCV's `Stitcher_PANORAMA` mode (which assumes a
physically rotating camera and bundle-adjusts per-frame focal length/rotation)
did not stitch reliably; switching to `Stitcher_SCANS` mode (built for
translated, not rotated, captures — see `example.py`'s calls to
`stitch_panorama(frames, mode=cv2.Stitcher_SCANS)`) is what made panoramas
stitch reliably, confirming the pan is a crop/translation effect, not a
physical rotation. Everything else about PTZ control (ONVIF `ContinuousMove`,
dead-reckoning position tracking) still holds regardless of this correction.

## The speaker dead-end — confirmed unavailable, real investigation story

**Confirmed dead end**: the camera's speaker (two-way audio) is not
accessible via ONVIF or RTSP on this camera. A separate USB speaker will be
sourced instead.

The investigation behind that conclusion is documented here from project
session history — it is **not** something verifiable from `ptz.py`/`mic.py`'s
code comments alone (those only cover the AES/port/embedded-key summary
below); this is the fuller story as recorded from that session:

1. Traced speaker control to a proprietary encrypted protocol on TCP port
   8089 (separate from ONVIF, which exposes no `AudioOutputConfiguration`
   for this camera).
2. Found an existing open-source tool built for a similar camera model, but
   this camera's protocol version didn't match (different packet header
   format).
3. Got a modified version partially working — real structured responses
   from the camera — but hit a wall: the camera negotiates a fresh AES
   encryption key per session over MQTT, with the entire payload encrypted
   and no exploitable unencrypted portion.
4. Attempted Frida (dynamic instrumentation) to hook the phone app's
   encryption function at runtime and capture the key as used — got as far
   as patching and installing a modified version of the app.
5. The V380 Pro app has a commercial anti-tampering security layer that
   detects this kind of modification and deliberately crashes the app as a
   defense mechanism — a legitimate security feature working as designed,
   not a bug, and the actual cause of the repeated app crashes hit during
   this attempt.
6. One more lead (a different open-source tool with documented
   credential-extraction via packet capture) was found but also didn't pan
   out.
7. **Final decision**: buy a separate USB speaker rather than continue
   pursuing this.

## Reliability hardening — done; the live drop test — not done

Both `ptz.py` and `mic.py` have connect retry + reconnect-on-failure logic
(`connect()`'s retry loop, `_call_with_reconnect()` in `ptz.py`;
`probe_stream()`/`record_clip()`/`listen_live()`'s retry/auto-reconnect in
`mic.py`). This has been **confirmed working end-to-end against the real
camera** in a past session — movement and mic recording both succeeded in
the same run.

**What has NOT been done**: actually triggering a live WiFi drop (e.g.
physically disconnecting the camera or the Pi mid-move / mid-record) to
watch the retry/reconnect logic recover in practice. The retry code exists
and is exercised on ordinary call failures, but the specific "pull the WiFi
mid-operation" scenario it's designed for has never been directly tested.

## Testing

There is no automated test suite. Everything is exercised through
`example.py`'s demo functions, which require the real camera:

```bash
cd src/onvif_camera
pip install -r requirements.txt
# edit IP/PORT/USER/PASS at the top of example.py to match your camera
python3 example.py
```

What can be checked **without** the camera, on any dev machine:

```bash
cd src/onvif_camera
python3 -m py_compile ptz.py mic.py room_sweep.py engage.py example.py
python3 -c "import onvif, cv2, mediapipe"   # requirements.txt deps resolve
```

Both checks currently pass on this dev machine — see the status section
above for exactly what that does and doesn't prove.

## Not yet done

- No ROS 2 wrapper — everything here remains plain Python scripts run
  directly, not nodes/topics.
- `room_sweep.py` and `engage.py` are not wired to each other's eventual
  callers: no real ultrasonic trigger feeds `engage.py`, and `engage.py`'s
  `trigger_head_servo()` doesn't send a real servo command.
- The live WiFi-drop test described above.
