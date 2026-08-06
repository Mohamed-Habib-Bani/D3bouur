# Piper voice model

Not committed (large binary, gitignored via `ros2_ws/.gitignore`). To
reproduce:

```bash
pip3 install --user piper-tts
python3 -m piper.download_voices fr_FR-siwis-medium --download-dir ros2_ws/models/piper
```

Chosen after a listening comparison against espeak-ng (see
`scripts/tts_comparison/`) — Piper was clearly more natural. This is the
voice `d3bouur_conversation/tts.py` loads by default.

On the Pi 5, this same `.onnx` + `.onnx.json` pair can be copied over
directly (ONNX models aren't architecture-specific) — no need to
re-download, just re-run `onnxruntime` install for ARM.
