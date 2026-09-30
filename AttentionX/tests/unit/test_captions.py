from __future__ import annotations

from pathlib import Path

from models.schemas import CandidateSegment, ScoredSegment, TranscriptSegment
from services.captions import generate_srt
from tests.support.media_factory import parse_srt


def test_generate_srt_uses_relative_non_overlapping_timestamps(tmp_path: Path) -> None:
    candidate = CandidateSegment(
        start=10.0,
        end=12.5,
        transcript_text="alpha beta",
        transcript_segs=[
            TranscriptSegment(10.0, 10.8, "First line"),
            TranscriptSegment(10.7, 11.2, "Second line overlaps the first."),
        ],
        energy_score=0.0,
        face_score=0.0,
        scene_score=1.0,
        duration=2.5,
    )
    scored = ScoredSegment(candidate, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    srt_path = generate_srt(scored, 0, str(tmp_path))
    blocks = parse_srt(srt_path)

    assert len(blocks) == 2
    assert blocks[0]["start"] == 0.0
    assert blocks[0]["end"] <= blocks[1]["start"]


def test_generate_srt_wraps_lines_to_42_characters(tmp_path: Path) -> None:
    long_text = (
        "This is a deliberately long subtitle line that should be wrapped "
        "before it exceeds the gate limit."
    )
    candidate = CandidateSegment(
        start=0.0,
        end=3.0,
        transcript_text=long_text,
        transcript_segs=[TranscriptSegment(0.0, 2.5, long_text)],
        energy_score=0.0,
        face_score=0.0,
        scene_score=1.0,
        duration=3.0,
    )
    scored = ScoredSegment(candidate, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    srt_path = generate_srt(scored, 1, str(tmp_path))
    blocks = parse_srt(srt_path)

    assert len(blocks) == 1
    assert max(len(line) for line in blocks[0]["lines"]) <= 42
