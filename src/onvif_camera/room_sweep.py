"""
room_sweep.py — Panoramic "room awareness" from a fixed-mount PTZ camera.

A fixed-mount PTZ camera only rotates in place — it never translates through
space, so it cannot build a true metric map (no parallax, no depth from
motion). What it CAN build, and what this module builds, is:
  1. A wide panoramic image of the room from the camera's mounting position.
  2. A rough angular map: "a person was seen at approximately pan=62%",
     derived from where in the pan sweep each detection occurred.

This is three independent stages, each usable on its own:

  Stage 1 — capture_sweep()      Drive PTZCamera through a pan (and optional
                                  tilt) sweep, grabbing an OpenCV frame from
                                  the RTSP stream at each stop, tagged with
                                  the dead-reckoning pan/tilt position at
                                  capture time.

  Stage 1 (alt) — capture_sweep_video() + extract_sweep_frames()
                                  Pan smoothly and continuously while
                                  recording video, then sample frames out of
                                  the recording afterward instead of
                                  stopping to shoot at each position. Trades
                                  some per-frame sharpness (the camera is
                                  moving during every frame's exposure) for
                                  a faster, smoother sweep. See
                                  capture_sweep_video()'s docstring for the
                                  full tradeoff. Produces the same
                                  SweepFrame objects capture_sweep() does,
                                  so stages 2-3 don't care which was used.

  Stage 2 — stitch_panorama()    Feed the captured frames to OpenCV's
                                  cv2.Stitcher to produce one wide image.

  Stage 3 — detect_in_sweep()    Run MediaPipe's Object Detector on each
                                  captured frame and report detections by
                                  the pan/tilt position of the frame they
                                  came from — the angular map.

Stage 3 needs `pip install mediapipe`; the import is lazy so stages 1-2 work
without it. See requirements.txt.

WHY MEDIAPIPE FOR DETECTION (over YOLOv8/ultralytics or raw OpenCV DNN)
──────────────────────────────────────────────────────────────────────
This eventually has to run on a Raspberry Pi 5, not just a dev PC, so the
constraint that matters most is CPU-only inference on ARM with no GPU/NPU:

  - MediaPipe Object Detector (EfficientDet-Lite0, int8) — chosen. Google
    publishes official aarch64 wheels (64-bit Raspberry Pi OS required —
    no 32-bit ARM wheels exist), the model is a ~4-6 MB quantized .tflite
    file, and it's built specifically for CPU-only edge/mobile inference.
    Detection here only runs on a handful of sweep frames per pass, not a
    live video stream, so its accuracy (solid but below YOLOv8) is more
    than sufficient — the frames aren't going anywhere.
  - YOLOv8n (ultralytics) — better accuracy, but pulls in torch (large
    install, slow first-run) and is noticeably slower per-frame on Pi5 CPU
    without exporting to ncnn/tflite first (extra pipeline step). Worth
    revisiting later if MediaPipe's accuracy proves insufficient.
  - OpenCV DNN + MobileNet-SSD — lightest dependency footprint (just cv2,
    already a hard dependency here), but the model is a 2016-era Caffe
    architecture with weaker accuracy, and the weight files aren't
    pip-installed — they have to be hunted down and placed manually.

ADAPTING TO YOUR CAMERA
────────────────────────
- Requires a PTZCamera that is already connect()ed AND calibrate()d (or has
  full_pan_time / pan_pos set manually) — see ptz.py. Sweep positions are
  expressed as the same 0.0-1.0 fraction PTZCamera itself uses; there's no
  true degree calibration (no absolute encoder), so "pan=62%" is the
  honest unit. Pass total_pan_degrees to print_angular_map() if you've
  separately measured the camera's real pan range and want a rough degree
  estimate printed alongside.
- num_frames / pan_range control sweep density. Stitching needs real visual
  overlap between adjacent frames to find matching features — if
  stitch_panorama() fails with "not enough overlap", increase num_frames
  (smaller pan step) rather than widening pan_range.
"""

import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from ptz import PTZCamera


# ─── Capture ────────────────────────────────────────────────────────────────

