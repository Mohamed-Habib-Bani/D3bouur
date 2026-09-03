"""D3BOUUR speech-to-text: a swappable engine abstraction, same pattern as
llm_router.py's provider abstraction (LLMConfig + per-provider methods).

Why swappable rather than picking one now: the earlier comparison
(scripts/stt_comparison/compare_stt.py) ran Vosk (small French model) against
whisper.cpp (base, multilingual) on espeak-ng-synthesized audio, on this x86
WSL2 dev machine — not real speech, not the Pi 5. Vosk was more accurate on
that synthetic audio, whisper.cpp was faster, but neither ranking is trusted
to hold on a real voice or real ARM hardware (see that script's own caveats).
Rather than hard-commit to one engine on weak evidence, both are wired in
behind one interface and selected by config — like `LLMConfig.primary_provider`
picks ollama vs. openrouter, `STTConfig.engine` picks vosk vs. whisper. Re-run
the comparison with real mic audio on the Pi 5, then just flip `engine` (or
STT_ENGINE in .env) once there's a real answer — no caller code changes.

Unlike the LLM router, there's no automatic fallback between engines here:
STT engines don't have a "primary/secondary, try the other on failure" story
the way a network-dependent LLM provider does — a missing model file or a
failed transcription isn't something reasonable to silently swap into a
completely different engine while a visitor is mid-sentence. One engine is
selected explicitly; a failure is raised as STTError for the caller to handle.

Both engines expect the same input shape: mono 16-bit PCM audio at 16kHz
(raw samples, no WAV header) — the sample rate both Vosk and whisper.cpp's
models are trained/tuned for. `wav_bytes_to_pcm16()` below converts a WAV
file (e.g. from espeak-ng test audio, or however the real mic capture ends
up handing off audio) into that shape.
"""

import json
import logging
import os
import subprocess
import tempfile
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.signal import resample_poly

from .llm_router import _default_env_path, _load_env_file

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000

# models/ lives at the workspace root (ros2_ws/models/), same convention as
# tts.py's DEFAULT_VOICE_MODEL — large, gitignored binaries shared across
# scripts, not package source. See ros2_ws/models/vosk/README.md and
# ros2_ws/models/whisper/README.md to download them.
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VOSK_MODEL_PATH = _WORKSPACE_ROOT / "models" / "vosk" / "vosk-model-small-fr-0.22"
DEFAULT_WHISPER_MODEL_PATH = _WORKSPACE_ROOT / "models" / "whisper" / "ggml-base.bin"
# No default for the whisper-cli binary itself — unlike the model weights,
# it's a compiled artifact tied to the machine it was built on (see
# ros2_ws/models/whisper/README.md), so it must be set via
# STT_WHISPER_CLI_PATH / STTConfig.whisper_cli_path explicitly.


class STTError(Exception):
    """The configured STT engine failed to produce a transcription."""


class SpeechToText(ABC):
    """Common interface both engines implement: raw 16-bit mono PCM in,
    transcribed text out. Swapping VoskSTT for WhisperCppSTT (or back) never
    requires touching caller code — see create_stt()."""

    @abstractmethod
    def transcribe(self, pcm16_audio: bytes) -> str:
        """`pcm16_audio` is raw mono 16-bit PCM at TARGET_SAMPLE_RATE (16kHz)
        — no WAV header. Returns the transcribed text, "" if the engine heard
        silence/nothing intelligible. Raises STTError on an engine failure
        (not on the "heard nothing" case, which is a normal outcome, not a
        failure)."""


def wav_bytes_to_pcm16(wav_bytes: bytes, target_rate: int = TARGET_SAMPLE_RATE) -> bytes:
    """Converts WAV file bytes (any mono 16-bit PCM sample rate) to raw PCM16
    at `target_rate`. Mirrors compare_stt.py's resampling step — needed here
    because espeak-ng outputs 22050Hz and real mic capture may not land on
    16kHz either, but both STT engines expect 16kHz."""
    import io

    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(
                f"expected mono 16-bit PCM, got {w.getnchannels()} channel(s) / "
                f"{w.getsampwidth() * 8}-bit"
            )
        src_rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

    if src_rate == target_rate:
        return samples.tobytes()

    gcd = np.gcd(target_rate, src_rate)
    up, down = target_rate // gcd, src_rate // gcd
    resampled = resample_poly(samples.astype(np.float32), up, down)
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()


@dataclass
class STTConfig:
    """All tunable knobs in one place, mirroring LLMConfig — override any of
    these when constructing create_stt(config=...) without touching the
    engine implementations."""

    # "vosk" or "whisper" — which engine create_stt() instantiates.
    engine: str = "vosk"

    vosk_model_path: Optional[Path] = None
    whisper_cli_path: Optional[Path] = None
    whisper_model_path: Optional[Path] = None
    # whisper.cpp is multilingual; Vosk's model is French-only by construction
    # (vosk-model-small-fr-0.22), so only whisper needs a language knob.
    whisper_language: str = "fr"

    sample_rate: int = TARGET_SAMPLE_RATE

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "STTConfig":
        _load_env_file(env_file or _default_env_path())
        vosk_path = os.environ.get("STT_VOSK_MODEL_PATH")
        whisper_cli = os.environ.get("STT_WHISPER_CLI_PATH")
        whisper_model = os.environ.get("STT_WHISPER_MODEL_PATH")
        return cls(
            engine=os.environ.get("STT_ENGINE", "vosk"),
            vosk_model_path=Path(vosk_path) if vosk_path else DEFAULT_VOSK_MODEL_PATH,
            whisper_cli_path=Path(whisper_cli) if whisper_cli else None,
            whisper_model_path=Path(whisper_model) if whisper_model else DEFAULT_WHISPER_MODEL_PATH,
            whisper_language=os.environ.get("STT_WHISPER_LANGUAGE", "fr"),
        )


