"""
example.py — usage examples for ptz.py and mic.py.

Edit the CAMERA CONFIG section below for your physical camera, then run
whichever section you need.  Each section is independent.
"""

import cv2

from ptz import PTZCamera
from mic import probe_stream, print_stream_info, record_clip, listen_live, play_wav
from room_sweep import (
    capture_sweep, capture_sweep_video, extract_sweep_frames,
    stitch_panorama, save_panorama, detect_in_sweep, print_angular_map,
)
from engage import run_engagement_attempt, FaceDetector, EngagementConfig, Outcome
import time

# ════════════════════════════════════════════════════════════════════════════
# CAMERA CONFIG  — edit these for your camera
# ════════════════════════════════════════════════════════════════════════════

IP       = "192.168.1.102"  # camera IP on your LAN
PORT     = 8899             # ONVIF port — find with:  nmap -p 1-65535 --open <IP>
USER     = "admin"
PASS     = "admin"
RTSP_URL = f"rtsp://{USER}:{PASS}@{IP}:554/live/ch00_0"

# Calibrated traversal times at speed=0.5 for the reference V380 Pro camera.
# Run calibrate() on YOUR camera and replace these with your measurements.
CALIBRATION_SPEED = 0.5   # the cam.speed these times were measured at
FULL_PAN_TIME      = 28.27   # seconds to traverse full pan  range at CALIBRATION_SPEED
FULL_TILT_TIME     = 12.28   # seconds to traverse full tilt range at CALIBRATION_SPEED

# Measured room-level tilt fraction — NOT assumed to be 0.5. This camera's
# tilt range turned out to be down-biased enough that 0.5 pointed at the
# floor. Run demo_find_level_tilt() once, watch the feed, and paste the
# printed value here. None until measured — the room-sweep demos refuse to
# guess and will tell you to run it first.
LEVEL_TILT = None


def scaled_pan_time(speed: float) -> float:
    """
    FULL_PAN_TIME was measured at CALIBRATION_SPEED. Traversal time scales
    inversely with speed (time = distance / velocity), so moving at a
    different speed takes proportionally longer or shorter — used wherever
    code needs to know how long an actual full-range pan will take at a
    speed other than CALIBRATION_SPEED (e.g. a sweep run slower to reduce
    motion blur).
    """
    return FULL_PAN_TIME * (CALIBRATION_SPEED / speed)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1 — First-time setup: find ONVIF port + check RTSP audio
# ════════════════════════════════════════════════════════════════════════════
# Uncomment and run this block when setting up a new camera.
# It tries to connect on PORT and probes the RTSP stream for video/audio.

def setup_check():
    print("── ONVIF connection test ──")
    try:
        cam = PTZCamera(IP, PORT, USER, PASS)
        cam.connect()
        print("ONVIF: OK")
    except Exception as e:
        print(f"ONVIF: FAILED — {e}")
        print("Try other ports: nmap -p 1-65535 --open", IP)

    print("\n── RTSP stream check ──")
    print_stream_info(RTSP_URL)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Calibration (run once per physical camera)
# ════════════════════════════════════════════════════════════════════════════
# After running, copy the printed FULL_PAN_TIME and FULL_TILT_TIME values
# into the CAMERA CONFIG section above.
# Manually position the camera to one extreme before starting each axis.

def run_calibration():
    cam = PTZCamera(IP, PORT, USER, PASS)
    cam.connect()

    # Test direction signs FIRST so calibration moves the right way.
    # Comment out the calibrate() call, uncomment these test moves,
    # run them, and flip cam.pan_sign or cam.tilt_sign if reversed.
    #
    # print("Testing pan direction (should move RIGHT)...")
    # cam.move_raw(pan=1, tilt=0, duration=1.5)
    # print("Testing tilt direction (should move UP)...")
    # cam.move_raw(pan=0, tilt=1, duration=1.5)
    #
    # Reference camera result: tilt was reversed, so cam.tilt_sign = -1

    cam.tilt_sign = -1   # reference camera: positive ONVIF tilt = DOWN

    cam.calibrate()
    # After calibration, copy the two printed time values into CAMERA CONFIG.


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Basic movement
# ════════════════════════════════════════════════════════════════════════════