DEFAULT_CONNECT_RETRIES     = 3
DEFAULT_CONNECT_RETRY_DELAY = 2.0   # seconds, matches ptz.py / mic.py
DEFAULT_FRAME_RETRIES       = 2     # extra attempts after the first, per frame
DEFAULT_FRAME_RETRY_DELAY   = 1.5   # seconds


class SweepError(RuntimeError):
    """Base class for room_sweep failures."""


class SweepConnectionError(SweepError):
    """The RTSP video stream could not be opened or a frame could not be read."""


@dataclass
class SweepFrame:
    pan_pos:  float        # dead-reckoning pan position 0.0-1.0 at capture time
    tilt_pos: float        # dead-reckoning tilt position 0.0-1.0 at capture time
    image:    np.ndarray   # BGR frame, as returned by cv2.VideoCapture


def _open_capture(
    rtsp_url: str,
    max_retries: int = DEFAULT_CONNECT_RETRIES,
    retry_delay: float = DEFAULT_CONNECT_RETRY_DELAY,
) -> cv2.VideoCapture:
    for attempt in range(1, max_retries + 1):
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # best-effort; not all backends honor it
        if cap.isOpened():
            return cap
        cap.release()
        print(f"VideoCapture attempt {attempt}/{max_retries} failed to open {rtsp_url}")
        if attempt < max_retries:
            time.sleep(retry_delay)

    raise SweepConnectionError(
        f"Could not open RTSP video stream at {rtsp_url} after {max_retries} attempts."
    )


def _grab_fresh_frame(
    cap: cv2.VideoCapture,
    rtsp_url: str,
    flush_frames: int,
    max_retries: int,
    retry_delay: float,
) -> Tuple[np.ndarray, cv2.VideoCapture]:
    """
    Return a frame captured AFTER any buffered pre-move frames are discarded,
    plus the (possibly reopened) VideoCapture to keep using.

    cv2.VideoCapture keeps an internal frame buffer, so the first read() after
    a pan/tilt move can return a stale frame from before the camera stopped —
    grab() cheaply discards decoded frames without the cost of retrieve()ing
    them, so we drain a few before taking the one we actually keep.

    If grabbing/retrieving fails outright (stream dropped), reopens the
    capture and retries — same reconnect-on-failure shape as ptz.py.
    """
    last_reason = "unknown error"
    for attempt in range(1, max_retries + 2):   # first try + retries
        ok = True
        for _ in range(flush_frames):
            if not cap.grab():
                ok = False
                last_reason = "grab() failed while flushing buffered frames"
                break
        if ok:
            ret, frame = cap.retrieve()
            if ret and frame is not None:
                return frame, cap
            last_reason = "retrieve() returned no frame"

        print(f"Frame capture attempt {attempt} failed ({last_reason}); reconnecting...")
        cap.release()
        try:
            cap = _open_capture(rtsp_url, max_retries=1, retry_delay=retry_delay)
        except SweepConnectionError:
            pass   # let the outer loop's attempt counter decide when to give up
        time.sleep(retry_delay)

    raise SweepConnectionError(
        f"Could not capture a video frame from {rtsp_url} after repeated attempts "
        f"— last reason: {last_reason}"
    )


