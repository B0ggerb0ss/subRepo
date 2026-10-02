# F12 — Reference Style Replication (Optional)

## Purpose

If the user uploads past high-performing short clips as reference examples, compute a
lightweight style profile from those clips and use it to bias the scoring toward
candidates that match the creator's established pacing, face prominence, and caption density.

This is the "personal viral editor" layer — it biases selection toward the creator's
known style rather than applying purely generic scoring.

This feature is optional. Its absence does not affect any other stage.

## Inputs

| Name       | Type       | Description                                   |
|------------|------------|-----------------------------------------------|
| ref_paths  | list[str]  | Paths to uploaded reference short clip files  |

## Outputs

| Name          | Type          | Description                                   |
|---------------|---------------|-----------------------------------------------|
| style_profile | StyleProfile  | Lightweight style descriptor for scorer       |

## Data Schema

```python
@dataclass
class StyleProfile:
    mean_duration:    float    # average duration of reference clips (seconds)
    mean_face_ratio:  float    # average face visibility ratio across clips [0,1]
    mean_caption_density: float  # estimated words per second from clip duration
```

## Behavior

For each reference clip:
1. Run `ffprobe` to get duration.
2. Run face tracking (F05) at 1 fps sampling.
3. Compute `face_ratio` from `FaceTrack.visibility_ratio`.
4. Estimate caption density from clip duration (proxy: shorter clips → higher density).

Aggregate across all reference clips:
- `mean_duration = mean(durations)`
- `mean_face_ratio = mean(face_ratios)`
- `mean_caption_density = mean(1 / duration)` (words per second proxy)

## Style Score in F08

Given a `CandidateSegment c` and `StyleProfile p`:
```
duration_sim = 1 - abs(c.duration - p.mean_duration) / max(p.mean_duration, 1)
face_sim     = 1 - abs(c.face_score - p.mean_face_ratio)
style_score  = mean(duration_sim, face_sim)
```
Both `duration_sim` and `face_sim` are clamped to [0, 1].

## Constraints

- This feature is optional. If `ref_paths` is empty or None, return `None`.
- Do not run the full transcription or audio pipeline on reference clips.
- Only run a fast subset: ffprobe for duration, 1-fps face sampling.
- The style weight in F08 is 0.10 — even a rough profile improves ranking.
- Reference clips are temporary; write nothing to output_dir.
