# TTS comparison — espeak-ng vs Piper

`compare_tts.py` needs a Piper voice model that is **not** committed to this
repo (large binary). To reproduce:

```bash
sudo apt-get install -y espeak-ng
pip3 install --user piper-tts
python3 -m piper.download_voices fr_FR-siwis-medium --download-dir <models-dir>
```

Then edit `PIPER_MODEL` at the top of `compare_tts.py` to point at wherever
you put it.

Test text comes from the *real* conversation brain (Ollama running locally,
`llama3.2:3b` + `nomic-embed-text` pulled) — not hand-written — so the script
also depends on that being set up, same as `demo_chat.py` in
`src/d3bouur_conversation/`.

Output WAV files land in `output_audio/` (gitignored) — listen to them
yourself to judge naturalness; the script only measures generation speed,
it does not score audio quality.
