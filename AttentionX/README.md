---
title: AttentionX
emoji: "🎬"
colorFrom: blue
colorTo: red
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
license: mit
short_description: Turn long-form horizontal video into captioned 9:16 clips in one Gradio app.
---

# AttentionX

AttentionX is a single-process Gradio app that takes one long-form horizontal video and produces up to three short-form vertical clips with captions.

## Local Demo

```bash
pip install -r requirements.txt
python app.py
```

The UI is compact enough to show the full workflow at startup, and when `data/test/test_video.mp4` is present it is preloaded so the demo opens with the complete UI visible.

## Validation

Run the test suite:

```bash
bash run_tests.sh all
```

Run all gates:

```bash
python scripts/run_all_gates.py
```

## Hugging Face Spaces

System dependencies are declared in `packages.txt` and the Space entrypoint is `app.py`.

To push the current branch to a Space:

```bash
export HF_TOKEN=hf_xxx
bash deploy_to_hf.sh your-username/AttentionX
```
