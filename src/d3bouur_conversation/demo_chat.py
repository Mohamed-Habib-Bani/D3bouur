#!/usr/bin/env python3
"""Interactive manual test for the D3BOUUR conversation brain + TTS.

Run from this directory (no colcon build needed — Python resolves the
d3bouur_conversation/ subpackage relative to this script):

    python3 demo_chat.py

Type a message and press Enter. Ctrl+D (or Ctrl+C) to quit. The provider
that actually answered (openrouter/ollama) and its latency are shown with
each reply, so a fallback happening live is visible, not hidden. Each reply
is also synthesized with Piper and saved to spoken_replies/; playback is
best-effort (needs `aplay` + a working audio output device, which this dev
machine doesn't have — see PiperTTS.speak's return value).
"""

import logging
from pathlib import Path

from d3bouur_conversation import AllProvidersFailedError, ConversationBrain, KnowledgeBase, PiperTTS

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

REPLIES_DIR = Path(__file__).parent / "spoken_replies"


def main() -> None:
    knowledge_base = KnowledgeBase()
    print(f"Knowledge base: {len(knowledge_base)} entries loaded from {knowledge_base.index_path}\n")
    brain = ConversationBrain(knowledge_base=knowledge_base)
    tts = PiperTTS()
    REPLIES_DIR.mkdir(exist_ok=True)
    print("D3BOUUR conversation brain — interactive test. Ctrl+D to quit.\n")

    turn = 0
    while True:
        try:
            user_input = input("Vous: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue

        try:
            result = brain.chat(user_input)
        except AllProvidersFailedError as exc:
            print(f"D3BOUUR: (aucune réponse — les deux fournisseurs ont échoué : {exc})\n")
            continue

        print(f"D3BOUUR [{result.provider}, {result.elapsed:.2f}s]: {result.text}")

        turn += 1
        out_path = REPLIES_DIR / f"turn_{turn:03d}.wav"
        played = tts.speak(result.text, out_path)
        status = "played" if played else f"saved to {out_path} (no playback device)"
        print(f"  [TTS: {status}]\n")


if __name__ == "__main__":
    main()