def capture_sweep(
    cam: PTZCamera,
    rtsp_url: str,
    num_frames: int = 8,
    pan_range: Tuple[float, float] = (0.0, 1.0),
    tilt_position: Optional[float] = None,
    settle_s: float = 1.0,
    flush_frames: int = 5,
    frame_retries: int = DEFAULT_FRAME_RETRIES,
    frame_retry_delay: float = DEFAULT_FRAME_RETRY_DELAY,
    connect_retries: int = DEFAULT_CONNECT_RETRIES,
    connect_retry_delay: float = DEFAULT_CONNECT_RETRY_DELAY,
    output_dir: Optional[str] = None,
) -> List[SweepFrame]:
    """
    Sweep `cam` across `pan_range` in `num_frames` steps, capturing one video
    frame at each stop via OpenCV on the RTSP stream. Optionally move to a
    fixed tilt first (for now the sweep itself is pan-only at a single tilt —
    call this once per tilt level if you want multiple rows).

    Requires `cam` to already be connect()ed and calibrated (full_pan_time
    and pan_pos set — see PTZCamera.calibrate() / reset_pan() in ptz.py).

    If output_dir is given, each frame is also saved as a JPEG named with its
    pan/tilt position, useful for inspecting a sweep or re-running detection
    later without re-driving the camera.

    Raises SweepConnectionError if the video stream can't be opened or a
    frame can't be captured after retries. Raises RuntimeError if the camera
    isn't calibrated/positioned.
    """
    if cam.full_pan_time is None or cam.pan_pos is None:
        raise RuntimeError(
            "Camera pan is not calibrated/positioned — call cam.connect(), "
            "cam.calibrate() (or set full_pan_time manually), and cam.reset_pan() first."
        )
    if num_frames < 2:
        raise ValueError("num_frames must be >= 2 — stitching needs overlapping frames.")

    if tilt_position is not None:
        if cam.full_tilt_time is None or cam.tilt_pos is None:
            raise RuntimeError(
                "Camera tilt is not calibrated/positioned — cannot move_to_tilt(). "
                "Omit tilt_position to sweep at the current tilt instead."
            )
        print(f"Moving to tilt={tilt_position:.0%} before sweep...")
        cam.move_to_tilt(tilt_position)

    out_dir = Path(output_dir) if output_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    pan_positions = np.linspace(pan_range[0], pan_range[1], num_frames)

    cap = _open_capture(rtsp_url, connect_retries, connect_retry_delay)
    frames: List[SweepFrame] = []
    try:
        for i, pos in enumerate(pan_positions):
            print(f"[{i + 1}/{num_frames}] Moving to pan={pos:.1%} ...")
            cam.move_to_pan(float(pos))
            time.sleep(settle_s)   # let motion blur settle before capturing

            image, cap = _grab_fresh_frame(
                cap, rtsp_url, flush_frames, frame_retries, frame_retry_delay
            )
            tilt_pos = cam.tilt_pos if cam.tilt_pos is not None else 0.0
            sf = SweepFrame(pan_pos=cam.pan_pos, tilt_pos=tilt_pos, image=image)
            frames.append(sf)
            print(f"    captured {image.shape[1]}x{image.shape[0]} frame "
                  f"at pan={sf.pan_pos:.1%} tilt={sf.tilt_pos:.1%}")

            if out_dir:
                fname = out_dir / f"frame_{i:02d}_pan{sf.pan_pos:.2f}_tilt{sf.tilt_pos:.2f}.jpg"
                cv2.imwrite(str(fname), image)
    finally:
        cap.release()

    return frames


# ─── Continuous-video capture (Stage 1, alternative to capture_sweep) ───────

