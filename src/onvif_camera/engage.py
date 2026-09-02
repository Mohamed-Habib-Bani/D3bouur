"""
engage.py — Face-presence engagement detection.

Replaces the panorama-sweep priority scheme (room_sweep.py's Stage 3 is not
wasted — capture_sweep()/stitch_panorama() still work standalone — but it's
no longer the mechanism deciding WHO to approach).

THE FLOW THIS MODULE IMPLEMENTS
────────────────────────────────
  1. An ultrasonic sensor trips (real distance reading, real direction) —
     that event is the caller's job to detect; this module is handed the
     resulting pan/tilt target and a distance reading/getter.
  2. Camera turns to face that direction (reuses ptz.py's PTZCamera).
  3. FaceDetector runs on each frame — face presence, not generic person
     detection, because a detected face inherently means someone is roughly
     facing the camera (a person walking past side-on won't trigger it).
  4. A running persistence timer tracks how long the SAME look-attempt keeps
     seeing a face across consecutive frames — resets the instant a frame
     comes back with no face.
  5. "Wants to communicate" = face persisted >= presence_threshold_s AND the
     distance reading is within [distance_min_m, distance_max_m] at the
     moment persistence completes. Only then: ENGAGED (trigger_head_servo()
     is called; the caller/state machine takes it from there).

Two distinct "give up and recenter" paths, matched to how confident we are
that nothing is going to happen:
  - RETURN_NO_FACE:  no face at all during the initial look window — almost
    certainly a wall/furniture/object tripped the ultrasonic sensor, not a
    person, so recenter immediately rather than sit through a full timeout.
  - RETURN_TIMEOUT:  a face WAS seen at some point but never strung together
    presence_threshold_s of continuous presence before the overall watch
    window ran out (flickered in/out, or turned away) — recenter, but only
    after actually giving it the full window's benefit of the doubt.
A third case — engaged, then the conversation ends or times out — is NOT
handled here; that's the existing behavior state machine's Timeout/Natural
End logic once this is wired to it (see d3bouur_behavior).

WHY MEDIAPIPE FACE DETECTOR (BlazeFace short-range) FOR THE FACE MODEL
────────────────────────────────────────────────────────────────────────
Same Pi-5-CPU-only constraint room_sweep.py's detect_in_sweep() reasoned
through for generic object detection (see that file's module docstring) —
but face presence is a narrower, better-served problem, and the answer is
mediapipe again rather than a second toolchain, for two independent reasons:
  - Consistency: mediapipe is already the one detection dependency this
    project has committed to (room_sweep.py, requirements.txt). Reaching for
    OpenCV's DNN face detector (the well-known res10_300x300_ssd Caffe pair)
    would work technically, but "already tested to run on Pi5, already a
    project dependency" beats "one more detector to install/verify/keep
    working" when both are viable — a second detection library here buys
    nothing this task needs.
  - Fit: BlazeFace short-range is *purpose-built* for exactly this job —
    fast, close-range, real-time face presence on CPU-only mobile/edge
    hardware, not a repurposed generic detector. The model is ~200KB
    (vs res10's ~10MB Caffe weights) and mediapipe ships official aarch64
    wheels — same 64-bit-OS requirement already noted for the Pi 5 in
    requirements.txt, so no new hardware caveat either.
This does mean this module can't run without mediapipe installed (unlike
capture_sweep()/stitch_panorama() in room_sweep.py, which work without it) —
that's fine, since face presence IS this module's whole job, not an optional
extra stage.

TESTING NOTE
────────────
On a dev PC there's no ultrasonic sensor to trigger this for real. Pass a
`distance_m` callable so a manual/simulated reading can stand in for it —
demo_engagement() in example.py prompts for one interactively per attempt so
all three outcomes (engaged / no-face / timeout) can be exercised on purpose.
"""

import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

import cv2

from ptz import PTZCamera
from room_sweep import (
    DEFAULT_CONNECT_RETRIES,
    DEFAULT_CONNECT_RETRY_DELAY,
    DEFAULT_FRAME_RETRIES,
    DEFAULT_FRAME_RETRY_DELAY,
    _grab_fresh_frame,
    _open_capture,
)


# ─── Face model ─────────────────────────────────────────────────────────────

DEFAULT_MODEL_PATH = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"
DEFAULT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)


