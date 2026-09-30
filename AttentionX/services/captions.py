"""F09 — Caption Generation (SRT)

Spec reference: Features/F09-caption-generation/SPEC.md
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from models.schemas import ScoredSegment
from utils.time_utils import fmt_srt_time


def generate_srt(scored_seg: ScoredSegment, clip_index: int, output_dir: str) -> str:
    """Write an SRT caption file for the given scored segment.

    Timestamps are relative to the clip's start so they sync after FFmpeg trim.
    Returns the absolute path to the written SRT file.
    """
    clip_start = scored_seg.candidate.start
    segs = scored_seg.candidate.transcript_segs
    srt_path = Path(output_dir) / f"clip_{clip_index}.srt"

    blocks: list[str] = []
    counter = 1
    last_end = 0.0
    for seg in segs:
        rel_start = max(last_end, seg.start - clip_start, 0.0)
        rel_end = max(rel_start + 0.1, seg.end - clip_start)
        lines = textwrap.wrap(seg.text.strip(), width=42)[:2]
        if not lines:
            continue
        blocks.append(
            f"{counter}\n"
            f"{fmt_srt_time(rel_start)} --> {fmt_srt_time(rel_end)}\n"
            + "\n".join(lines)
            + "\n"
        )
        counter += 1
        last_end = rel_end

    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return str(srt_path.resolve())
