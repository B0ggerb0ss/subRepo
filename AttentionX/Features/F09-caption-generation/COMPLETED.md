# F09 — Caption Generation — Completion Record

## Status: COMPLETE
## Implementation date: 2026-04-18

---

## Files Implemented

| File                   | Role                                     |
|------------------------|------------------------------------------|
| `services/captions.py` | `generate_srt()`, `_fmt_time()` — full   |

---

## Implementation Notes

- Timestamps are relative to `clip_start` — required because FFmpeg trims the clip first, so absolute timestamps would be wrong
- `textwrap.wrap(text, width=42)[:2]` — enforces 42-char line limit and 2-line cap in one call
- `_fmt_time` uses integer divmod chain (not string formatting hacks) for exact SRT compliance
- Empty segments (after strip + wrap) are silently skipped — empty SRT is valid, FFmpeg renders no captions
- Counter starts at 1 and only increments on non-empty blocks — no gaps in SRT block numbering
- Returns resolved absolute path (required for FFmpeg subtitles filter)

## Deviations from IMPL.md

- IMPL.md used `chr(10).join(lines)` for Python < 3.12 compatibility. Used `"\n".join(lines)` directly (Python 3.12 is the target environment)
- SRT counter now correctly skips empty segments (IMPL.md incremented `i` for all segments)

---

## Gate 9 Criteria (pending integration test)

```
Returns str path to .srt file               → Path.write_text + str(resolve())
SRT timestamps are relative to clip start   → rel_start = seg.start - clip_start
Max 2 lines per block                       → textwrap.wrap(...)[:2]
Max 42 chars per line                       → textwrap.wrap(width=42)
Empty transcript segs → empty SRT           → for loop produces no blocks
Comma separator in ms: HH:MM:SS,mmm        → f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
```