def ensure_face_model(model_path: Path = DEFAULT_MODEL_PATH, url: str = DEFAULT_MODEL_URL) -> Path:
    """Return a path to the BlazeFace .tflite model, downloading it on first use."""
    import urllib.request

    model_path = Path(model_path)
    if model_path.exists():
        return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Face model not found at {model_path}; downloading from {url} ...")
    try:
        urllib.request.urlretrieve(url, model_path)
    except Exception as e:
        raise RuntimeError(
            f"Could not download face model to {model_path}: {e}\n"
            f"Download it manually from {url} and place it at that path."
        ) from e

    print(f"Saved model ({model_path.stat().st_size:,} bytes) to {model_path}")
    return model_path


class FaceDetector:
    """
    Thin wrapper around mediapipe's Face Detector task (IMAGE mode — each
    poll is treated as an independent frame; the persistence timer in
    EngagementConfig/run_engagement_attempt() is what tracks continuity
    across frames, not mediapipe's own VIDEO running mode).

    Import of mediapipe is lazy so the rest of this file (constants, dataclasses)
    can be imported without it installed — the actual detection call fails
    loudly with an actionable message instead.
    """

    def __init__(self, model_path: Optional[str] = None, min_detection_confidence: float = 0.5):
        try:
            import mediapipe as mp
        except ImportError as e:
            raise RuntimeError(
                "mediapipe is not installed — required for FaceDetector.\n"
                "Install with: pip install mediapipe\n"
                "On Raspberry Pi OS this requires the 64-bit OS; mediapipe does "
                "not publish 32-bit ARM wheels."
            ) from e

        self._mp = mp
        resolved = ensure_face_model(Path(model_path) if model_path else DEFAULT_MODEL_PATH)

        BaseOptions = mp.tasks.BaseOptions
        FaceDetectorTask = mp.tasks.vision.FaceDetector
        FaceDetectorOptions = mp.tasks.vision.FaceDetectorOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(resolved)),
            running_mode=VisionRunningMode.IMAGE,
            min_detection_confidence=min_detection_confidence,
        )
        self._detector = FaceDetectorTask.create_from_options(options)

    def face_present(self, frame_bgr) -> bool:
        """True if at least one face was detected in this frame."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._detector.detect(mp_image)
        return len(result.detections) > 0

    def close(self) -> None:
        self._detector.close()

    def __enter__(self) -> "FaceDetector":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ─── Engagement state machine ────────────────────────────────────────────────

class Outcome(Enum):
    ENGAGED           = auto()   # face persisted long enough, distance in range
    RETURN_NO_FACE    = auto()   # case 1 — nothing ever detected, recenter promptly
    RETURN_TIMEOUT    = auto()   # case 2 — face seen but never persisted, recenter after full window


@dataclass
class EngagementConfig:
    presence_threshold_s:    float = 2.5   # continuous face presence needed to count as genuine interest
    no_face_initial_window_s: float = 1.5  # if no face at all shows up in this long, assume object not person
    max_watch_s:             float = 7.0   # overall cap on how long a single look-attempt runs
    distance_min_m:          float = 1.0   # "reasonable range" lower bound
    distance_max_m:          float = 2.0   # "reasonable range" upper bound
    poll_interval_s:         float = 0.2   # time between frame grabs while watching
    frame_flush:             int   = 1     # frames to discard per grab, see room_sweep._grab_fresh_frame


@dataclass
class EngagementResult:
    outcome:        Outcome
    elapsed_s:       float   # total time spent watching, from turn-complete to decision
    best_streak_s:   float   # longest continuous face-presence streak seen this attempt
    distance_m:      Optional[float]  # distance reading at the decision point (None if never reached one)
    reason:          str     # human-readable explanation, for logging/debugging


def trigger_head_servo(pan_target: float, tilt_target: float) -> None:
    """
    Placeholder for the real action: send the Arduino an `S:angle` command
    (see the Pi<->Arduino serial protocol in the handoff doc) to turn the
    head servo toward the same direction the camera is already facing.

    Left as a stub — same "clean, swappable function call" pattern the
    behavior state machine and kiosk face were built with — because the
    servo is Arduino hardware, not reachable from this dev-PC test setup.
    Wire this up once run_engagement_attempt() is actually driven from real
    hardware instead of example.py's manual-input demo.
    """
    print(f"[STUB] trigger_head_servo(pan={pan_target:.2f}, tilt={tilt_target:.2f}) "
          f"— would send Arduino S:angle here")


def run_engagement_attempt(
    cam: PTZCamera,
    rtsp_url: str,
    pan_target: float,
    tilt_target: float,
    distance_m: Callable[[], float],
    return_pan: float = 0.5,
    return_tilt: Optional[float] = None,
    face_detector: Optional[FaceDetector] = None,
    config: Optional[EngagementConfig] = None,
) -> EngagementResult:
    """
    Turn the camera to (pan_target, tilt_target), watch for a persistent
    face, and decide ENGAGED / RETURN_NO_FACE / RETURN_TIMEOUT.

    distance_m: called once, at the moment persistence completes, to check
    the "reasonable range" condition — not polled continuously, since on
    real hardware this stands in for the single ultrasonic reading that
    triggered the turn in the first place. Pass a lambda for a fixed test
    value, or a real sensor-read function once wired to hardware.

    return_pan/return_tilt: where "facing front" is. return_tilt defaults to
    tilt_target when not given (only pan recenters) — pass the real
    LEVEL_TILT for an actual front-facing recenter.

    On RETURN_NO_FACE / RETURN_TIMEOUT this function recenters the camera
    itself before returning. On ENGAGED it does NOT recenter — that's the
    existing behavior state machine's job once the conversation ends (case 3
    in the module docstring), not this module's.

    Requires cam to already be connect()ed and calibrated (full_pan_time/
    full_tilt_time set) — same precondition as room_sweep.py's capture
    functions, since move_to_pan()/move_to_tilt() need it.
    """
    cfg = config or EngagementConfig()
    owns_detector = face_detector is None
    detector = face_detector or FaceDetector()
    if return_tilt is None:
        return_tilt = tilt_target

    cap = None
    try:
        print(f"Turning to pan={pan_target:.2f}, tilt={tilt_target:.2f} to look...")
        cam.move_to_pan(pan_target)
        cam.move_to_tilt(tilt_target)

        cap = _open_capture(rtsp_url, max_retries=DEFAULT_CONNECT_RETRIES,
                             retry_delay=DEFAULT_CONNECT_RETRY_DELAY)

        attempt_start = time.monotonic()
        streak_start: Optional[float] = None
        best_streak_s = 0.0
        seen_any_face = False
        outcome: Optional[Outcome] = None
        reason = ""
        dist_reading: Optional[float] = None

        while True:
            frame, cap = _grab_fresh_frame(
                cap, rtsp_url,
                flush_frames=cfg.frame_flush,
                max_retries=DEFAULT_FRAME_RETRIES,
                retry_delay=DEFAULT_FRAME_RETRY_DELAY,
            )
            now = time.monotonic()
            elapsed = now - attempt_start
            present = detector.face_present(frame)

            if present:
                seen_any_face = True
                if streak_start is None:
                    streak_start = now
                streak_s = now - streak_start
                best_streak_s = max(best_streak_s, streak_s)

                if streak_s >= cfg.presence_threshold_s:
                    dist_reading = distance_m()
                    if cfg.distance_min_m <= dist_reading <= cfg.distance_max_m:
                        outcome = Outcome.ENGAGED
                        reason = (f"face persisted {streak_s:.1f}s, distance "
                                  f"{dist_reading:.2f}m in range "
                                  f"[{cfg.distance_min_m}, {cfg.distance_max_m}]")
                    else:
                        outcome = Outcome.RETURN_TIMEOUT
                        reason = (f"face persisted {streak_s:.1f}s but distance "
                                  f"{dist_reading:.2f}m outside range "
                                  f"[{cfg.distance_min_m}, {cfg.distance_max_m}]")
                    break
            else:
                streak_start = None   # any missed frame resets the streak, per spec
                if not seen_any_face and elapsed >= cfg.no_face_initial_window_s:
                    outcome = Outcome.RETURN_NO_FACE
                    reason = (f"no face detected within initial "
                              f"{cfg.no_face_initial_window_s}s window — "
                              f"likely an object, not a person")
                    break

            if elapsed >= cfg.max_watch_s:
                outcome = Outcome.RETURN_TIMEOUT
                reason = (f"max_watch_s ({cfg.max_watch_s}s) elapsed without "
                          f"{cfg.presence_threshold_s}s of continuous presence "
                          f"(best streak: {best_streak_s:.1f}s)")
                break

            time.sleep(cfg.poll_interval_s)

        elapsed_total = time.monotonic() - attempt_start

        if outcome == Outcome.ENGAGED:
            trigger_head_servo(pan_target, tilt_target)
        else:
            print(f"Recentering: pan={return_pan:.2f}, tilt={return_tilt:.2f}")
            cam.move_to_pan(return_pan)
            cam.move_to_tilt(return_tilt)

        print(f"Outcome: {outcome.name} — {reason}")
        return EngagementResult(
            outcome=outcome,
            elapsed_s=elapsed_total,
            best_streak_s=best_streak_s,
            distance_m=dist_reading,
            reason=reason,
        )
    finally:
        if cap is not None:
            cap.release()
        if owns_detector:
            detector.close()
