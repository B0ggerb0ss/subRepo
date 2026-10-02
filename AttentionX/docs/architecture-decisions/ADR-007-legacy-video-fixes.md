# ADR-007 — Legacy video workflow fixes

Each change has a regression test reproducing the audit's observation (`tests/unit/test_legacy_regressions.py`, `tests/integration/test_legacy_video_fixes.py`). The five-value `run_pipeline` contract is unchanged.

| Defect (audit) | Fix |
|---|---|
| Snap could exceed `max_dur` | end re-clamped to `start + max_dur` after snapping |
| Next window absorbed silence | a window starts at its first segment's own start |
| Center coords used as "no face" | `FaceTrack.detected` mask; crop mean and visibility use it |
| Captions dropped tokens / overran clip | every token emitted; ≤2-line cues with proportional timing, clamped to clip |
| Narrow portrait crop crashed | aspect-fit: crop when wider than 9:16, otherwise scale + pad |
| Stream-copy trim ran long (1.625 s for 1.5 s) | single re-encode pass with input seeking; ±1 frame |
| Silent video rejected; empty ASR fatal | silent sources accepted (ASR/energy skipped, output without audio); empty ASR = no speech |
| Whisper rebuilt each run; eager import | lazy import + per-process model cache; app imports without faster-whisper |
| `mp.solutions` absent in MediaPipe 1.0.1 → faces never detected | MediaPipe Tasks BlazeFace with provisioned model; `detector_status` distinguishes "missing" from "no face" |
| Sentence-initial capital counted as entity | only non-initial capitals / numbers count |

TC-03 in `Features/F01-input-normalization` ("silent video raises") is superseded; `normalize_video(require_audio=True)` keeps the strict behavior available.
