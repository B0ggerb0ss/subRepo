# F04 — Audio Energy Analysis — Implementation

## File Location

`services/audio_features.py`

## Dependencies

- `librosa` — `load`, `feature.rms`, `frames_to_time`
- `numpy`
- `models/schemas.py` — `EnergyPeak`, `RMSCurve`, `AudioAnalysisError`
- `models/settings.py` — `Settings.rms_peak_percentile`

## Core Function Signature

```python
def analyze_audio_energy(
    wav_path: str,
    percentile: int = 75
) -> tuple[list[EnergyPeak], RMSCurve]:
```

## Implementation Outline

```python
import librosa
import numpy as np

def analyze_audio_energy(wav_path, percentile=75):
    y, sr = librosa.load(wav_path, sr=22050, mono=True)
    
    rms = librosa.feature.rms(y=y, hop_length=512)[0]          # shape: (n_frames,)
    times = librosa.frames_to_time(
        np.arange(len(rms)), sr=sr, hop_length=512
    )
    
    norm_rms = rms / rms.max() if rms.max() > 0 else rms       # normalize to [0,1]
    threshold = np.percentile(norm_rms, percentile)
    
    above = norm_rms > threshold
    peaks = _merge_contiguous_windows(times, norm_rms, above, merge_gap=0.5)
    
    curve = RMSCurve(times=times.tolist(), values=norm_rms.tolist())
    return peaks, curve


def _merge_contiguous_windows(times, rms, mask, merge_gap):
    # Group contiguous True regions into (start, end, mean_score) tuples
    # Merge adjacent groups separated by < merge_gap seconds
    ...
```

## Peak Merging Logic

1. Find contiguous runs of `True` in `mask`.
2. For each run: `start = times[run_start]`, `end = times[run_end]`, `score = mean(rms[run])`.
3. Merge two runs if `next.start - current.end < merge_gap`.
4. Return as `list[EnergyPeak]`.

## Settings

```python
# models/settings.py
class Settings:
    rms_peak_percentile: int = 75
    rms_merge_gap_sec:   float = 0.5
```

## Notes

- `rms.max() > 0` guard prevents division by zero on silent audio.
- `_merge_contiguous_windows` is a pure function — unit-testable independently.
- Do not import matplotlib here; plotting is for debugging only (use a separate debug script).
