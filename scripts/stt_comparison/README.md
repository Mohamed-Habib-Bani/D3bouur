# STT comparison — Vosk vs whisper.cpp

`compare_stt.py` needs a Vosk model and a whisper.cpp build/model that are
**not** committed to this repo (large binaries). To reproduce:

```bash
# Vosk
pip3 install --user vosk scipy numpy
curl -sL -o vosk-model-small-fr-0.22.zip \
    https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip
unzip vosk-model-small-fr-0.22.zip -d <models-dir>

# whisper.cpp
git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
bash ./models/download-ggml-model.sh base
```

Then edit `VOSK_MODEL_PATH`, `WHISPER_CLI`, and `WHISPER_MODEL` at the top of
`compare_stt.py` to point at wherever you put them.

On the Pi 5, whisper.cpp needs its own ARM build (the same `cmake` steps,
run natively on the Pi — CPU backend auto-detects the architecture).

Ground-truth audio is synthesized with `espeak-ng` (no mic on the dev
machine this was first run on) — see the caveats note at the top of
`compare_stt.py` and in each `results_*.md` output.
