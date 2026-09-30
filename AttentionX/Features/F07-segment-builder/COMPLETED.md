# F07 — Candidate Segment Builder — Completion Record

## Status: COMPLETE
## Implementation date: 2026-04-18

---

## Files Implemented

| File                       | Role                                                            |
|----------------------------|-----------------------------------------------------------------|
| `services/segment_builder.py` | `build_candidates()` + all helper functions — full implementation |
| `models/schemas.py`        | `CandidateSegment`                                              |

---

## Implementation Notes

- `_chunk_transcript`: greedy grouping — accumulates segments until `target_dur` reached, caps at `max_dur`
- `_energy_in_window`: max `rms_score` of overlapping peaks (not mean — peak energy matters)
- `_face_in_window`: fraction of sampled frames in window that have real face detection (not fallback 0.5,0.5)
- `_scene_coherence`: `1 / (1 + internal_cuts)` — penalizes windows spanning many scene cuts
- `_snap_to_scene`: moves window start to nearest scene boundary within `snap_tolerance` seconds
- `_fallback_candidates`: returns single center-window candidate when transcript is empty

## Deviations from IMPL.md

- IMPL.md's `_fallback_candidate` had `...` for the `CandidateSegment` fields — filled in with correct zero-score defaults
- Float equality check `cx == 0.5 and cy == 0.5` in `_face_in_window` replaced with epsilon comparison `abs(cx - 0.5) > 1e-6` to fix linter warning (python:S1244)
- `min_dur`, `max_dur`, `target_dur`, `snap_tolerance` are parameters (with defaults matching Settings) so `app.py` can pass settings values

---

## Gate 7 Criteria (pending integration test)

```
Returns list[CandidateSegment]              → import check passes
Falls back to center window on empty transcript → _fallback_candidates()
energy_score ∈ [0, 1]                      → bounded by EnergyPeak.rms_score
face_score ∈ [0, 1]                        → fraction of visible frames
scene_score = 1/(1+cuts)                   → always > 0
Segments respect min/max duration bounds    → enforced in _chunk_transcript and main loop
```
