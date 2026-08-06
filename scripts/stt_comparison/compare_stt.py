#!/usr/bin/env python3
"""
D3BOUUR STT comparison: Vosk (small French model) vs whisper.cpp (base,
multilingual).

Both are realistic size classes for real-time use on a Pi 5 — Vosk's
"-fr-0.22" small model and whisper's "base" model are both in the tens-to-
low-hundreds-of-MB range, not the large/accuracy-optimized variants that
would be too slow on-device.

Test audio: this dev machine (WSL2) has no microphone, so ground-truth audio
is synthesized with espeak-ng from known French text (see PHRASES below).
That means this test measures "can each engine transcribe clean, single-
voice French audio, and how fast" — not real-world accuracy against a real
human voice, accent, or background noise. Treat the WER numbers here as a
sanity check + relative comparison, not a final verdict. Re-run against real
recorded speech once a mic is wired up (and again on the Pi 5 itself, since
this machine is x86, not ARM, so absolute latency numbers won't transfer).

Setup this script depends on (not committed — see README.md in this folder):
  - Vosk: `pip3 install --user vosk` + vosk-model-small-fr-0.22 unzipped
  - whisper.cpp: built from source (cmake), + ggml-base.bin downloaded

Usage:
    python3 compare_stt.py
"""

import subprocess
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
from vosk import KaldiRecognizer, Model

SCRIPT_DIR = Path(__file__).parent

# Local paths outside the repo — large downloaded/built artifacts live in the
# scratchpad, not in git. Adjust these if you re-run setup elsewhere (e.g. on
# the Pi 5, where whisper.cpp would need its own ARM build).
SCRATCHPAD = Path(
    "/tmp/claude-1000/-home-mrkra-d3bouur/dc3ec592-b1ef-46e7-814f-a3105a6f6809/scratchpad"
)
VOSK_MODEL_PATH = SCRATCHPAD / "models" / "vosk-model-small-fr-0.22"
WHISPER_CLI = SCRATCHPAD / "whisper.cpp" / "build" / "bin" / "whisper-cli"
WHISPER_MODEL = SCRATCHPAD / "whisper.cpp" / "models" / "ggml-base.bin"

AUDIO_DIR = SCRIPT_DIR / "test_audio"
TARGET_SAMPLE_RATE = 16000

# Ground-truth phrases: realistic things a visitor might say TO the robot
# (STT transcribes the visitor, not D3BOUUR itself — that's the TTS test).
PHRASES = [
    "Bonjour, je voudrais des informations sur vos formations.",
    "Est-ce que vous proposez des stages pour les étudiants ?",
    "Quels sont vos horaires d'ouverture ?",
    "Pouvez-vous m'indiquer où sont les toilettes s'il vous plaît ?",
    "Merci beaucoup, au revoir et bonne journée.",
]


def synthesize_reference_audio(text: str, out_path: Path) -> None:
    """espeak-ng outputs 22050Hz mono 16-bit PCM; resample to 16kHz for
    Vosk/whisper.cpp, which both expect 16kHz mono PCM16 input."""
    raw_path = out_path.with_suffix(".raw.wav")
    subprocess.run(
        ["espeak-ng", "-v", "fr", "-w", str(raw_path), text],
        check=True,
        capture_output=True,
    )

    with wave.open(str(raw_path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        src_rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

    gcd = np.gcd(TARGET_SAMPLE_RATE, src_rate)
    up, down = TARGET_SAMPLE_RATE // gcd, src_rate // gcd
    resampled = resample_poly(samples.astype(np.float32), up, down)
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)

    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_SAMPLE_RATE)
        w.writeframes(resampled.tobytes())

    raw_path.unlink()


def transcribe_vosk(model: Model, wav_path: Path) -> tuple[str, float]:
    with wave.open(str(wav_path), "rb") as w:
        audio = w.readframes(w.getnframes())

    start = time.perf_counter()
    recognizer = KaldiRecognizer(model, TARGET_SAMPLE_RATE)
    recognizer.AcceptWaveform(audio)
    result = recognizer.FinalResult()
    elapsed = time.perf_counter() - start

    import json

    text = json.loads(result).get("text", "")
    return text, elapsed


