"""F09 — Caption Generation (SRT)

Spec reference: Features/F09-caption-generation/SPEC.md

Contract:
- Every token of every transcript segment that overlaps the clip is emitted.
- A segment longer than one cue (2 lines x 42 chars) is split into several
  consecutive cues; its time span is divided in proportion to cue characters.
- Cue times are clip-relative, non-overlapping and clamped to [0, clip_duration].
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from models.schemas import ScoredSegment
from utils.time_utils import fmt_srt_time

LINE_WIDTH = 42
LINES_PER_CUE = 2
MIN_CUE_SEC = 0.1


def _cue_texts(text: str) -> list[list[str]]:
    # break_long_words=False keeps URLs/identifiers intact; an over-long token
    # becomes its own (overlong) line rather than being silently cut.
    lines = textwrap.wrap(
        text.strip(), width=LINE_WIDTH, break_long_words=False, break_on_hyphens=False
    )
    return [lines[i:i + LINES_PER_CUE] for i in range(0, len(lines), LINES_PER_CUE)]


def generate_srt(scored_seg: ScoredSegment, clip_index: int, output_dir: str) -> str:
    """Write an SRT caption file for the given scored segment.

    Timestamps are relative to the clip's start so they sync after FFmpeg trim.
    Returns the absolute path to the written SRT file.
    """
    clip_start = scored_seg.candidate.start
    clip_dur = max(0.0, scored_seg.candidate.end - clip_start)
    srt_path = Path(output_dir) / f"clip_{clip_index}.srt"

    blocks: list[str] = []
    counter = 1
    last_end = 0.0
    for seg in scored_seg.candidate.transcript_segs:
        if seg.end <= clip_start or seg.start >= clip_start + clip_dur:
            continue
        cues = _cue_texts(seg.text)
        if not cues:
            continue
        seg_start = min(max(last_end, seg.start - clip_start, 0.0), clip_dur)
        seg_end = min(max(seg.end - clip_start, seg_start), clip_dur)
        weights = [sum(len(line) for line in cue) or 1 for cue in cues]
        total = float(sum(weights))
        cursor = seg_start
        for cue, weight in zip(cues, weights):
            cue_start = max(cursor, last_end)
            cue_end = cue_start + (seg_end - seg_start) * weight / total
            cue_end = min(max(cue_end, cue_start + MIN_CUE_SEC), clip_dur)
            if cue_end <= cue_start:
                # No room left inside the clip: append to the previous cue so
                # the tokens are still shown rather than dropped.
                if blocks:
                    blocks[-1] = blocks[-1].rstrip("\n") + "\n" + "\n".join(cue) + "\n"
                continue
            blocks.append(
                f"{counter}\n"
                f"{fmt_srt_time(cue_start)} --> {fmt_srt_time(cue_end)}\n"
                + "\n".join(cue)
                + "\n"
            )
            counter += 1
            cursor = last_end = cue_end

    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return str(srt_path.resolve())
