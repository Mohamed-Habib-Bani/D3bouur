#!/usr/bin/env python3
"""Rebuild the D3BOUUR knowledge base index from knowledge/*.md and *.txt files.

Run this whenever content in knowledge/ is added, edited, or removed:

    python3 build_index.py

Reads every file in knowledge/, embeds each one via Ollama, and writes
knowledge_index.json (rebuilt from scratch each run, not appended to).

With no files in knowledge/, this produces an empty index — the knowledge
base's normal, fully-supported starting state, not an error condition.
"""

from pathlib import Path

from d3bouur_conversation import KnowledgeBase

PACKAGE_ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = PACKAGE_ROOT / "knowledge"
INDEX_PATH = PACKAGE_ROOT / "knowledge_index.json"


def main() -> None:
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    files = sorted(KNOWLEDGE_DIR.glob("*.md")) + sorted(KNOWLEDGE_DIR.glob("*.txt"))

    kb = KnowledgeBase(index_path=INDEX_PATH)
    kb.clear()

    for path in files:
        text = path.read_text().strip()
        if not text:
            print(f"skipping {path.name} (empty file)")
            continue
        print(f"embedding {path.name}...")
        kb.add_document(source=path.name, text=text)

    kb.save()
    print(f"\nWrote {len(kb)} entries to {INDEX_PATH}")


if __name__ == "__main__":
    main()
