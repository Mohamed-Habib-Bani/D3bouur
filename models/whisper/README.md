# whisper.cpp STT model + CLI

Only `ggml-base.bin` (the model weights) lives here — it's architecture-
independent, so it's tracked the same way as the Piper/Vosk models. It is
**not** committed to git (large binary, gitignored via `ros2_ws/.gitignore`);
to reproduce:

```bash
git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git <somewhere>
bash <somewhere>/models/download-ggml-model.sh base
cp <somewhere>/models/ggml-base.bin ros2_ws/models/whisper/
```

The `whisper-cli` **binary** is deliberately not kept here — unlike the model
weights, it's a compiled artifact tied to the machine it was built on (this
was first built on x86 WSL2; the Pi 5 needs its own native ARM build, same
cmake steps run on the Pi itself — the CPU backend auto-detects the
architecture). Build it wherever's convenient and point
`STT_WHISPER_CLI_PATH` (in `.env`) at the resulting `build/bin/whisper-cli`:

```bash
cd <somewhere>
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

Used by `d3bouur_conversation/stt.py`'s `WhisperCppSTT`, and by the earlier
comparison at `scripts/stt_comparison/compare_stt.py`.
