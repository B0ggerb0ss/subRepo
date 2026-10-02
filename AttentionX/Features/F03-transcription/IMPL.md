# F03 — Speech Transcription — Implementation

## File Location

`services/transcribe.py`

## Dependencies

- `faster_whisper` — `WhisperModel`
- `models/schemas.py` — `TranscriptSegment`, `TranscriptionError`
- `models/settings.py` — `Settings.whisper_model_size`

## Core Function Signature

```python
def transcribe(wav_path: str, model_size: str = "base") -> list[TranscriptSegment]:
    """
    Run faster-whisper on wav_path.
    Returns ordered list of TranscriptSegment.
    Raises TranscriptionError if transcription fails or produces no output.
    """
```

## Implementation

```python
from faster_whisper import WhisperModel

def transcribe(wav_path: str, model_size: str = "base") -> list[TranscriptSegment]:
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_iter, _ = model.transcribe(wav_path, beam_size=5)
    
    results = []
    for seg in segments_iter:
        results.append(TranscriptSegment(
            start=seg.start,
            end=seg.end,
            text=seg.text.strip()
        ))
    
    if not results:
        raise TranscriptionError("no speech detected in audio")
    
    return results
```

## Settings

```python
# models/settings.py
class Settings:
    whisper_model_size: str = "base"   # "base" | "small"
    whisper_beam_size: int = 5
```

## Notes

- `compute_type="int8"` reduces memory footprint significantly on CPU.
- `device="cpu"` is explicit; do not auto-detect to avoid GPU assumption on HF Spaces.
- Model is loaded fresh per pipeline run to avoid stale state between sessions.
  (If memory becomes an issue, consider module-level singleton with a lock.)
- The `segments_iter` from faster-whisper is a generator; fully consume it before returning.
