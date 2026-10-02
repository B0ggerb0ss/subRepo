from __future__ import annotations

from services.segment_builder import build_candidates


def test_build_candidates_combines_signals_and_snaps_to_scene(
    transcript_segments,
    energy_peaks,
    face_track_fixture,
) -> None:
    candidates = build_candidates(
        transcript=transcript_segments,
        energy_peaks=energy_peaks,
        face_track=face_track_fixture,
        scene_boundaries=[0.0, 0.4, 6.0],
        video_duration=12.0,
        min_dur=4.0,
        max_dur=8.0,
        target_dur=6.0,
        snap_tolerance=0.5,
    )

    assert candidates
    first = candidates[0]
    assert first.start == 0.0
    assert first.energy_score > 0.0
    assert first.face_score > 0.0
    assert first.scene_score <= 1.0


def test_build_candidates_falls_back_when_transcript_is_empty(face_track_fixture) -> None:
    candidates = build_candidates(
        transcript=[],
        energy_peaks=[],
        face_track=face_track_fixture,
        scene_boundaries=[0.0],
        video_duration=20.0,
    )

    assert len(candidates) == 1
    assert candidates[0].duration == 15.0
