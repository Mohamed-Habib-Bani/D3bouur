# Vosk STT model

Not committed (large binary directory, gitignored via `ros2_ws/.gitignore`).
To reproduce:

```bash
pip3 install --user vosk
curl -sL -o vosk-model-small-fr-0.22.zip \
    https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip
unzip vosk-model-small-fr-0.22.zip -d ros2_ws/models/vosk/
rm vosk-model-small-fr-0.22.zip
```

This is the small French model from the earlier STT comparison
(`scripts/stt_comparison/compare_stt.py`) — `d3bouur_conversation/stt.py`'s
`VoskSTT` loads it by default. Model data is architecture-independent (Kaldi
graph/weight files, no compiled code), so this same directory can be copied
straight to the Pi 5 — only the `vosk` Python package itself needs its own
per-machine `pip install`.
