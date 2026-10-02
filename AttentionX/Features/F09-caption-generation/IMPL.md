# F09 — Caption Generation — Implementation

## File Location

`services/captions.py`

## Dependencies

- `textwrap` (stdlib)
- `pathlib` (stdlib)
- `models/schemas.py` — `ScoredSegment`, `TranscriptSegment`

## Core Function Signature

```python
def generate_srt(
    scored_seg: ScoredSegment,
    clip_index: int,
    output_dir: str,
) -> str:
    """
    Write SRT file for the clip window.
    Returns path to srt file.
    """
```

## Implementation

```python
import textwrap
from pathlib import Path

def generate_srt(scored_seg, clip_index, output_dir):
    clip_start = scored_seg.candidate.start
    segs = scored_seg.candidate.transcript_segs
    srt_path = Path(output_dir) / f"clip_{clip_index}.srt"
    
    blocks = []
    for i, seg in enumerate(segs, start=1):
        rel_start = max(0.0, seg.start - clip_start)
        rel_end   = max(rel_start + 0.1, seg.end - clip_start)
        lines = textwrap.wrap(seg.text.strip(), width=42)[:2]  # max 2 lines
        if not lines:
            continue
        blocks.append(
            f"{i}\n"
            f"{_fmt_time(rel_start)} --> {_fmt_time(rel_end)}\n"
            f"{chr(10).join(lines)}\n"
        )
    
    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return str(srt_path)


def _fmt_time(seconds: float) -> str:
    ms = int(seconds * 1000)
    h  = ms // 3_600_000;  ms %= 3_600_000
    m  = ms // 60_000;     ms %= 60_000
    s  = ms // 1_000;      ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
```

## Notes

- `textwrap.wrap(..., width=42)[:2]` enforces both the character limit and the 2-line cap in one call.
- `chr(10)` used instead of `\n` inside f-string for Python < 3.12 compatibility.
- Timestamps relative to `clip_start` so they work when FFmpeg trims the clip first.
- Empty `segs` list produces an empty SRT file, which FFmpeg handles gracefully (no captions rendered).
- The comma in milliseconds (`{ms:03d}` after `,`) is the SRT spec requirement — not a period.
