# F14 — Hugging Face Spaces Deployment — Validation

## Gate 10 (Full) Pass Criteria

```
Space build log completes without error                     ✓
Public Space URL loads Gradio UI in browser                 ✓
Upload + generate flow completes on hosted environment      ✓
At least one output clip is downloadable by external user   ✓
FFmpeg available on Space: ffmpeg -version in build log     ✓
No runtime ImportError in Space logs                        ✓
```

## Verification Checklist

### Pre-push verification (local)

- [ ] `python app.py` starts without error locally
- [ ] `packages.txt` exists at repo root with `ffmpeg`
- [ ] `requirements.txt` is complete and tested locally
- [ ] `README.md` has valid HF Spaces YAML frontmatter
- [ ] `data/temp/` and `data/outputs/` created in `app.py` startup code

### Post-push verification (on Spaces)

- [ ] Open Space → Logs tab — confirm build completes without error
- [ ] Open Space → App tab — confirm Gradio UI loads
- [ ] Upload a test video (30–60 seconds)
- [ ] Click Generate Clips
- [ ] Confirm at least one clip is rendered and playable
- [ ] Confirm Download link returns a valid MP4 file
- [ ] Open Space URL in a private browser window (anonymous user) — confirm access works

### Gemini integration on Spaces

- [ ] Open Space Settings → Secrets → add `GEMINI_API_KEY`
- [ ] Generate a clip — confirm hook text appears in UI
- [ ] Remove key from secrets — confirm pipeline still works, hooks empty

## RAM Monitoring

- Upload a 5-minute video and generate clips
- Watch Space resource monitor during processing
- Confirm RAM stays below 14 GB peak (2 GB safety margin)
- If RAM exceeds limit: switch whisper model to "base", reduce frame sampling

## Failure Scenarios and Responses

| Failure                        | Response                                              |
|-------------------------------|-------------------------------------------------------|
| Build error: missing ffmpeg    | Verify packages.txt format — no leading whitespace   |
| OOM kill during processing     | Reduce input size limit in Settings.max_upload_mb    |
| Clip not downloadable          | Check data/outputs/ path is accessible to Gradio     |
| UI loads but generation hangs  | Check Space logs for stuck process; reduce video size |
| 502 error on Space URL         | Space may be sleeping (free tier); click to wake      |
