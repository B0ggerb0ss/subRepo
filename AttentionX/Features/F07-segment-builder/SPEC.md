# F07 — Candidate Segment Builder

## Purpose

Fuse the transcript segments (F03), energy peaks (F04), face track (F05), and scene
boundaries (F06) into a set of candidate clip windows. Each window is 5–20 seconds
and represents a coherent, potentially high-value moment in the source video.

## Inputs

| Name             | Type                    | Description                    |
|------------------|-------------------------|--------------------------------|
| transcript       | list[TranscriptSegment] | From F03                       |
| energy_peaks     | list[EnergyPeak]        | From F04                       |
| face_track       | FaceTrack               | From F05                       |
| scene_boundaries | list[float]             | From F06                       |
| video_duration   | float                   | Total duration of norm.mp4 (s) |

## Outputs

| Name        | Type                     | Description                           |
|-------------|--------------------------|---------------------------------------|
| candidates  | list[CandidateSegment]   | All viable candidate windows          |

## Data Schema

```python
@dataclass
class CandidateSegment:
    start:           float                  # seconds
    end:             float                  # seconds
    transcript_text: str                    # concatenated text in window
    transcript_segs: list[TranscriptSegment]
    energy_score:    float                  # max normalized RMS in window [0,1]
    face_score:      float                  # face visibility ratio in window [0,1]
    scene_score:     float                  # coherence score [0,1]; penalizes many cuts
    duration:        float                  # end - start
```

## Behavior

### Step 1 — Transcript chunking

Group consecutive `TranscriptSegment` objects into windows of 5–20 seconds.
- Start a new window when accumulated duration ≥ target (default: 15 seconds).
- Never split a single segment across two windows.
- Minimum window duration: 5 seconds.
- Maximum window duration: 20 seconds.

### Step 2 — Energy score per window

For each window `[start, end]`, find all `EnergyPeak` objects that overlap,
and take the max `rms_score` as `energy_score`.
If no peaks overlap → `energy_score = 0.0`.

### Step 3 — Face score per window

Compute the fraction of `FaceTrack.frame_times` that fall within `[start, end]`
where the corresponding center is not the fallback (0.5, 0.5).
This is the per-window `face_score`.

### Step 4 — Scene coherence score

Count the number of `scene_boundaries` that fall strictly inside `[start, end]`.
`scene_score = 1 / (1 + internal_cuts)` — penalizes candidates with many cuts.
A candidate with 0 internal cuts gets `scene_score = 1.0`.
A candidate with 3 internal cuts gets `scene_score = 0.25`.

### Step 5 — Boundary snapping

Snap `start` to the nearest scene boundary that is ≤ 1 second away.
Do not snap if no boundary is within 1 second (avoid large shifts).

## Constraints

- Minimum candidate duration: 5 seconds.
- Maximum candidate duration: 20 seconds.
- At least 1 candidate must be produced; if transcript is too short, use the full video.
- Windows must not overlap each other.
- Windows must not exceed `video_duration`.
