from __future__ import annotations

from models.schemas import CandidateSegment, StyleProfile
from services.scorer import score_candidates


def test_score_candidates_sorts_descending_and_keeps_breakdown(candidate_segment) -> None:
    weaker = CandidateSegment(
        start=6.0,
        end=12.0,
        transcript_text="um uh filler words only",
        transcript_segs=[],
        energy_score=0.2,
        face_score=0.2,
        scene_score=0.5,
        duration=6.0,
    )

    ranked = score_candidates([weaker, candidate_segment], top_n=2)

    assert len(ranked) == 2
    assert ranked[0].final_score >= ranked[1].final_score
    assert set(ranked[0].score_breakdown) >= {"transcript", "energy", "face", "scene", "style", "final"}


def test_score_candidates_uses_style_profile(candidate_segment) -> None:
    profile = StyleProfile(
        mean_duration=6.0,
        mean_face_ratio=0.9,
        mean_caption_density=0.4,
    )

    ranked = score_candidates([candidate_segment], style_profile=profile)

    assert ranked[0].style_score > 0.9
