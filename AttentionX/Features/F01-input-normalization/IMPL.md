# F01 — Input Normalization — Implementation

## File Location

`services/ingest.py`

## Dependencies

- `subprocess` (stdlib)
- `pathlib` (stdlib)
- `utils/ffmpeg_utils.py` → `run_ffmpeg()`, `probe_streams()`

## Data Schemas

```python
# models/schemas.py
class NormalizationError(RuntimeError):
    pass
```

## Core Function Signature

```python
def normalize_video(input_path: str, output_dir: str) -> str:
    """
    Transcode input_path to H.264/AAC MP4 in output_dir.
    Returns absolute path to normalized MP4.
    Raises NormalizationError on any failure.
    """
```

## Implementation Steps

1. Construct `norm_path = output_dir / "output_norm.mp4"`.
2. Build FFmpeg command list (never shell=True to avoid injection risk).
3. Call `subprocess.run(cmd, capture_output=True)`.
4. Check returncode; if non-zero raise `NormalizationError(stderr)`.
5. Call `probe_streams(norm_path)` to verify video + audio streams exist.
6. Return `str(norm_path)`.

## FFmpeg Command List (no shell=True)

```python
cmd = [
    "ffmpeg", "-i", input_path,
    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
    "-c:a", "aac", "-b:a", "128k",
    "-movflags", "+faststart",
    "-y", str(norm_path)
]
```

## ffprobe Verification

```python
def probe_streams(path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name",
        "-of", "json", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)
```

Check that returned JSON contains at least one `codec_type: "video"` and one `codec_type: "audio"`.

## Module Interface (services/ingest.py)

```python
def normalize_video(input_path: str, output_dir: str) -> str: ...
def extract_audio(norm_path: str, output_dir: str) -> str: ...  # F02
```

Both functions live in `ingest.py` since they are tightly coupled ingestion steps.

## Notes

- `shell=False` is mandatory — input paths come from user uploads and must not be shell-interpolated.
- `-preset fast` is chosen over `medium` to reduce CPU time on HF Spaces.
- `-crf 23` balances quality and file size for demo use.
