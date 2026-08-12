"""
example.py — usage examples for ptz.py and mic.py.

Edit the CAMERA CONFIG section below for your physical camera, then run
whichever section you need.  Each section is independent.
"""

from ptz import PTZCamera
from mic import probe_stream, print_stream_info, record_clip, listen_live, play_wav
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
FULL_PAN_TIME  = 28.27   # seconds to traverse full pan  range at speed 0.5
FULL_TILT_TIME = 12.28   # seconds to traverse full tilt range at speed 0.5


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

    cam = PTZCamera(IP, PORT, USER, PASS, speed=0.3)
    cam.tilt_sign      = -1
    cam.full_pan_time  = FULL_PAN_TIME
    cam.full_tilt_time = FULL_TILT_TIME
    cam.connect()
    cam.reset_pan(0.0)
    cam.reset_tilt(0.5)   # start at tilt midpoint

    print("Starting audio recording and pan sweep simultaneously...")
    audio_done = threading.Event()

    def record_thread():
        record_clip(RTSP_URL, "sweep_audio.wav", seconds=FULL_PAN_TIME + 2)
        audio_done.set()

    t = threading.Thread(target=record_thread, daemon=True)
    t.start()
    time.sleep(0.5)   # let ffmpeg connect before camera starts moving

    cam.move_to_pan(1.0)  # sweep from 0% to 100%

    audio_done.wait(timeout=FULL_PAN_TIME + 5)
    print("Sweep complete.  Audio saved to sweep_audio.wav")


# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Pick which section to run:
    setup_check()
    # run_calibration()
    demo_movement()
    demo_microphone()
    # demo_sweep_with_audio()
