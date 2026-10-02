# F11 — Gradio UI — Validation

## Gate 10 (Local) Pass Criteria

```
python app.py starts without ImportError or crash           ✓
UI loads in browser at localhost                            ✓
Upload one MP4 → click Generate → output clip returned     ✓
Status log updates during processing                        ✓
Output clip is playable in the Gradio video component       ✓
Download link returns a valid MP4 file                      ✓
No raw traceback shown to user on pipeline error            ✓
```

## Test Cases

### TC-01: Happy path end-to-end

```
Input:    a 2–5 minute MP4 with clear speech and visible speaker
Expected: 1–3 vertical clips returned
          Each clip plays in the browser
          Status shows "Generated N clip(s)."
```

### TC-02: No video uploaded

```
Input:    click Generate without uploading a file
Expected: Status shows "Error: no video uploaded."
          No crash, no exception shown to user
```

### TC-03: Reference clips provided

```
Input:    long video + 2 reference short clips
Expected: pipeline runs with style_profile applied
          Clips still returned normally
```

### TC-04: Pipeline error handling

```
Input:    a corrupt video file (random bytes, .mp4 extension)
Expected: Status shows "Pipeline error: NormalizationError: ..."
          No raw traceback in status box
          No output clips shown
```

### TC-05: Session isolation

```
Input:    two simultaneous submissions (simulate with two browser tabs)
Expected: each submission produces its own output files
          Files in data/temp/{session_1}/ do not interfere with data/temp/{session_2}/
```

### TC-06: App restart

```
Input:    stop and restart python app.py
Expected: data/temp/ and data/outputs/ from previous session do not cause errors
          New submissions work normally
```

## Manual Verification Checklist

- [ ] Open app in Chrome and Firefox — confirm UI renders
- [ ] Upload a test video, click Generate, wait for completion
- [ ] Confirm status log shows stage-by-stage progress
- [ ] Confirm output video plays inline without download
- [ ] Confirm download button returns the same file
- [ ] Check that data/outputs/ contains the generated clip
- [ ] Trigger an error (no upload) — confirm graceful error message
