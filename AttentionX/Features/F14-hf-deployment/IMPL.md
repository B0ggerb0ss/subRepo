# F14 — HF Spaces Deployment — Implementation

## Files to Create/Verify Before Deploying

### packages.txt

```
ffmpeg
```

Location: repository root (`/packages.txt`).
HF Spaces reads this file and installs listed apt packages before starting the app.

### requirements.txt

```
gradio>=4.0
faster-whisper>=1.0
librosa>=0.10
mediapipe>=0.10
scenedetect[opencv]>=0.6
opencv-python-headless>=4.8
numpy>=1.24
scipy>=1.11
google-generativeai>=0.5
```

Location: repository root (`/requirements.txt`).

### README.md (HF Spaces Metadata)

```markdown
---
title: AttentionX
emoji: 🎬
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: "4.44.0"
app_file: app.py
pinned: false
---

# AttentionX

AI-powered long-form to short-form video repurposing engine.

Upload a long video → get vertical clips with captions, speaker-centered crop,
and highlight scoring — all in one click.
```

### data/ directories

The `data/temp/` and `data/outputs/` directories must exist at startup.
Either commit empty `.gitkeep` files or create them in `app.py` startup:

```python
# At top of app.py, before demo definition:
from pathlib import Path
Path("data/temp").mkdir(parents=True, exist_ok=True)
Path("data/outputs").mkdir(parents=True, exist_ok=True)
```

## Deployment Command Sequence

```bash
# From local development machine:
git remote add space https://huggingface.co/spaces/{username}/AttentionX
git push space main
```

Monitor build at: `https://huggingface.co/spaces/{username}/AttentionX` → Logs tab.

## Space Secret Configuration

To enable Gemini hooks on the hosted Space:
1. Open Space Settings → Variables and secrets.
2. Add secret: `GEMINI_API_KEY` = your API key.
3. The Space restarts automatically; the key is available via `os.environ`.

## Build Failure Triage

| Symptom                          | Likely Cause                              | Fix                                 |
|----------------------------------|-------------------------------------------|-------------------------------------|
| `ffmpeg: command not found`      | `packages.txt` missing or wrong format    | Verify packages.txt has `ffmpeg`    |
| `ImportError: mediapipe`         | Version mismatch or missing               | Pin version in requirements.txt     |
| `ImportError: scenedetect`       | Missing opencv extra                      | Use `scenedetect[opencv]` in reqs   |
| App crashes on startup           | data/ dirs missing                        | Add mkdir in app.py startup         |
| RAM exceeded during processing   | Large video or large model                | Switch to "base" whisper, reduce input |
| Build timeout                    | Too many heavy dependencies               | Check for redundant packages        |

## Notes

- HF Spaces caches the pip install across builds if `requirements.txt` is unchanged.
  Update requirements.txt with any new dependency additions.
- `opencv-python-headless` is used instead of `opencv-python` to avoid display dependency issues
  in the headless Spaces environment.
- The Space URL format is: `https://{username}-attentionx.hf.space`
