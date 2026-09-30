# F04 — Audio Energy Analysis

## Purpose

Compute a frame-level RMS energy curve from the extracted WAV and identify
high-energy windows that correspond to emotional peaks, raised voice, or
vocal emphasis. These windows become one scoring signal for the highlight ranker (F08).

## Inputs

| Name      | Type  | Description                    |
|-----------|-------|--------------------------------|
| wav_path  | str   | Path to `audio.wav` (from F02) |

## Outputs

| Name         | Type             | Description                               |
|--------------|------------------|-------------------------------------------|
| energy_peaks | list[EnergyPeak] | Time windows above energy threshold       |
| rms_curve    | RMSCurve         | Full normalized RMS array with time axis  |

## Data Schemas

```python
@dataclass
class EnergyPeak:
    start:     float   # seconds
    end:       float   # seconds
    rms_score: float   # normalized [0, 1]

@dataclass
class RMSCurve:
    times: list[float]   # time of each frame in seconds
    values: list[float]  # normalized RMS per frame [0, 1]
```

## Behavior

1. Load WAV with `librosa.load(wav_path, sr=22050, mono=True)`.
2. Compute RMS: `librosa.feature.rms(y=audio, hop_length=512)`.
3. Convert frame indices to seconds: `librosa.frames_to_time(frames, sr=22050, hop_length=512)`.
4. Normalize RMS values to [0, 1] by dividing by `max(rms)`.
5. Identify contiguous windows where normalized RMS > 75th percentile.
6. Merge adjacent windows separated by < 0.5 seconds.
7. Return `(energy_peaks, rms_curve)`.

## Threshold

Default: 75th percentile of the full RMS array.
Configurable via `Settings.rms_peak_percentile` (default: 75).

## Error Handling

- WAV load failure → raise `AudioAnalysisError`
- RMS array empty → raise `AudioAnalysisError`
- No peaks found → return empty list (not an error; scorer handles gracefully)

## Constraints

- Load entire WAV per call (not streamed).
- Use mono channel only.
- `hop_length=512` is the default; do not change unless tuning is explicitly needed.