def capture_sweep_video(
    cam: PTZCamera,
    rtsp_url: str,
    video_path: str,
    pan_range: Tuple[float, float] = (0.0, 1.0),
    tilt_position: Optional[float] = None,
    speed: Optional[float] = None,
    margin: float = 1.05,
    connect_retries: int = DEFAULT_CONNECT_RETRIES,
    connect_retry_delay: float = DEFAULT_CONNECT_RETRY_DELAY,
) -> Tuple[Path, float, float, float]:
    """
    Continuously pan from pan_range[0] to pan_range[1] while recording video
    from the RTSP stream — an alternative to capture_sweep()'s stop-move-
    stop-shoot pattern for a smooth, single-pass sweep. Feed the return
    value straight into extract_sweep_frames() to pull tagged SweepFrames
    out of the recording afterward.

    TRADEOFF vs capture_sweep(): capture_sweep() fully stops before each
    shot, so (once settled) every frame has ~zero angular velocity — as
    sharp as the lighting allows. Here the camera moves throughout every
    frame's exposure, so every frame carries motion blur proportional to
    (angular speed x exposure time). There's no exposure-time control wired
    up here (no ONVIF Imaging service), so the only lever against blur is
    `speed` — pass something noticeably slower than you'd use for stop-and-
    shoot capture. In exchange: no per-position settle delay (capture_sweep's
    settle_s x num_frames of dead time doesn't exist here), a genuinely
    smooth sweep with no stop/restart jitter, and frame density becomes a
    free choice made at extract_sweep_frames() time rather than something
    that has to be decided (and re-driven) up front.

    Requires cam to be calibrated and positioned (same as capture_sweep()).
    Moves to pan_range[0] (and tilt_position, if given) with a normal
    stop-and-settle move first, so the continuous leg starts from a known
    position — only the pan_range[0] -> pan_range[1] traversal is continuous.
    """
    if cam.full_pan_time is None or cam.pan_pos is None:
        raise RuntimeError(
            "Camera pan is not calibrated/positioned — call cam.connect(), "
            "cam.calibrate() (or set full_pan_time manually), and cam.reset_pan()/home() first."
        )
    if tilt_position is not None:
        if cam.full_tilt_time is None or cam.tilt_pos is None:
            raise RuntimeError(
                "Camera tilt is not calibrated/positioned — cannot move_to_tilt()."
            )
        print(f"Moving to tilt={tilt_position:.0%} before the sweep...")
        cam.move_to_tilt(tilt_position)

    spd = speed if speed is not None else cam.speed
    print(f"Moving to pan={pan_range[0]:.0%} (sweep start)...")
    cam.move_to_pan(pan_range[0])

    fraction  = pan_range[1] - pan_range[0]
    pan_dir   = 1.0 if fraction >= 0 else -1.0
    duration  = margin * cam.duration_for_pan_fraction(abs(fraction), speed=spd)

    cap = _open_capture(rtsp_url, connect_retries, connect_retry_delay)
    fps    = cap.get(cv2.CAP_PROP_FPS) or 15.0   # RTSP often doesn't report a reliable fps
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out = Path(video_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out), fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise SweepError(f"Could not open VideoWriter for {out} ({width}x{height} @ {fps}fps)")

    print(f"Recording continuous {duration:.1f}s pan sweep to {out} "
          f"(pan {pan_range[0]:.0%} -> {pan_range[1]:.0%} at speed={spd})...")

    move_error: list = []

    def move_thread():
        try:
            cam.move_raw(pan_dir * spd, 0.0, duration)
        except Exception as e:
            move_error.append(e)

    t = threading.Thread(target=move_thread, daemon=True)
    t_start = time.monotonic()
    t.start()

    frame_count = 0
    try:
        while time.monotonic() - t_start < duration:
            ret, frame = cap.read()
            if not ret:
                print("  Warning: stream read failed mid-recording — stopping capture early "
                      "with whatever was recorded so far.")
                break
            writer.write(frame)
            frame_count += 1
    finally:
        writer.release()
        cap.release()
        t.join(timeout=duration + 5)

    if move_error:
        raise SweepConnectionError(
            f"Pan move failed during video sweep: {move_error[0]}"
        ) from move_error[0]

    cam.pan_pos = pan_range[1]   # move_raw() doesn't dead-reckon on its own; the sweep ran as commanded

    if frame_count == 0:
        raise SweepConnectionError(f"No frames were captured to {out} — check the RTSP stream.")

    print(f"Recorded {frame_count} frames to {out}")
    return out, pan_range[0], pan_range[1], duration


