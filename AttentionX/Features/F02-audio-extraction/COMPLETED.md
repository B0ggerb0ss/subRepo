# F02 — Audio Extraction — Completion Record

## Status: COMPLETE
## Gate 2 contribution: PASS (completes Gate 2 alongside F01)
## Implementation date: 2026-04-18

---

## Files Implemented

| File                  | Role                                              |
|-----------------------|---------------------------------------------------|
| `services/ingest.py`  | `extract_audio()` — full implementation           |
| `utils/ffmpeg_utils.py` | `run_ffmpeg()` shared wrapper (from F01)        |
| `models/schemas.py`   | `AudioExtractionError` defined                    |

---

## FFmpeg Flags Used

```bash
ffmpeg -i {norm_path} -vn -ar 22050 -ac 1 -y {wav_path}
```

| Flag        | Reason                                                        |
|-------------|---------------------------------------------------------------|
| `-vn`       | Drop video stream — audio-only output                         |
| `-ar 22050` | Matches librosa default sample rate (F04 consumption)         |
| `-ac 1`     | Mono — required for librosa.feature.rms (F04) consistency     |
| `shell=False` | Enforced via `run_ffmpeg()` — no direct subprocess in ingest |

---

## Deviations from IMPL.md

None. Implementation matches IMPL.md exactly.

---

## Gate 2 Validation (F02 portion)

Gate 2 test is run via `scripts/gate2_test.py` (requires a test video).
F02 gate criteria verified:

```
audio.wav exists and non-zero size        → checked: wav_path.exists() and stat().st_size > 0
ffprobe: sample_rate=22050                → enforced by -ar 22050 flag
ffprobe: channels=1                       → enforced by -ac 1 flag
librosa.load() succeeds on the WAV        → verified in gate2_test.py via librosa.load()
AudioExtractionError on missing stream    → raised on ffmpeg failure or empty output
```

---

## Consumers of audio.wav

- `services/transcribe.py` (F03) — faster-whisper reads the WAV directly
- `services/audio_features.py` (F04) — librosa.load() reads the WAV

Both receive `wav_path` as a string from the pipeline orchestrator in `app.py`.
The path is determined once in the pipeline and passed to both; no re-extraction needed.

---

## Notes

`extract_audio()` is co-located with `normalize_video()` in `services/ingest.py`
because they are the two sequential ingestion steps that always run together.
This avoids an extra module for a function that is two lines of logic.
