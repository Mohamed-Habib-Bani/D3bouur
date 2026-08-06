#!/usr/bin/env python3
"""
D3BOUUR TTS comparison: espeak-ng vs Piper (fr_FR-siwis-medium).

Test text is not hand-written — this script calls the *actual* conversation
brain (d3bouur_conversation.ConversationBrain, via local Ollama, no API key
needed) with a handful of representative visitor questions, and uses D3BOUUR's
genuine generated French replies as the TTS input. That's the real distribution
of text this pipeline will need to speak, not a guess at it.

For each reply, both engines synthesize audio and generation time is measured.
Naturalness itself is NOT scored automatically — that's a "listen and judge"
call. WAV files are written to output_audio/ for you to play.

Setup this script depends on (not committed — see README.md in this folder):
  - espeak-ng: `sudo apt-get install -y espeak-ng`
  - Piper: `pip3 install --user piper-tts` + fr_FR-siwis-medium voice
  - Ollama running locally with llama3.2:3b and nomic-embed-text pulled
    (this is the project's already-chosen primary LLM provider)

Usage:
    python3 compare_tts.py
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONVERSATION_PKG_DIR = SCRIPT_DIR.parent.parent / "src" / "d3bouur_conversation"
sys.path.insert(0, str(CONVERSATION_PKG_DIR))

from d3bouur_conversation import AllProvidersFailedError, ConversationBrain, KnowledgeBase  # noqa: E402

SCRATCHPAD = Path(
    "/tmp/claude-1000/-home-mrkra-d3bouur/dc3ec592-b1ef-46e7-814f-a3105a6f6809/scratchpad"
)
PIPER_MODEL = SCRATCHPAD / "models" / "piper" / "fr_FR-siwis-medium.onnx"

OUTPUT_DIR = SCRIPT_DIR / "output_audio"

# Representative visitor questions — same style as the LLM comparison
# (ros2_ws/scripts/llm_comparison/compare_llms.py), picked to produce short,
# spoken-style replies typical of a live demo interaction.
QUESTIONS = [
    "Bonjour !",
    "Qu'est-ce que fait AcaROBOTICS ?",
    "Quelles formations proposez-vous ?",
    "Avez-vous des événements prévus bientôt ?",
    "Merci, au revoir.",
]


def generate_test_texts() -> list[tuple[str, str]]:
    """Runs the real conversation brain and returns [(question, reply_text)]."""
    print(f"Loading knowledge base + conversation brain (Ollama, local) ...")
    knowledge_base = KnowledgeBase()
    brain = ConversationBrain(knowledge_base=knowledge_base)

    pairs = []
    for question in QUESTIONS:
        try:
            result = brain.chat(question)
        except AllProvidersFailedError as exc:
            print(f"  SKIPPED {question!r}: both providers failed ({exc})")
            continue
        print(f"  [{result.provider}, {result.elapsed:.2f}s] {question!r} -> {result.text!r}")
        pairs.append((question, result.text))
    return pairs


def synthesize_espeak(text: str, out_path: Path) -> float:
    start = time.perf_counter()
    subprocess.run(
        ["espeak-ng", "-v", "fr", "-w", str(out_path), text],
        check=True,
        capture_output=True,
    )
    return time.perf_counter() - start


def synthesize_piper(text: str, out_path: Path) -> float:
    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "-m", "piper", "-m", str(PIPER_MODEL), "-f", str(out_path)],
        input=text,
        check=True,
        capture_output=True,
        text=True,
    )
    return time.perf_counter() - start


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    pairs = generate_test_texts()
    if not pairs:
        print("No replies generated — nothing to synthesize.")
        return

    rows = []
    for i, (question, text) in enumerate(pairs, start=1):
        espeak_path = OUTPUT_DIR / f"reply_{i}_espeak.wav"
        piper_path = OUTPUT_DIR / f"reply_{i}_piper.wav"

        print(f"\n[{i}/{len(pairs)}] Synthesizing: {text!r}")
        espeak_time = synthesize_espeak(text, espeak_path)
        print(f"  espeak-ng [{espeak_time*1000:6.1f} ms] -> {espeak_path.name}")
        piper_time = synthesize_piper(text, piper_path)
        print(f"  Piper     [{piper_time*1000:6.1f} ms] -> {piper_path.name}")

        rows.append(
            {
                "question": question,
                "text": text,
                "espeak_time": espeak_time,
                "espeak_path": espeak_path.name,
                "piper_time": piper_time,
                "piper_path": piper_path.name,
            }
        )

    avg_espeak = sum(r["espeak_time"] for r in rows) / len(rows)
    avg_piper = sum(r["piper_time"] for r in rows) / len(rows)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = SCRIPT_DIR / f"results_{timestamp}.md"
    with open(report_path, "w") as f:
        f.write("# D3BOUUR TTS comparison — espeak-ng vs Piper (fr_FR-siwis-medium)\n\n")
        f.write(f"Run: {datetime.now().isoformat()}\n\n")
        f.write(
            "**Caveats:** run on a WSL2 x86 dev machine, not the Pi 5 — absolute "
            "generation speed will not transfer, only the relative comparison. "
            "Naturalness is not scored here; listen to the WAV files in "
            "`output_audio/` and judge for yourself.\n\n"
        )
        f.write("| # | Visitor question | D3BOUUR reply (real, from ConversationBrain) | espeak ms | espeak file | Piper ms | Piper file |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(rows, start=1):
            f.write(
                f"| {i} | {r['question']} | {r['text']} | {r['espeak_time']*1000:.1f} | "
                f"{r['espeak_path']} | {r['piper_time']*1000:.1f} | {r['piper_path']} |\n"
            )
        f.write(f"\n**Averages** — espeak-ng: {avg_espeak*1000:.1f} ms | Piper: {avg_piper*1000:.1f} ms\n")

    print(f"\nReport written to {report_path}")
    print(f"Audio files in {OUTPUT_DIR}")
    print(f"\nAverages — espeak-ng: {avg_espeak*1000:.1f} ms | Piper: {avg_piper*1000:.1f} ms")


if __name__ == "__main__":
    main()