def demo_movement():
    cam = PTZCamera(
        IP, PORT, USER, PASS,
        speed=0.5,
    )
    cam.tilt_sign       = -1          # reference camera tilt is reversed
    cam.full_pan_time   = FULL_PAN_TIME
    cam.full_tilt_time  = FULL_TILT_TIME
    cam.connect()

    # Starting from a known physical position (e.g. after manually homing camera)
    cam.reset_pan(0.0)
    cam.reset_tilt(0.0)

    # Raw timed moves (direction × speed × duration)
    print("Moving right for 2 seconds...")
    cam.move(pan_dir=1, tilt_dir=0, duration=2.0)
    cam.print_position()

    print("Moving up for 1 second...")
    cam.move(pan_dir=0, tilt_dir=1, duration=1.0)
    cam.print_position()

    # Percentage-based moves — requires calibration values to be set
    print("Moving to pan=50% (centre)...")
    cam.move_to_pan(0.5)
    cam.print_position()

    print("Moving to tilt=25%...")
    cam.move_to_tilt(0.25)
    cam.print_position()

    # Drift correction: if the camera has physically drifted from where the
    # tracker thinks it is, manually move it to a known extreme and reset:
    # cam.reset_pan(0.0)   # or reset_pan(1.0) if at the other extreme
    # cam.reset_tilt(0.0)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3B — Home: drive both axes to a verified reference position
# ════════════════════════════════════════════════════════════════════════════
# Isolated test for PTZCamera.home() — watch the camera while this runs.
# Expect: simultaneous pan+tilt motion that visibly stops moving (hits its
# limit) well before the printed duration elapses, then holds there.

def demo_home():
    cam = PTZCamera(IP, PORT, USER, PASS, speed=0.5)   # must match calibration speed
    cam.tilt_sign      = -1
    cam.full_pan_time  = FULL_PAN_TIME
    cam.full_tilt_time = FULL_TILT_TIME
    cam.calibration_speed = CALIBRATION_SPEED   # explicit — see move_to_pan()/home() scaling
    cam.connect()

    cam.home()             # drives both axes to (0.0, 0.0) — the default
    cam.print_position()

    # Sanity check: move somewhere and confirm it's computed from a real
    # reference now, not a guess.
    print("Moving to pan=50%, tilt=50% to confirm relative moves look right...")
    cam.move_to_pan(0.5)
    cam.move_to_tilt(0.5)
    cam.print_position()

    # To home to the opposite corner instead:
    # cam.home(pan_target=1.0, tilt_target=1.0)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3C — Find level tilt: measure the tilt fraction that's actually
#              room height, since it isn't guaranteed to be 0.5
# ════════════════════════════════════════════════════════════════════════════
# Run this once per camera mount. Watch the live feed while it runs — press
# Enter the instant the view looks level (room height, not floor/ceiling).
# Copy the printed value into LEVEL_TILT above.

def demo_find_level_tilt():
    cam = PTZCamera(IP, PORT, USER, PASS, speed=0.5)   # match calibration speed
    cam.tilt_sign      = -1
    cam.full_pan_time  = FULL_PAN_TIME
    cam.full_tilt_time = FULL_TILT_TIME
    cam.calibration_speed = CALIBRATION_SPEED
    cam.connect()

    level = cam.find_level_tilt()
    print(f"\nMeasured LEVEL_TILT = {level:.3f} — paste this into the CAMERA CONFIG section.")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Microphone
# ════════════════════════════════════════════════════════════════════════════

def demo_microphone():
    # Check what tracks the stream has
    info = probe_stream(RTSP_URL)
    if info["audio"] is None:
        print("No audio track found.  Check the RTSP URL and camera settings.")
        return

    a = info["audio"]
    print(f"Audio track: {a['codec'].upper()} {a['sample_rate']} Hz {a['channels']}ch")

    # Record a 5-second clip to a WAV file
    wav_path = record_clip(RTSP_URL, "mic_test.wav", seconds=5)

    # Play it back
    print("Playing back recording...")
    play_wav(str(wav_path))

    # OR: listen live (blocks until Ctrl+C)
    # listen_live(RTSP_URL)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Combined: sweep pan while recording audio
# ════════════════════════════════════════════════════════════════════════════

