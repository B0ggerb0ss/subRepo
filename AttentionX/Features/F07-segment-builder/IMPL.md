# F07 — Candidate Segment Builder — Implementation

## File Location

`services/segment_builder.py`

## Dependencies

- `models/schemas.py` — `CandidateSegment`, `TranscriptSegment`, `EnergyPeak`, `FaceTrack`
- `models/settings.py` — `Settings.min_clip_duration`, `Settings.max_clip_duration`, `Settings.target_clip_duration`

## Core Function Signature

```python
def build_candidates(
    transcript: list[TranscriptSegment],
    energy_peaks: list[EnergyPeak],
    face_track: FaceTrack,
    scene_boundaries: list[float],
    video_duration: float,
) -> list[CandidateSegment]:
```

## Implementation Outline

```python
def build_candidates(...) -> list[CandidateSegment]:
    windows = _chunk_transcript(transcript, min_dur=5.0, max_dur=20.0, target=15.0)
    candidates = []
    for (segs, start, end) in windows:
        start = _snap_to_scene(start, scene_boundaries, tolerance=1.0)
        end = min(end, video_duration)
        if end - start < 5.0:
            continue
        candidates.append(CandidateSegment(
            start=start,
            end=end,
            transcript_text=" ".join(s.text for s in segs),
            transcript_segs=segs,
            energy_score=_energy_in_window(start, end, energy_peaks),
            face_score=_face_in_window(start, end, face_track),
            scene_score=_scene_coherence(start, end, scene_boundaries),
            duration=end - start,
        ))
    return candidates if candidates else _fallback_candidate(video_duration)
```

## Helper Functions

```python
def _chunk_transcript(segs, min_dur, max_dur, target):
    # Greedy grouping: accumulate segments until target duration reached
    # Yield (segment_list, window_start, window_end) per group
    ...

def _energy_in_window(start, end, peaks):
    overlapping = [p.rms_score for p in peaks if p.start < end and p.end > start]
    return max(overlapping) if overlapping else 0.0

def _face_in_window(start, end, face_track):
    in_window = [
        (cx, cy) for t, cx, cy in zip(face_track.frame_times, face_track.centers_x, face_track.centers_y)
        if start <= t <= end
    ]
    if not in_window:
        return 0.0
    visible = sum(1 for cx, cy in in_window if not (cx == 0.5 and cy == 0.5))
    return visible / len(in_window)

def _scene_coherence(start, end, boundaries):
    internal_cuts = sum(1 for b in boundaries if start < b < end)
    return 1.0 / (1 + internal_cuts)

def _snap_to_scene(start, boundaries, tolerance):
    candidates = [b for b in boundaries if abs(b - start) <= tolerance]
    if candidates:
        return min(candidates, key=lambda b: abs(b - start))
    return start

def _fallback_candidate(video_duration):
    mid = video_duration / 2
    s = max(0.0, mid - 7.5)
    e = min(video_duration, mid + 7.5)
    return [CandidateSegment(start=s, end=e, ...)]
```

## Settings

```python
class Settings:
    min_clip_duration:    float = 5.0
    max_clip_duration:    float = 20.0
    target_clip_duration: float = 15.0
    scene_snap_tolerance: float = 1.0
```
