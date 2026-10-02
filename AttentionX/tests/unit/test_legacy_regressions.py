"""Regression tests for defects reproduced by the 30 Sep 2026 audit
(docs/reference/implementation_pack/reproductions.json).

Each test encodes the audit's observed failure input and asserts the corrected
contract rather than the old behavior.
"""
from __future__ import annotations

from pathlib import Path

from models.schemas import CandidateSegment, FaceTrack, ScoredSegment, TranscriptSegment
from services.captions import generate_srt
from services.render import _mean_face_cx, plan_vertical_geometry
from services.scorer import _transcript_score
from services.segment_builder import _face_in_window, build_candidates
from tests.support.media_factory import parse_srt


def _track(xs: list[float], detected: list[bool]) -> FaceTrack:
    return FaceTrack(
        frame_times=[float(i) for i in range(len(xs))],
        centers_x=xs,
        centers_y=[0.5] * len(xs),
        visibility_ratio=sum(detected) / len(detected),
        stability_score=1.0,
        detected=detected,
    )


def test_face_visibility_uses_detection_mask_not_center_sentinel() -> None:
    # Audit: two real detections exactly at the frame center scored 0.0.
    track = _track([0.5, 0.5], [True, True])
    assert _face_in_window(0.0, 2.0, track) == 1.0


def test_face_visibility_counts_missing_detections_as_absent() -> None:
    track = _track([0.3, 0.5], [True, False])
    assert _face_in_window(0.0, 2.0, track) == 0.5


def test_crop_mean_includes_true_centered_faces() -> None:
    # Audit: [0.5, 0.5, 0.8] all detected averaged to 0.8 (centered faces dropped).
    track = _track([0.5, 0.5, 0.8], [True, True, True])
    assert abs(_mean_face_cx(track, 0.0, 3.0) - 0.6) < 1e-9


def test_crop_mean_ignores_undetected_frames() -> None:
    track = _track([0.5, 0.2, 0.2], [False, True, True])
    assert abs(_mean_face_cx(track, 0.0, 3.0) - 0.2) < 1e-9


def test_snapping_never_exceeds_max_duration() -> None:
    transcript = [
        TranscriptSegment(10.0, 18.0, "first part of a long thought"),
        TranscriptSegment(18.0, 30.0, "second part keeps going"),
        TranscriptSegment(30.0, 45.0, "a third window follows here"),
    ]
    candidates = build_candidates(
        transcript=transcript,
        energy_peaks=[],
        face_track=_track([0.5], [False]),
        scene_boundaries=[0.0, 9.0, 30.0],
        video_duration=45.0,
        min_dur=5.0,
        max_dur=20.0,
        target_dur=15.0,
        snap_tolerance=1.0,
    )
    assert candidates
    for c in candidates:
        assert c.end - c.start <= 20.0 + 1e-9
        assert abs(c.duration - (c.end - c.start)) < 1e-9


def test_next_window_starts_at_next_speech_not_previous_end() -> None:
    # Audit: silence 15..20 was absorbed into the second window, which started at 15.
    transcript = [
        TranscriptSegment(0.0, 15.0, "speech until fifteen"),
        TranscriptSegment(20.0, 25.0, "speech resumes at twenty"),
    ]
    candidates = build_candidates(
        transcript=transcript,
        energy_peaks=[],
        face_track=_track([0.5], [False]),
        scene_boundaries=[0.0],
        video_duration=30.0,
        min_dur=5.0,
        max_dur=20.0,
        target_dur=15.0,
        snap_tolerance=0.5,
    )
    assert [(c.start, c.end) for c in candidates] == [(0.0, 15.0), (20.0, 25.0)]


def _scored(start: float, end: float, segs: list[TranscriptSegment]) -> ScoredSegment:
    cand = CandidateSegment(
        start=start,
        end=end,
        transcript_text=" ".join(s.text for s in segs),
        transcript_segs=segs,
        energy_score=0.0,
        face_score=0.0,
        scene_score=1.0,
        duration=end - start,
    )
    return ScoredSegment(cand, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def test_captions_preserve_every_token_and_stay_inside_clip(tmp_path: Path) -> None:
    words = [f"word{i}" for i in range(40)]
    seg = TranscriptSegment(0.0, 8.0, " ".join(words))
    srt = generate_srt(_scored(0.0, 8.0, [seg]), 0, str(tmp_path))
    blocks = parse_srt(srt)
    emitted = " ".join(line for b in blocks for line in b["lines"]).split()
    assert emitted == words
    assert all(len(line) <= 42 for b in blocks for line in b["lines"])
    assert all(len(b["lines"]) <= 2 for b in blocks)
    assert all(0.0 <= b["start"] < b["end"] <= 8.0 for b in blocks)
    assert all(a["end"] <= b["start"] for a, b in zip(blocks, blocks[1:]))


def test_captions_clamp_segments_that_overrun_the_clip(tmp_path: Path) -> None:
    segs = [
        TranscriptSegment(9.0, 11.0, "starts before the clip"),
        TranscriptSegment(11.0, 14.0, "runs past the clip end"),
        TranscriptSegment(20.0, 21.0, "entirely outside"),
    ]
    blocks = parse_srt(generate_srt(_scored(10.0, 13.0, segs), 0, str(tmp_path)))
    text = " ".join(line for b in blocks for line in b["lines"])
    assert "entirely outside" not in text
    assert "starts before the clip" in text and "runs past the clip end" in text
    assert all(0.0 <= b["start"] < b["end"] <= 3.0 + 1e-3 for b in blocks)


def test_narrow_portrait_source_is_padded_not_crashed() -> None:
    # Audit: a portrait source narrower than the 404x720 9:16 crop failed with
    # "Invalid too big or non positive size for width '404' or height '720'".
    geometry = plan_vertical_geometry(360, 720, face_cx=0.5)
    assert geometry.mode == "pad"
    assert "pad=" in geometry.filter
    exact = plan_vertical_geometry(404, 720, face_cx=0.5)
    assert exact.mode == "crop" and exact.crop_x == 0
    wide = plan_vertical_geometry(1280, 720, face_cx=0.9)
    assert wide.mode == "crop"
    assert 0 <= wide.crop_x <= 1280 - wide.crop_w


def test_sentence_initial_capital_is_not_named_entity_signal() -> None:
    assert _transcript_score("this is ordinary text") == _transcript_score("This is ordinary text")
