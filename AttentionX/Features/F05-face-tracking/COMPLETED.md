# F05 — Face Detection and Tracking — Completion Record

## Status: COMPLETE
## Implementation date: 2026-04-18

---

## Files Implemented

| File                   | Role                                                      |
|------------------------|-----------------------------------------------------------|
| `services/face_track.py` | `track_faces()`, `_detect_face_center()`, `_compute_stability()` |
| `models/schemas.py`    | `FaceTrack`                                               |

---

## Implementation Notes

- `model_selection=0` — short-range model, adequate for typical talking-head framing
- `cap.release()` and `detector.close()` called in `finally` block — resources always released
- No-face frames: fallback to `(0.5, 0.5)` center — `detected=False` tracked separately
- `visibility_ratio` = fraction of sampled frames with a real detection
- `stability_score` = `max(0, 1 - min(1, (var_x + var_y) * 10))` — empirical scaling

## Deviations from IMPL.md

- IMPL.md noted `cap.release()` must be in `try/finally` as a requirement. Implemented exactly that.
- `_detect_face_center` explicitly ignores `h, w = frame.shape[:2]` line from IMPL.md (it was unused).

---

## Gate 5 Criteria (pending live video test)

```
Returns FaceTrack with all required fields          → dataclass enforces structure
visibility_ratio ∈ [0, 1]                          → division guarded by total > 0
stability_score ∈ [0, 1]                           → clamped by max/min
cap and detector always released                    → try/finally block
Fallback (0.5, 0.5) on frames with no detection    → _detect_face_center returns False branch
```
