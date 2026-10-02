"""Gate 8 — Caption validation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from gate_common import check, summarize
from models.schemas import CandidateSegment, ScoredSegment, TranscriptSegment
from services.captions import generate_srt
from tests.support.media_factory import parse_srt


def main() -> int:
    print("\n=== Gate 8 — Captions ===\n")
    candidate = CandidateSegment(
        start=10.0,
        end=13.0,
        transcript_text="caption gate",
        transcript_segs=[
            TranscriptSegment(10.0, 11.0, "This subtitle line should wrap cleanly for the clip."),
            TranscriptSegment(10.9, 12.4, "The second subtitle should not overlap the first."),
        ],
        energy_score=0.0,
        face_score=0.0,
        scene_score=1.0,
        duration=3.0,
    )
    scored = ScoredSegment(candidate, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    with tempfile.TemporaryDirectory(prefix="attentionx_gate8_") as tmp:
        srt_path = generate_srt(scored, 0, tmp)
        blocks = parse_srt(srt_path)
        raw_text = Path(srt_path).read_text(encoding="utf-8")

    overlaps = any(left["end"] > right["start"] for left, right in zip(blocks, blocks[1:]))
    results = [
        check(
            "valid SRT file produced",
            lambda: "-->" in raw_text and len(blocks) > 0 or (_ for _ in ()).throw(RuntimeError("invalid SRT output")),
        ),
        check(
            "no overlapping subtitle ranges",
            lambda: not overlaps or (_ for _ in ()).throw(RuntimeError("subtitle blocks overlap")),
        ),
        check(
            "line lengths stay within gate limit",
            lambda: max(len(line) for block in blocks for line in block["lines"]) <= 42
            or (_ for _ in ()).throw(RuntimeError("line length exceeds 42 characters")),
        ),
    ]
    return summarize(8, results)


if __name__ == "__main__":
    sys.exit(main())
