# F02 — Audio Extraction — Implementation

## File Location

`services/ingest.py` (alongside `normalize_video`)

## Core Function Signature

```python
def extract_audio(norm_path: str, output_dir: str) -> str:
    """
    Extract mono WAV at 22050 Hz from norm_path.
    Returns absolute path to audio.wav.
    Raises AudioExtractionError on failure.
    """
```

## Data Schemas

```python
# models/schemas.py
class AudioExtractionError(RuntimeError):
    pass
```

## FFmpeg Command List

```python
wav_path = Path(output_dir) / "audio.wav"
cmd = [
    "ffmpeg", "-i", norm_path,
    "-vn",
    "-ar", "22050",
    "-ac", "1",
    "-y", str(wav_path)
]
```

## Verification

```python
assert wav_path.exists() and wav_path.stat().st_size > 0
```

If assertion fails → raise `AudioExtractionError("WAV file missing or empty")`.

## Called By

- `services/transcribe.py` (F03) consumes `wav_path`
- `services/audio_features.py` (F04) consumes `wav_path`

Both are independent callers; `wav_path` is determined once and passed to both.