def extract_sweep_frames(
    video_path: str,
    pan_start: float,
    pan_end: float,
    duration_s: float,
    num_frames: int = 8,
    tilt_position: float = 0.0,
    output_dir: Optional[str] = None,
) -> List[SweepFrame]:
    """
    Sample num_frames evenly-spaced frames out of a video recorded by
    capture_sweep_video(), tagging each with an estimated pan position via
    linear interpolation between pan_start and pan_end over duration_s — the
    same constant-angular-velocity assumption full_pan_time/calibrate()
    already rely on elsewhere in this codebase.

    tilt_position is a fixed value applied to every extracted frame, since
    capture_sweep_video() only pans continuously — tilt is set once before
    recording starts.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SweepError(f"Could not open recorded video {video_path}")

    frames: List[SweepFrame] = []
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        if total_frames <= 0:
            raise SweepError(f"{video_path} reports no frames — recording may have failed.")

        out_dir = Path(output_dir) if output_dir else None
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

        frame_indices = np.linspace(0, total_frames - 1, num_frames).astype(int)
        for i, idx in enumerate(frame_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ret, image = cap.read()
            if not ret or image is None:
                print(f"  Warning: could not read frame {idx}/{total_frames} — skipping.")
                continue

            t = idx / fps
            time_fraction = min(1.0, t / duration_s) if duration_s > 0 else 0.0
            pan_pos = pan_start + (pan_end - pan_start) * time_fraction

            sf = SweepFrame(pan_pos=pan_pos, tilt_pos=tilt_position, image=image)
            frames.append(sf)
            print(f"  extracted frame {i + 1}/{num_frames} at pan={pan_pos:.1%} (video t={t:.1f}s)")

            if out_dir:
                fname = out_dir / f"frame_{i:02d}_pan{pan_pos:.2f}_tilt{tilt_position:.2f}.jpg"
                cv2.imwrite(str(fname), image)
    finally:
        cap.release()

    if not frames:
        raise SweepError(f"No frames could be extracted from {video_path}")

    return frames


# ─── Stitching ──────────────────────────────────────────────────────────────

_STITCH_STATUS_MESSAGES = {
    cv2.Stitcher_ERR_NEED_MORE_IMGS: (
        "Not enough overlap between frames to stitch. Try more frames "
        "(smaller pan step) or a narrower pan_range in capture_sweep()."
    ),
    cv2.Stitcher_ERR_HOMOGRAPHY_EST_FAIL: (
        "Could not find enough matching features between frames. Likely a "
        "low-texture or poorly lit room, or too large a pan step between "
        "captures — try more frames."
    ),
    cv2.Stitcher_ERR_CAMERA_PARAMS_ADJUST_FAIL: (
        "Camera parameter estimation failed, often from inconsistent "
        "exposure/lighting between frames (e.g. captured while panning past "
        "a window) — try capturing in more uniform lighting."
    ),
}


def stitch_panorama(frames: Sequence[SweepFrame], mode: int = cv2.Stitcher_PANORAMA) -> np.ndarray:
    """
    Stitch captured frames into one panoramic image using OpenCV's Stitcher.

    Raises SweepError with a specific diagnosis if stitching fails — the
    raw cv2.Stitcher status code alone isn't actionable on its own.
    """
    if len(frames) < 2:
        raise ValueError("Need at least 2 frames to stitch a panorama.")

    stitcher = cv2.Stitcher_create(mode)
    status, pano = stitcher.stitch([f.image for f in frames])

    if status != cv2.Stitcher_OK:
        hint = _STITCH_STATUS_MESSAGES.get(status, "No further diagnosis available.")
        raise SweepError(f"Panorama stitching failed (status {status}). {hint}")

    return pano


def save_panorama(pano: np.ndarray, path: str) -> Path:
    """Save a stitched panorama to disk. Raises IOError if the write fails."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out), pano):
        raise IOError(f"cv2.imwrite failed to save panorama to {out}")
    print(f"Saved panorama ({pano.shape[1]}x{pano.shape[0]}) to {out}")
    return out


# ─── Detection (Stage 3) ─────────────────────────────────────────────────────

DEFAULT_MODEL_PATH = Path(__file__).parent / "models" / "efficientdet_lite0.tflite"
DEFAULT_MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/int8/1/efficientdet_lite0.tflite"
)


@dataclass
class AngularDetection:
    label:       str
    confidence:  float
    pan_pos:     float                    # 0.0-1.0, from the source frame
    tilt_pos:    float
    frame_index: int
    bbox:        Tuple[int, int, int, int]  # (x, y, width, height) in the source frame


def ensure_model(model_path: Path = DEFAULT_MODEL_PATH, url: str = DEFAULT_MODEL_URL) -> Path:
    """
    Return a path to the EfficientDet-Lite0 .tflite model, downloading it
    from Google's model zoo on first use if it isn't already on disk.
    """
    model_path = Path(model_path)
    if model_path.exists():
        return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Detection model not found at {model_path}; downloading from {url} ...")
    try:
        urllib.request.urlretrieve(url, model_path)
    except Exception as e:
        raise RuntimeError(
            f"Could not download detection model to {model_path}: {e}\n"
            f"Download it manually from {url} and place it at that path."
        ) from e

    print(f"Saved model ({model_path.stat().st_size:,} bytes) to {model_path}")
    return model_path