class VoskSTT(SpeechToText):
    """Vosk (small French model, vosk-model-small-fr-0.22 in the earlier
    comparison) — offline, pure-Python bindings around Kaldi, no subprocess.
    The model is loaded once here and reused across calls, same reasoning as
    PiperTTS loading its voice once (tts.py) — reloading a model per call is
    exactly the cost a live conversation can't afford to pay on every turn."""

    def __init__(self, model_path: Path, sample_rate: int = TARGET_SAMPLE_RATE) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"Vosk model not found at {model_path} — download e.g. "
                f"vosk-model-small-fr-0.22 from https://alphacephei.com/vosk/models "
                f"and point STT_VOSK_MODEL_PATH at the unzipped folder."
            )
        from vosk import KaldiRecognizer, Model  # local import: optional dependency

        logger.info("Loading Vosk model from %s", model_path)
        self._model = Model(str(model_path))
        self._recognizer_cls = KaldiRecognizer
        self.sample_rate = sample_rate

    def transcribe(self, pcm16_audio: bytes) -> str:
        try:
            recognizer = self._recognizer_cls(self._model, self.sample_rate)
            recognizer.AcceptWaveform(pcm16_audio)
            result = json.loads(recognizer.FinalResult())
        except Exception as exc:  # Vosk/Kaldi internals raise plain Exception on bad input
            raise STTError(f"Vosk transcription failed: {exc}") from exc
        return result.get("text", "").strip()


class WhisperCppSTT(SpeechToText):
    """whisper.cpp (base model, multilingual) via its `whisper-cli` binary —
    same subprocess-per-call approach as compare_stt.py's transcribe_whisper,
    so the earlier timing numbers stay comparable to this integration. Each
    call pays a fresh model-load cost (whisper-cli is a one-shot CLI, no
    persistent process) — see the module docstring in compare_stt.py; a
    persistent whisper-server would drop this if per-call latency becomes a
    problem on the Pi 5."""

    def __init__(
        self,
        cli_path: Path,
        model_path: Path,
        language: str = "fr",
        sample_rate: int = TARGET_SAMPLE_RATE,
    ) -> None:
        if not cli_path.exists():
            raise FileNotFoundError(
                f"whisper.cpp CLI not found at {cli_path} — build whisper.cpp "
                f"(cmake) and point STT_WHISPER_CLI_PATH at build/bin/whisper-cli."
            )
        if not model_path.exists():
            raise FileNotFoundError(
                f"whisper.cpp model not found at {model_path} — download e.g. "
                f"ggml-base.bin via whisper.cpp's models/download-ggml-model.sh "
                f"and point STT_WHISPER_MODEL_PATH at it."
            )
        self.cli_path = cli_path
        self.model_path = model_path
        self.language = language
        self.sample_rate = sample_rate

    def transcribe(self, pcm16_audio: bytes) -> str:
        # whisper-cli takes a WAV file, not raw PCM or stdin — write the
        # incoming PCM16 back out as a throwaway mono WAV, same shape
        # compare_stt.py fed it.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with wave.open(tmp, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.sample_rate)
                w.writeframes(pcm16_audio)

        try:
            proc = subprocess.run(
                [
                    str(self.cli_path),
                    "-m", str(self.model_path),
                    "-f", str(tmp_path),
                    "-l", self.language,
                    "-nt",  # no timestamps — plain transcript text on stdout
                ],
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise STTError(f"whisper.cpp failed to start: {exc}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        if proc.returncode != 0:
            raise STTError(f"whisper.cpp exited {proc.returncode}: {proc.stderr[:200]}")

        return proc.stdout.strip()


def create_stt(config: Optional[STTConfig] = None) -> SpeechToText:
    """Factory: builds whichever engine `config.engine` selects. This is the
    single place caller code needs — the conversation pipeline should depend
    on the SpeechToText interface, not on VoskSTT/WhisperCppSTT directly, so
    flipping STT_ENGINE in .env (or config.engine) is the only change needed
    to swap engines once real-hardware testing picks a winner."""
    config = config or STTConfig.from_env()

    if config.engine == "vosk":
        if config.vosk_model_path is None:
            raise ValueError("STTConfig.vosk_model_path (or STT_VOSK_MODEL_PATH) is required for engine='vosk'")
        return VoskSTT(config.vosk_model_path, config.sample_rate)

    if config.engine == "whisper":
        if config.whisper_cli_path is None or config.whisper_model_path is None:
            raise ValueError(
                "STTConfig.whisper_cli_path and whisper_model_path (or "
                "STT_WHISPER_CLI_PATH / STT_WHISPER_MODEL_PATH) are required for engine='whisper'"
            )
        return WhisperCppSTT(
            config.whisper_cli_path, config.whisper_model_path, config.whisper_language, config.sample_rate
        )

    raise ValueError(f"unknown STT engine {config.engine!r} — expected 'vosk' or 'whisper'")
