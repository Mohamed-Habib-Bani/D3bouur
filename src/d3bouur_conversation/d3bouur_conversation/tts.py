"""Piper text-to-speech for D3BOUUR's spoken replies.

Chosen over espeak-ng after a listening comparison (see
scripts/tts_comparison/) — Piper was clearly more natural, at the cost of
being roughly 50x slower to generate. The voice is loaded once here and
reused across calls; scripts/tts_comparison/compare_tts.py deliberately
reloads it per call instead, to give espeak-ng's CLI a fair apples-to-apples
timing comparison — that reload cost is exactly what a live conversation
can't afford to pay on every reply.
"""

import io
import logging
import os
import shutil
import subprocess
import wave
from pathlib import Path

from piper import PiperVoice

logger = logging.getLogger(__name__)

# models/ lives at the workspace root (ros2_ws/models/piper/), not inside
# this package — it's a large, gitignored binary shared across scripts, not
# package source. See ros2_ws/models/piper/README.md to download it.
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VOICE_MODEL = _WORKSPACE_ROOT / "models" / "piper" / "fr_FR-siwis-medium.onnx"


class PiperTTS:
    """Wraps a loaded Piper voice: text in, WAV out (and best-effort playback)."""

    def __init__(self, model_path: Path | None = None) -> None:
        model_path = model_path or Path(
            os.environ.get("D3BOUUR_PIPER_MODEL_PATH", DEFAULT_VOICE_MODEL)
        )
        if not model_path.exists():
            raise FileNotFoundError(
                f"Piper voice model not found at {model_path} — see "
                f"{model_path.parent}/README.md to download it."
            )
        logger.info("Loading Piper voice from %s", model_path)
        self.voice = PiperVoice.load(str(model_path))

    def synthesize_bytes(self, text: str) -> bytes:
        """Synthesizes `text` to WAV bytes in memory — no disk I/O. Used by
        d3bouur_interface's /api/speak endpoint, which returns the audio
        straight to the browser for playback + mouth-sync analysis."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self.voice.synthesize_wav(text, wav_file)
        return buffer.getvalue()

    def synthesize_to_file(self, text: str, out_path: Path) -> Path:
        out_path.write_bytes(self.synthesize_bytes(text))
        return out_path

    def speak(self, text: str, out_path: Path) -> bool:
        """Synthesizes `text` to `out_path` and attempts to play it.

        Returns True if playback actually happened, False if only the file
        was written — expected on machines with no audio output device
        (e.g. this WSL2 dev machine, until real speaker hardware is wired
        up on the robot).
        """
        self.synthesize_to_file(text, out_path)

        if shutil.which("aplay") is None:
            logger.warning(
                "aplay not found — saved %s but could not play it (no audio "
                "output configured on this machine)",
                out_path,
            )
            return False

        try:
            subprocess.run(["aplay", "-q", str(out_path)], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "aplay failed to play %s: %s", out_path, exc.stderr.decode(errors="replace")
            )
            return False
