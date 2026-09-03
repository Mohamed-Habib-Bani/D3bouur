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
import re
import shutil
import subprocess
import wave
from pathlib import Path

from piper import PiperVoice

logger = logging.getLogger(__name__)

# Belt-and-suspenders: the persona instructs the LLM never to use markdown
# (see persona.py), but the 9-question verification run showed that
# instruction isn't consistently followed — one reply came back with bullet
# markers despite it. Piper reads punctuation literally ("asterisque",
# stray dashes read aloud, etc.), so strip common markdown syntax here
# rather than trust the model to always comply.
_MD_BOLD_ITALIC = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)(\S.*?\S|\S)\1")
_MD_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
_MD_NUMBERED = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_MD_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MD_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def strip_markdown(text: str) -> str:
    """Strips common markdown syntax so it never reaches Piper as literal
    punctuation (e.g. "asterisque asterisque" read aloud, or bullet dashes
    spoken as "tiret"). Defensive fallback — see module docstring above."""
    text = _MD_CODE_FENCE.sub("", text)
    text = _MD_INLINE_CODE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_HEADER.sub("", text)
    text = _MD_BULLET.sub("", text)
    text = _MD_NUMBERED.sub("", text)
    text = _MD_BOLD_ITALIC.sub(r"\2", text)
    text = _MD_BOLD_ITALIC.sub(r"\2", text)  # nested emphasis, e.g. **_x_**
    return re.sub(r"[ \t]{2,}", " ", text).strip()

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
        text = strip_markdown(text)
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
