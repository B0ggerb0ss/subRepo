# F03 — Speech Transcription

## Purpose

Convert the extracted WAV audio into timestamped text segments. The transcript is
consumed by both the caption generator (F09) and the segment builder (F07) for
hook-quality scoring and semantic chunking.

## Inputs

| Name      | Type | Description                    |
|-----------|------|--------------------------------|
| wav_path  | str  | Path to `audio.wav` (from F02) |
| model_size| str  | "base" (default) or "small"    |

## Outputs

| Name              | Type                     | Description                        |
|-------------------|--------------------------|------------------------------------|
| segments          | list[TranscriptSegment]  | Ordered list of timed text chunks  |

## TranscriptSegment Schema

```python
@dataclass
class TranscriptSegment:
    start: float   # seconds
    end:   float   # seconds
    text:  str     # spoken text, stripped of leading/trailing whitespace
```

## Behavior

1. Load faster-whisper model (size from config, default "base").
2. Transcribe `wav_path` with `beam_size=5`.
3. Collect all segments into `list[TranscriptSegment]`.
4. Validate: non-empty, timestamps monotonically increasing, start < end per segment.
5. Return segment list.

## Model Selection

| Model  | Speed (CPU) | Accuracy | Use When                              |
|--------|-------------|----------|---------------------------------------|
| base   | Fast        | Good     | Default; HF Spaces CPU tier           |
| small  | Medium      | Better   | Optional; when accuracy matters more  |
| large  | Slow        | Best     | Never on CPU tier (memory risk)       |

## Error Handling

- Model load failure → raise `TranscriptionError`
- Empty segment list returned → raise `TranscriptionError("no speech detected")`
- Timestamp ordering violated → log warning, do not raise (whisper can have minor overlaps)

## Constraints

- Never use "large" or "large-v3" on CPU-tier.
- Word-level timestamps are optional; segment-level is the required baseline.
- Input must be the mono 22050 Hz WAV from F02.
