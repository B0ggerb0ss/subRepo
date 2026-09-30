# F12 — Reference Style Replication — Implementation

## File Location

`services/style_profile.py`

## Dependencies

- `services/face_track.py` — `track_faces`
- `utils/ffmpeg_utils.py` — `get_duration`
- `models/schemas.py` — `StyleProfile`
- `numpy`

## Core Function Signature

```python
def build_style_profile(ref_paths: list[str]) -> StyleProfile | None:
    """
    Compute style profile from reference short clips.
    Returns None if ref_paths is empty.
    """
```

## Implementation

```python
import numpy as np
from services.face_track import track_faces
from utils.ffmpeg_utils import get_duration

def build_style_profile(ref_paths: list[str]) -> StyleProfile | None:
    if not ref_paths:
        return None
    
    durations, face_ratios = [], []
    
    for path in ref_paths:
        try:
            dur = get_duration(path)
            if dur <= 0:
                continue
            ft = track_faces(path, sample_fps=1.0)   # 1 fps is enough for style
            durations.append(dur)
            face_ratios.append(ft.visibility_ratio)
        except Exception:
            continue   # skip unreadable reference clips silently
    
    if not durations:
        return None
    
    return StyleProfile(
        mean_duration=float(np.mean(durations)),
        mean_face_ratio=float(np.mean(face_ratios)),
        mean_caption_density=float(np.mean([1.0 / d for d in durations])),
    )
```

## Notes

- `try/except` per reference clip: a broken reference should not abort the pipeline.
- `sample_fps=1.0` keeps reference analysis fast; 1 sample per second is enough for style ratios.
- `get_duration()` uses `ffprobe -show_entries format=duration`.
- `mean_caption_density` is a proxy (1/duration), not actual word count.
  It captures the heuristic that shorter clips tend to have higher caption turnover.
- This module is only imported when reference clips are uploaded; it adds no overhead otherwise.