def demo_sweep_with_audio():
    """Record audio while panning across the full field of view."""
    import threading

    cam = PTZCamera(IP, PORT, USER, PASS, speed=0.5)   # match calibration speed for home()
    cam.tilt_sign      = -1
    cam.full_pan_time  = FULL_PAN_TIME
    cam.full_tilt_time = FULL_TILT_TIME
    cam.calibration_speed = CALIBRATION_SPEED   # explicit — see move_to_pan()/home() scaling
    cam.connect()
    cam.home()             # verified (0.0, 0.0) reference on both axes

    cam.speed = 0.3         # slower pan for the actual sweep
    cam.move_to_tilt(0.5)   # real room-center tilt, computed from home()'s verified reference

    # FULL_PAN_TIME was measured at CALIBRATION_SPEED (0.5); the sweep below
    # runs at cam.speed (0.3), so the actual pan takes proportionally longer.
    # Recording for the un-scaled duration would cut off before the sweep
    # finishes.
    pan_time = scaled_pan_time(cam.speed)

    print(f"Starting audio recording and pan sweep simultaneously "
          f"(pan will take ~{pan_time:.1f}s at speed={cam.speed})...")
    audio_done = threading.Event()

    def record_thread():
        record_clip(RTSP_URL, "sweep_audio.wav", seconds=pan_time + 2)
        audio_done.set()

    t = threading.Thread(target=record_thread, daemon=True)
    t.start()
    time.sleep(0.5)   # let ffmpeg connect before camera starts moving

    cam.move_to_pan(1.0)  # sweep from 0% to 100%

    audio_done.wait(timeout=pan_time + 10)
    print("Sweep complete.  Audio saved to sweep_audio.wav")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Room sweep: capture + panoramic stitch (test this checkpoint
#              first, before adding detection)
# ════════════════════════════════════════════════════════════════════════════

def _require_level_tilt() -> float:
    if LEVEL_TILT is None:
        raise RuntimeError(
            "LEVEL_TILT is not set — run demo_find_level_tilt() once and paste "
            "the measured value into the CAMERA CONFIG section before sweeping."
        )
    return LEVEL_TILT


def demo_room_sweep_panorama():
    level_tilt = _require_level_tilt()

    cam = PTZCamera(IP, PORT, USER, PASS, speed=0.5)   # match calibration speed for home()
    cam.tilt_sign      = -1
    cam.full_pan_time  = FULL_PAN_TIME
    cam.full_tilt_time = FULL_TILT_TIME
    cam.calibration_speed = CALIBRATION_SPEED   # explicit — see move_to_pan()/home() scaling
    cam.connect()
    cam.home()              # verified (0.0, 0.0) reference on both axes, replaces the old guess

    cam.speed = 0.3          # slower for the sweep itself — less motion blur per frame

    frames = capture_sweep(
        cam, RTSP_URL,
        num_frames=8,             # increase if stitching complains about overlap
        pan_range=(0.0, 1.0),
        tilt_position=level_tilt,   # measured room-level tilt, not an assumed 0.5
        settle_s=1.0,
        output_dir="sweep_frames",  # saved frames double as input for demo_room_sweep_detect()
    )

    # PANORAMA mode assumes a physically rotating camera and bundle-adjusts a
    # per-frame focal length/rotation — a mismatch for this camera's digital
    # sensor-crop "pan", where independent per-crop auto-exposure can make
    # that adjustment fail to converge (cv2.Stitcher_ERR_CAMERA_PARAMS_ADJUST_FAIL).
    # SCANS mode is built for translated (not rotated) captures and skips
    # that step entirely — a closer physical match here. If PANORAMA starts
    # working better later (e.g. after locking exposure), swap back.
    pano = stitch_panorama(frames, mode=cv2.Stitcher_SCANS)
    save_panorama(pano, "panorama.jpg")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 6B — Room sweep, continuous video variant: smooth pan the whole
#              way, extract frames from the recording afterward
# ════════════════════════════════════════════════════════════════════════════
# TRADEOFF vs demo_room_sweep_panorama(): that version stops fully before
# each shot, so every frame is as sharp as the lighting allows. Here the
# camera moves throughout every frame's exposure, so every extracted frame
# carries some motion blur proportional to (angular speed x exposure time) —
# there's no exposure control available (no ONVIF Imaging service wired up),
# so speed is deliberately much slower than the stop-and-shoot version to
# keep that blur small. In exchange: one smooth continuous pass, no
# per-position settle delay, and frame count is a free choice made after
# recording rather than committed to up front.

def demo_room_sweep_panorama_continuous():
    level_tilt = _require_level_tilt()

    cam = PTZCamera(IP, PORT, USER, PASS, speed=0.5)   # match calibration speed for home()
    cam.tilt_sign      = -1
    cam.full_pan_time  = FULL_PAN_TIME
    cam.full_tilt_time = FULL_TILT_TIME
    cam.calibration_speed = CALIBRATION_SPEED
    cam.connect()
    cam.home()               # verified (0.0, 0.0) reference on both axes

    sweep_speed = 0.15        # noticeably slower than the stop-and-shoot demo — less blur per frame

    video_path, pan_start, pan_end, duration = capture_sweep_video(
        cam, RTSP_URL, "sweep_video.mp4",
        pan_range=(0.0, 1.0),
        tilt_position=level_tilt,
        speed=sweep_speed,
    )

    frames = extract_sweep_frames(
        video_path, pan_start, pan_end, duration,
        num_frames=8,              # free to change without re-driving the camera — re-run from here
        tilt_position=level_tilt,
        output_dir="sweep_frames_continuous",
    )

    pano = stitch_panorama(frames, mode=cv2.Stitcher_SCANS)
    save_panorama(pano, "panorama_continuous.jpg")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Room sweep: object/person detection + angular map
#              Requires: pip install mediapipe
# ════════════════════════════════════════════════════════════════════════════

def demo_room_sweep_detect():
    """Re-sweeps and detects in one pass. See demo_room_sweep_panorama() for
    a version that only captures + stitches, without the mediapipe dependency."""
    level_tilt = _require_level_tilt()

    cam = PTZCamera(IP, PORT, USER, PASS, speed=0.5)   # match calibration speed for home()
    cam.tilt_sign      = -1
    cam.full_pan_time  = FULL_PAN_TIME
    cam.full_tilt_time = FULL_TILT_TIME
    cam.calibration_speed = CALIBRATION_SPEED   # explicit — see move_to_pan()/home() scaling
    cam.connect()
    cam.home()              # verified (0.0, 0.0) reference on both axes

    cam.speed = 0.3          # slower for the sweep itself — less motion blur per frame

    frames = capture_sweep(
        cam, RTSP_URL, num_frames=8,
        tilt_position=level_tilt,   # measured room-level tilt, not an assumed 0.5
        output_dir="sweep_frames",
    )

    detections = detect_in_sweep(frames, target_labels=["person"])
    print_angular_map(detections)   # pass total_pan_degrees=<measured value> for a degree estimate


# ════════════════════════════════════════════════════════════════════════════
# SECTION 8 — Engagement detection: face-presence + persistence timer
#              Requires: pip install mediapipe (see requirements.txt)
# ════════════════════════════════════════════════════════════════════════════
# Standalone test against the real camera. There's no ultrasonic sensor on a
# dev PC, so each attempt below asks for a simulated pan/tilt "trigger
# direction" and a simulated distance reading instead — that's exactly the
# two inputs run_engagement_attempt() expects a real ultrasonic-driven caller
# to supply once this is wired into the behavior state machine.
#
# To exercise all three outcomes on purpose:
#   ENGAGED         — stand at the given direction, in [distance_min_m,
#                      distance_max_m], and stay put for > presence_threshold_s.
#   RETURN_NO_FACE  — point it at an empty part of the room (no face at all).
#   RETURN_TIMEOUT  — stand in view but keep stepping out of frame / turning
#                      away before presence_threshold_s completes, or give a
#                      distance outside range.

def demo_engagement():
    level_tilt = _require_level_tilt()

    cam = PTZCamera(IP, PORT, USER, PASS, speed=0.5)   # match calibration speed
    cam.tilt_sign      = -1
    cam.full_pan_time  = FULL_PAN_TIME
    cam.full_tilt_time = FULL_TILT_TIME
    cam.calibration_speed = CALIBRATION_SPEED
    cam.connect()
    cam.home()                 # verified (0.0, 0.0) reference on both axes
    cam.move_to_pan(0.5)
    cam.move_to_tilt(level_tilt)   # start "facing front"

    config = EngagementConfig(
        presence_threshold_s=2.5,
        no_face_initial_window_s=1.5,
        max_watch_s=7.0,
        distance_min_m=1.0,
        distance_max_m=2.0,
    )

    print("\nLoading face model (first run downloads it)...")
    with FaceDetector() as detector:
        while True:
            raw = input(
                "\nSimulated trigger — pan target 0.0-1.0 "
                "(blank to quit): "
            ).strip()
            if not raw:
                break
            pan_target = float(raw)
            distance = float(input("Simulated ultrasonic distance in meters: ").strip())

            result = run_engagement_attempt(
                cam, RTSP_URL,
                pan_target=pan_target,
                tilt_target=level_tilt,
                distance_m=lambda: distance,
                return_pan=0.5,
                return_tilt=level_tilt,
                face_detector=detector,
                config=config,
            )
            print(f"  -> {result.outcome.name}  "
                  f"(elapsed={result.elapsed_s:.1f}s, best_streak={result.best_streak_s:.1f}s, "
                  f"distance={result.distance_m})")


# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Pick which section to run:
    # setup_check()
    # run_calibration()
    # demo_movement()
    # demo_home()
     demo_find_level_tilt()   # run this first — LEVEL_TILT is None until measured
    # demo_microphone()
    # demo_sweep_with_audio()
    # demo_room_sweep_panorama()
    # demo_room_sweep_panorama_continuous()
    # demo_room_sweep_detect()
    # demo_engagement()
