"""F07 — Candidate Segment Builder

Spec reference: Features/F07-segment-builder/SPEC.md
"""
from __future__ import annotations

from models.schemas import (
    CandidateSegment,
    EnergyPeak,
    FaceTrack,
    TranscriptSegment,
)


def build_candidates(
    transcript: list[TranscriptSegment],
    energy_peaks: list[EnergyPeak],
    face_track: FaceTrack,
    scene_boundaries: list[float],
    video_duration: float,
    min_dur: float = 5.0,
    max_dur: float = 20.0,
    target_dur: float = 15.0,
    snap_tolerance: float = 1.0,
) -> list[CandidateSegment]:
    """Build CandidateSegment list from pipeline signals.

    Falls back to a single center-window candidate when transcript is empty.
    """
    windows = _chunk_transcript(transcript, min_dur, max_dur, target_dur)
    candidates: list[CandidateSegment] = []

    for segs, start, end in windows:
        start = _snap_to_scene(start, scene_boundaries, snap_tolerance)
        end = min(end, video_duration)
        if end - start < min_dur:
            continue
        candidates.append(CandidateSegment(
            start=start,
            end=end,
            transcript_text=" ".join(s.text for s in segs),
            transcript_segs=segs,
            energy_score=_energy_in_window(start, end, energy_peaks),
            face_score=_face_in_window(start, end, face_track),
            scene_score=_scene_coherence(start, end, scene_boundaries),
            duration=end - start,
        ))

    return candidates if candidates else _fallback_candidates(video_duration)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _chunk_transcript(
    segs: list[TranscriptSegment],
    min_dur: float,
    max_dur: float,
    target: float,
) -> list[tuple[list[TranscriptSegment], float, float]]:
    """Greedy grouping: accumulate segments until target duration reached."""
    if not segs:
        return []

    windows: list[tuple[list[TranscriptSegment], float, float]] = []
    group: list[TranscriptSegment] = []
    group_start = segs[0].start

    for seg in segs:
        group.append(seg)
        span = seg.end - group_start
        if span >= target or (span >= min_dur and seg is segs[-1]):
            if span <= max_dur:
                windows.append((list(group), group_start, seg.end))
            else:
                windows.append((list(group), group_start, group_start + max_dur))
            group = []
            group_start = seg.end

    if group:
        span = group[-1].end - group_start
        if span >= min_dur:
            windows.append((group, group_start, group[-1].end))

    return windows


def _energy_in_window(start: float, end: float, peaks: list[EnergyPeak]) -> float:
    overlapping = [p.rms_score for p in peaks if p.start < end and p.end > start]
    return max(overlapping) if overlapping else 0.0


def _face_in_window(start: float, end: float, face_track: FaceTrack) -> float:
    in_window = [
        (cx, cy)
        for t, cx, cy in zip(
            face_track.frame_times, face_track.centers_x, face_track.centers_y
        )
        if start <= t <= end
    ]
    if not in_window:
        return 0.0
    visible = sum(1 for cx, cy in in_window if abs(cx - 0.5) > 1e-6 or abs(cy - 0.5) > 1e-6)
    return visible / len(in_window)


def _scene_coherence(start: float, end: float, boundaries: list[float]) -> float:
    internal_cuts = sum(1 for b in boundaries if start < b < end)
    return 1.0 / (1 + internal_cuts)


def _snap_to_scene(start: float, boundaries: list[float], tolerance: float) -> float:
    nearby = [b for b in boundaries if abs(b - start) <= tolerance]
    if nearby:
        return min(nearby, key=lambda b: abs(b - start))
    return start


def _fallback_candidates(video_duration: float) -> list[CandidateSegment]:
    mid = video_duration / 2
    s = max(0.0, mid - 7.5)
    e = min(video_duration, mid + 7.5)
    return [CandidateSegment(
        start=s,
        end=e,
        transcript_text="",
        transcript_segs=[],
        energy_score=0.0,
        face_score=0.0,
        scene_score=1.0,
        duration=e - s,
    )]
