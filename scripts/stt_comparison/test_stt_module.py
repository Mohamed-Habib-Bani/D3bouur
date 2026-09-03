#!/usr/bin/env python3
"""Wiring test for d3bouur_conversation/stt.py — confirms both engines work
*through the new shared interface* (create_stt() + SpeechToText.transcribe()),
not a repeat of compare_stt.py's WER/timing comparison.

Same synthetic-audio approach as compare_stt.py (no mic on this dev machine):
espeak-ng generates reference audio for a few known French phrases, and each
engine is asked to transcribe it via the module's public API — the same path
the real conversation pipeline will call. This is a "does the plumbing work"
check, not a fresh accuracy verdict: rerun compare_stt.py's fuller comparison
(or a version of it) against real recorded speech, on the Pi 5, before
treating either engine's numbers as final. See stt.py's module docstring for
why this deliberately doesn't hard-commit to one engine yet.

Usage:
    python3 test_stt_module.py
"""

import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "d3bouur_conversation"))

from d3bouur_conversation.stt import STTConfig  # noqa: E402
from d3bouur_conversation.stt import create_stt, wav_bytes_to_pcm16  # noqa: E402

# Model paths come from STTConfig.from_env() (ros2_ws/models/{vosk,whisper}/
# defaults + STT_WHISPER_CLI_PATH in .env) — see ros2_ws/models/*/README.md.

PHRASES = [
    "Bonjour, je voudrais des informations sur vos formations.",
    "Quels sont vos horaires d'ouverture ?",
    "Merci beaucoup, au revoir et bonne journée.",
]


def synthesize_wav_bytes(text: str) -> bytes:
    """espeak-ng -> WAV bytes in memory (22050Hz mono 16-bit, its native
    output rate — wav_bytes_to_pcm16() handles the resample to 16kHz)."""
    proc = subprocess.run(
        ["espeak-ng", "-v", "fr", "--stdout", text],
        check=True,
        capture_output=True,
    )
    return proc.stdout


def main() -> None:
    base_config = STTConfig.from_env()

    print("=== Vosk (via create_stt, STTConfig.from_env) ===")
    vosk = create_stt(STTConfig(**{**base_config.__dict__, "engine": "vosk"}))
    for phrase in PHRASES:
        pcm = wav_bytes_to_pcm16(synthesize_wav_bytes(phrase))
        text = vosk.transcribe(pcm)
        print(f"  ref: {phrase!r}\n  got: {text!r}\n")

    print("=== whisper.cpp (via create_stt, STTConfig.from_env) ===")
    whisper = create_stt(STTConfig(**{**base_config.__dict__, "engine": "whisper"}))
    for phrase in PHRASES:
        pcm = wav_bytes_to_pcm16(synthesize_wav_bytes(phrase))
        text = whisper.transcribe(pcm)
        print(f"  ref: {phrase!r}\n  got: {text!r}\n")

    print(
        "Both engines produced text through the shared SpeechToText interface — "
        "wiring confirmed. These are NOT final accuracy/latency numbers: this is "
        "synthetic espeak-ng audio on x86, not real speech on the Pi 5."
    )


if __name__ == "__main__":
    main()