def transcribe_whisper(wav_path: Path) -> tuple[str, float]:
    start = time.perf_counter()
    proc = subprocess.run(
        [
            str(WHISPER_CLI),
            "-m", str(WHISPER_MODEL),
            "-f", str(wav_path),
            "-l", "fr",
            "-nt",  # no timestamps
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    text = proc.stdout.strip()
    return text, elapsed


def normalize(text: str) -> list[str]:
    keep = "abcdefghijklmnopqrstuvwxyzàâäéèêëïîôöùûüçœ "
    cleaned = "".join(c if c.lower() in keep else " " for c in text.lower())
    return cleaned.split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Standard WER via word-level Levenshtein distance / len(reference)."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0

    d = [[0] * (len(hyp) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        d[i][0] = i
    for j in range(len(hyp) + 1):
        d[0][j] = j
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = 1 + min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1])
    return d[len(ref)][len(hyp)] / len(ref)


def main() -> None:
    AUDIO_DIR.mkdir(exist_ok=True)

    print(f"Loading Vosk model from {VOSK_MODEL_PATH} ...")
    vosk_model = Model(str(VOSK_MODEL_PATH))

    rows = []
    for i, phrase in enumerate(PHRASES, start=1):
        wav_path = AUDIO_DIR / f"phrase_{i}.wav"
        print(f"\n[{i}/{len(PHRASES)}] Synthesizing reference audio: {phrase!r}")
        synthesize_reference_audio(phrase, wav_path)

        vosk_text, vosk_time = transcribe_vosk(vosk_model, wav_path)
        vosk_wer = word_error_rate(phrase, vosk_text)
        print(f"  Vosk    [{vosk_time*1000:6.1f} ms, WER {vosk_wer:.2f}]: {vosk_text}")

        whisper_text, whisper_time = transcribe_whisper(wav_path)
        whisper_wer = word_error_rate(phrase, whisper_text)
        print(f"  Whisper [{whisper_time*1000:6.1f} ms, WER {whisper_wer:.2f}]: {whisper_text}")

        rows.append(
            {
                "phrase": phrase,
                "vosk_text": vosk_text,
                "vosk_time": vosk_time,
                "vosk_wer": vosk_wer,
                "whisper_text": whisper_text,
                "whisper_time": whisper_time,
                "whisper_wer": whisper_wer,
            }
        )

    avg_vosk_time = sum(r["vosk_time"] for r in rows) / len(rows)
    avg_vosk_wer = sum(r["vosk_wer"] for r in rows) / len(rows)
    avg_whisper_time = sum(r["whisper_time"] for r in rows) / len(rows)
    avg_whisper_wer = sum(r["whisper_wer"] for r in rows) / len(rows)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = SCRIPT_DIR / f"results_{timestamp}.md"
    with open(report_path, "w") as f:
        f.write("# D3BOUUR STT comparison — Vosk vs whisper.cpp\n\n")
        f.write(f"Run: {datetime.now().isoformat()}\n\n")
        f.write(
            "**Caveats:** run on a WSL2 x86 dev machine, not the Pi 5 — absolute "
            "latency will not transfer, only the relative comparison. Ground-truth "
            "audio is espeak-ng-synthesized (no mic available), so WER reflects "
            "clean single-voice audio, not real accented/noisy speech.\n\n"
        )
        f.write("| # | Ground truth | Vosk transcript | Vosk ms | Vosk WER | Whisper transcript | Whisper ms | Whisper WER |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(rows, start=1):
            f.write(
                f"| {i} | {r['phrase']} | {r['vosk_text']} | {r['vosk_time']*1000:.1f} | "
                f"{r['vosk_wer']:.2f} | {r['whisper_text']} | {r['whisper_time']*1000:.1f} | "
                f"{r['whisper_wer']:.2f} |\n"
            )
        f.write(
            f"\n**Averages** — Vosk: {avg_vosk_time*1000:.1f} ms, WER {avg_vosk_wer:.2f} | "
            f"Whisper: {avg_whisper_time*1000:.1f} ms, WER {avg_whisper_wer:.2f}\n"
        )
        f.write(
            "\nNote: whisper.cpp's timing includes reloading the model from disk on "
            "every call (whisper-cli is a one-shot CLI); a persistent process "
            "(whisper-server, or the library API kept warm) would drop this fixed "
            "cost. Vosk's model is loaded once and reused across phrases, which is "
            "the realistic in-robot setup for both.\n"
        )

    print(f"\nReport written to {report_path}")
    print(
        f"\nAverages — Vosk: {avg_vosk_time*1000:.1f} ms, WER {avg_vosk_wer:.2f} | "
        f"Whisper: {avg_whisper_time*1000:.1f} ms, WER {avg_whisper_wer:.2f}"
    )


if __name__ == "__main__":
    main()
