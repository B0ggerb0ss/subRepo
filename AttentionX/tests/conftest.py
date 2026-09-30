from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models.schemas import CandidateSegment, EnergyPeak, FaceTrack, ScoredSegment, TranscriptSegment
from tests.support.media_factory import (
    ensure_mplconfig,
    make_scene_cut_video,
    make_testsrc_video,
    write_pattern_wav,
)

ensure_mplconfig()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("attentionx-media")


@pytest.fixture(scope="session")
def energy_wav(media_dir: Path) -> Path:
    return write_pattern_wav(media_dir / "energy.wav")


@pytest.fixture(scope="session")
def source_video(media_dir: Path) -> Path:
    return make_testsrc_video(media_dir / "source.mp4")


@pytest.fixture(scope="session")
def scene_video(media_dir: Path) -> Path:
    return make_scene_cut_video(media_dir / "scene-cut.mp4")


@pytest.fixture(scope="session")
def no_face_video(media_dir: Path) -> Path:
    return make_scene_cut_video(
        media_dir / "no-face.mp4",
        duration=4.0,
        cut_at=2.0,
        colors=("black", "gray"),
    )


@pytest.fixture
def transcript_segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(0.0, 2.0, "Here is the reason this clip works."),
        TranscriptSegment(2.0, 4.5, "You need momentum to keep people watching."),
        TranscriptSegment(4.5, 7.0, "Stop scrolling and watch this example."),
        TranscriptSegment(7.0, 10.0, "Three steps make the outcome easy to follow."),
    ]


@pytest.fixture
def energy_peaks() -> list[EnergyPeak]:
    return [
        EnergyPeak(1.0, 2.0, 0.62),
        EnergyPeak(5.0, 6.0, 0.91),
    ]


@pytest.fixture
def face_track_fixture() -> FaceTrack:
    return FaceTrack(
        frame_times=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
        centers_x=[0.48, 0.49, 0.50, 0.51, 0.50, 0.49],
        centers_y=[0.44, 0.45, 0.46, 0.46, 0.45, 0.44],
        visibility_ratio=1.0,
        stability_score=0.98,
    )


@pytest.fixture
def candidate_segment(transcript_segments: list[TranscriptSegment]) -> CandidateSegment:
    return CandidateSegment(
        start=0.0,
        end=6.0,
        transcript_text=" ".join(seg.text for seg in transcript_segments[:3]),
        transcript_segs=transcript_segments[:3],
        energy_score=0.82,
        face_score=0.9,
        scene_score=1.0,
        duration=6.0,
    )


@pytest.fixture
def scored_segment(candidate_segment: CandidateSegment) -> ScoredSegment:
    return ScoredSegment(
        candidate=candidate_segment,
        final_score=0.88,
        transcript_score=0.8,
        energy_score=0.82,
        face_score=0.9,
        scene_score=1.0,
        style_score=0.0,
        score_breakdown={
            "transcript": 0.8,
            "energy": 0.82,
            "face": 0.9,
            "scene": 1.0,
            "style": 0.0,
            "final": 0.88,
        },
    )