def detect_in_sweep(
    frames: Sequence[SweepFrame],
    model_path: Optional[str] = None,
    score_threshold: float = 0.5,
    target_labels: Optional[Sequence[str]] = None,
) -> List[AngularDetection]:
    """
    Run MediaPipe's Object Detector on each captured frame and return one
    AngularDetection per detection found, tagged with the pan/tilt position
    of the frame it came from.

    target_labels, if given, restricts detection to those COCO category
    names (e.g. ["person"]) — cheaper and less noisy than filtering after
    the fact, since MediaPipe applies the allowlist during inference.

    Raises RuntimeError if mediapipe isn't installed (the import is lazy so
    capture_sweep()/stitch_panorama() work without it).
    """
    try:
        import mediapipe as mp
    except ImportError as e:
        raise RuntimeError(
            "mediapipe is not installed — required for detect_in_sweep().\n"
            "Install with: pip install mediapipe\n"
            "On Raspberry Pi OS this requires the 64-bit OS; mediapipe does "
            "not publish 32-bit ARM wheels."
        ) from e

    resolved_model_path = ensure_model(Path(model_path) if model_path else DEFAULT_MODEL_PATH)

    BaseOptions           = mp.tasks.BaseOptions
    ObjectDetector         = mp.tasks.vision.ObjectDetector
    ObjectDetectorOptions  = mp.tasks.vision.ObjectDetectorOptions
    VisionRunningMode      = mp.tasks.vision.RunningMode

    options = ObjectDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(resolved_model_path)),
        running_mode=VisionRunningMode.IMAGE,   # independent frames, not a live stream
        score_threshold=score_threshold,
        category_allowlist=list(target_labels) if target_labels else None,
    )

    detections: List[AngularDetection] = []
    with ObjectDetector.create_from_options(options) as detector:
        for i, sf in enumerate(frames):
            rgb = cv2.cvtColor(sf.image, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = detector.detect(mp_image)

            for det in result.detections:
                category = det.categories[0]
                box = det.bounding_box
                detections.append(AngularDetection(
                    label=category.category_name,
                    confidence=category.score,
                    pan_pos=sf.pan_pos,
                    tilt_pos=sf.tilt_pos,
                    frame_index=i,
                    bbox=(box.origin_x, box.origin_y, box.width, box.height),
                ))

    return detections


def build_angular_map(
    detections: Sequence[AngularDetection],
    cluster_tolerance: float = 0.08,
) -> List[dict]:
    """
    Collapse detections into distinct angular sightings by greedily merging
    same-label detections whose pan_pos is within cluster_tolerance of each
    other — sweep frames overlap by design, so the same person is typically
    seen in 2-3 adjacent frames and would otherwise be reported 2-3 times.
    Each cluster keeps its highest-confidence detection's position.
    """
    clusters: List[dict] = []
    for d in sorted(detections, key=lambda d: d.pan_pos):
        match = next(
            (c for c in clusters
             if c["label"] == d.label and abs(c["pan_pos"] - d.pan_pos) <= cluster_tolerance),
            None,
        )
        if match is None:
            clusters.append({
                "label": d.label, "pan_pos": d.pan_pos, "tilt_pos": d.tilt_pos,
                "confidence": d.confidence, "frame_index": d.frame_index, "count": 1,
            })
            continue
        match["count"] += 1
        if d.confidence > match["confidence"]:
            match.update(pan_pos=d.pan_pos, tilt_pos=d.tilt_pos,
                         confidence=d.confidence, frame_index=d.frame_index)
    return clusters


def print_angular_map(
    detections: Sequence[AngularDetection],
    cluster_tolerance: float = 0.08,
    total_pan_degrees: Optional[float] = None,
) -> None:
    """Pretty-print the clustered angular map. See build_angular_map()."""
    clusters = build_angular_map(detections, cluster_tolerance)
    if not clusters:
        print("No detections.")
        return

    print(f"Angular map — {len(clusters)} distinct sighting(s):")
    for c in sorted(clusters, key=lambda c: c["pan_pos"]):
        loc = f"pan={c['pan_pos']:.1%}"
        if total_pan_degrees:
            loc += f" (~{c['pan_pos'] * total_pan_degrees:.0f} deg)"
        print(f"  {c['label']:<12} {loc}  tilt={c['tilt_pos']:.1%}  "
              f"confidence={c['confidence']:.2f}  "
              f"seen in {c['count']} frame(s), best=frame {c['frame_index']}")
