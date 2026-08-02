#!/usr/bin/env python3
"""Interactive manual test for the D3BOUUR conversation brain.

Run from this directory (no colcon build needed — Python resolves the
d3bouur_conversation/ subpackage relative to this script):

    python3 demo_chat.py

Type a message and press Enter. Ctrl+D (or Ctrl+C) to quit. The provider
that actually answered (openrouter/ollama) and its latency are shown with
each reply, so a fallback happening live is visible, not hidden.
"""

import logging

from d3bouur_conversation import AllProvidersFailedError, ConversationBrain, KnowledgeBase

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main() -> None:
    knowledge_base = KnowledgeBase()
    print(f"Knowledge base: {len(knowledge_base)} entries loaded from {knowledge_base.index_path}\n")
    brain = ConversationBrain(knowledge_base=knowledge_base)
    print("D3BOUUR conversation brain — interactive test. Ctrl+D to quit.\n")
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

        print(f"D3BOUUR [{result.provider}, {result.elapsed:.2f}s]: {result.text}\n")


if __name__ == "__main__":
    main()
