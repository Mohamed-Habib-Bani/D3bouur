"""
mic.py — Camera microphone access via the RTSP stream's audio track.

The camera's RTSP stream carries both H264 video and an audio track from
the built-in microphone, even though the camera's ONVIF profile may not
formally declare any AudioSourceConfiguration.  ffprobe/ffmpeg talk directly
to the RTSP URL and discover the audio track regardless.

REQUIREMENTS
────────────
- ffmpeg (includes ffprobe and ffplay) must be installed separately and
  available on the system PATH.  It is NOT pip-installable.
  Download: https://ffmpeg.org/download.html
  Windows quick install: winget install Gyan.FFmpeg

RTSP URL FORMAT (typical)
──────────────────────────
  rtsp://<user>:<password>@<ip>:<rtsp_port>/live/ch00_0
  rtsp_port is usually 554 (standard RTSP) — distinct from the ONVIF port.

FEATURES NOT INCLUDED
──────────────────────
- Speaker / two-way audio: The camera's speaker is not accessible via RTSP
  or ONVIF on the reference camera.  It requires the proprietary binary
  protocol on port 8089/8800, which uses AES encryption with a key embedded
  in the phone app's native library (not solved).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


# Retry defaults mirror ptz.py's connect() — a momentary WiFi drop shouldn't
# require every caller to write its own retry loop.
DEFAULT_CONNECT_RETRIES     = 3
DEFAULT_CONNECT_RETRY_DELAY = 2.0   # seconds
DEFAULT_RECORD_RETRIES      = 1     # extra attempts after the first, for record_clip
DEFAULT_RECORD_RETRY_DELAY  = 2.0   # seconds
LISTEN_RETRY_DELAY          = 2.0   # seconds between listen_live reconnect attempts


class MicConnectionError(RuntimeError):
    """RTSP audio stream could not be reached (probe, record, or live listen)."""


def _require_ffmpeg(tool: str = "ffmpeg") -> str:
    """Return the path to the tool or raise a clear error."""
    path = shutil.which(tool)
    if path is None:
        raise RuntimeError(
            f"'{tool}' not found in PATH.\n"
            "Install ffmpeg: https://ffmpeg.org/download.html\n"
            "Windows: winget install Gyan.FFmpeg  (then restart your terminal)"
        )
    return path


# ─── Stream probing ───────────────────────────────────────────────────────────

def probe_stream(
    rtsp_url: str,
    timeout_s: int = 10,
    max_retries: int = DEFAULT_CONNECT_RETRIES,
    retry_delay: float = DEFAULT_CONNECT_RETRY_DELAY,
) -> dict:
    """
    Use ffprobe to inspect the RTSP stream and return a summary dict:
      {
        "video": {"codec": str, "width": int, "height": int, "fps": str} or None,
        "audio": {"codec": str, "sample_rate": int, "channels": int} or None,
        "raw_streams": [...]   # full ffprobe stream objects
      }

    Retries up to `max_retries` times with `retry_delay` seconds between
    attempts — a probe is a one-shot connection attempt, so it gets the same
    momentary-drop tolerance as ptz.py's connect().

    Raises MicConnectionError if ffprobe cannot connect after all attempts.
    """
    ffprobe = _require_ffmpeg("ffprobe")
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-rtsp_transport", "tcp",
        "-timeout", str(timeout_s * 1_000_000),  # ffmpeg timeout is in microseconds
        rtsp_url,
    ]

    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 5)
        except subprocess.TimeoutExpired as e:
            last_exc = e
            print(f"ffprobe attempt {attempt}/{max_retries} timed out after {timeout_s}s")
        else:
            if result.returncode == 0:
                data    = json.loads(result.stdout)
                streams = data.get("streams", [])
                summary = {"video": None, "audio": None, "raw_streams": streams}
                for s in streams:
                    if s.get("codec_type") == "video" and summary["video"] is None:
                        summary["video"] = {
                            "codec":  s.get("codec_name"),
                            "width":  s.get("width"),
                            "height": s.get("height"),
                            "fps":    s.get("r_frame_rate"),
                        }
                    elif s.get("codec_type") == "audio" and summary["audio"] is None:
                        summary["audio"] = {
                            "codec":       s.get("codec_name"),
                            "sample_rate": int(s.get("sample_rate", 0)),
                            "channels":    s.get("channels"),
                        }
                return summary

            last_exc = RuntimeError(result.stderr.strip())
            print(f"ffprobe attempt {attempt}/{max_retries} failed: {result.stderr.strip()}")

        if attempt < max_retries:
            time.sleep(retry_delay)

    raise MicConnectionError(
        f"Could not probe RTSP stream at {rtsp_url} after {max_retries} attempts "
        "— is the camera reachable and the URL/credentials correct?"
    ) from last_exc


def print_stream_info(rtsp_url: str) -> None:
    """Probe and pretty-print stream details.  Good for first-time setup verification."""
    print(f"Probing {rtsp_url} ...")
    try:
        info = probe_stream(rtsp_url)
    except MicConnectionError as e:
        print(f"  FAILED — {e}")
        return
    v = info["video"]
    a = info["audio"]
    print(f"  Video: {v['codec'].upper()} {v['width']}x{v['height']} @ {v['fps']} fps"
          if v else "  Video: none")
    print(f"  Audio: {a['codec'].upper()} {a['sample_rate']} Hz {a['channels']}ch"
          if a else "  Audio: none — microphone not available on this stream")


# ─── Recording ────────────────────────────────────────────────────────────────

def record_clip(
    rtsp_url: str,
    output_path: str,
    seconds: float = 5.0,
    sample_rate: int = 16000,
    channels: int = 1,
    max_retries: int = DEFAULT_RECORD_RETRIES,
    retry_delay: float = DEFAULT_RECORD_RETRY_DELAY,
) -> Path:
    """
    Record `seconds` of audio from the camera microphone into a WAV file.

    Args:
        rtsp_url:    Full RTSP URL including credentials.
        output_path: Destination WAV file path.
        seconds:     How many seconds to record.
        sample_rate: Output sample rate in Hz (default 16000).
        channels:    Output channel count (default 1 = mono).
        max_retries: Extra full-recording attempts if the stream drops or
                     never connects (default 1, i.e. try twice total). A
                     fixed-length recording has no persistent connection to
                     reconnect mid-flight, so on failure we just redo the
                     whole clip rather than resuming a partial one.
        retry_delay: Seconds to wait before retrying.

    Returns:
        Path to the saved WAV file.

    Raises:
        MicConnectionError if ffmpeg fails or no audio track is found after
        all attempts. Any partial/empty output file is removed before raising.
    """
    ffmpeg = _require_ffmpeg("ffmpeg")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg,
        "-y",                          # overwrite output without asking
        "-rtsp_transport", "tcp",
        "-timeout",        "10000000", # 10 s connection timeout (microseconds)
        "-i",              rtsp_url,
        "-vn",                         # drop video track
        "-t",              str(seconds),
        "-acodec",         "pcm_s16le", # uncompressed 16-bit PCM
        "-ar",             str(sample_rate),
        "-ac",             str(channels),
        str(out),
    ]

    total_attempts = max_retries + 1
    last_error: Optional[str] = None
    for attempt in range(1, total_attempts + 1):
        print(f"Recording {seconds:.1f}s clip → {out} ... (attempt {attempt}/{total_attempts})")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 20)
        except subprocess.TimeoutExpired:
            last_error = f"ffmpeg timed out after {seconds + 20:.0f}s — stream likely stalled mid-recording"
        else:
            if result.returncode != 0:
                last_error = f"ffmpeg failed:\n{result.stderr[-1000:]}"
            elif not out.exists() or out.stat().st_size == 0:
                last_error = "ffmpeg completed but output file is empty — no audio track, or stream dropped mid-recording?"
            else:
                print(f"Saved {out.stat().st_size:,} bytes to {out}")
                return out

        print(f"  attempt {attempt} failed: {last_error}")
        out.unlink(missing_ok=True)   # don't leave a partial/empty file behind
        if attempt < total_attempts:
            time.sleep(retry_delay)

    raise MicConnectionError(
        f"Could not record from {rtsp_url} after {total_attempts} attempts.\n"
        f"Last error: {last_error}"
    )


# ─── Live listening ───────────────────────────────────────────────────────────

def listen_live(rtsp_url: str, retry_delay: float = LISTEN_RETRY_DELAY) -> None:
    """
    Open a live audio monitor of the camera microphone.
    Plays through the default system audio output.
    Blocks until the user presses Ctrl+C.

    Uses ffplay which is part of the ffmpeg distribution.

    Unlike record_clip (a bounded operation where failing clean is right),
    this is an open-ended "watch until I say stop" call — with -nodisp there's
    no window for the user to close, so any ffplay exit that isn't a
    KeyboardInterrupt means the stream ended or dropped, not that the user is
    done. So it auto-reconnects and keeps listening, the same way ptz.py's
    heartbeat keeps a move alive through a momentary drop, until the user
    actually asks it to stop.
    """
    ffplay = _require_ffmpeg("ffplay")

    cmd = [
        ffplay,
        "-rtsp_transport", "tcp",
        "-i",              rtsp_url,
        "-vn",                         # audio-only (no video window)
        "-nodisp",                     # no graphical display
        "-autoexit",                   # exit when stream ends
    ]

    print("Listening to camera microphone.  Press Ctrl+C to stop.")
    try:
        while True:
            result = subprocess.run(cmd)
            if result.returncode != 0:
                print(f"Stream dropped (ffplay exit code {result.returncode}); "
                      f"reconnecting in {retry_delay:.0f}s... (Ctrl+C to stop)")
            else:
                print(f"Stream ended; reconnecting in {retry_delay:.0f}s... (Ctrl+C to stop)")
            time.sleep(retry_delay)
    except KeyboardInterrupt:
        print("\nStopped.")


def play_wav(path: str) -> None:
    """
    Play back a previously recorded WAV file through the system speakers.
    Uses the platform's built-in audio: winsound on Windows, aplay on Linux.

    Fails gracefully with a clear message if the file is missing or the
    platform's audio player isn't available, instead of crashing.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    if sys.platform == "win32":
        import winsound
        try:
            winsound.PlaySound(str(p), winsound.SND_FILENAME)
        except RuntimeError as e:
            raise RuntimeError(f"Could not play {p}: {e}") from e
    else:
        aplay = shutil.which("aplay")
        if aplay is None:
            raise RuntimeError(
                f"'aplay' not found in PATH — cannot play {p}.\n"
                "Install alsa-utils, e.g. 'sudo apt install alsa-utils' on Debian/Ubuntu/Raspberry Pi OS."
            )
        result = subprocess.run([aplay, str(p)], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"aplay failed to play {p}:\n{result.stderr.strip()}")
