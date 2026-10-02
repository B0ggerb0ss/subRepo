"""Gate 7 — Ranking validation."""
from __future__ import annotations

import sys

from gate_common import check, summarize
from models.schemas import EnergyPeak, FaceTrack, TranscriptSegment
from services.scorer import score_candidates
from services.segment_builder import build_candidates


def main() -> int:
    print("\n=== Gate 7 — Ranking ===\n")
    transcript = [
        TranscriptSegment(0.0, 2.0, "Here is the reason this clip works."),
        TranscriptSegment(2.0, 4.5, "You need momentum to keep people watching."),
        TranscriptSegment(4.5, 7.0, "Stop scrolling and watch this example."),
    ]
    peaks = [EnergyPeak(1.0, 2.0, 0.6), EnergyPeak(5.0, 6.0, 0.9)]
    face_track = FaceTrack(
        frame_times=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
        centers_x=[0.48, 0.49, 0.5, 0.51, 0.5, 0.49],
        centers_y=[0.45, 0.45, 0.46, 0.46, 0.45, 0.45],
        visibility_ratio=1.0,
        stability_score=0.99,
    )
    candidates = build_candidates(
        transcript=transcript,
        energy_peaks=peaks,
        face_track=face_track,
        scene_boundaries=[0.0, 6.0],
        video_duration=8.0,
        min_dur=4.0,
        max_dur=8.0,
        target_dur=6.0,
        snap_tolerance=0.5,
    )
    ranked = score_candidates(candidates, top_n=3)
    top = ranked[0]
    weighted_total = (
        top.transcript_score * 0.30
        + top.energy_score * 0.25
        + top.face_score * 0.25
        + top.scene_score * 0.10
        + top.style_score * 0.10
    )

    results = [
        check(
            "ranked list returned",
            lambda: len(ranked) > 0 or (_ for _ in ()).throw(RuntimeError("no ranked segments")),
        ),
        check(
            "per-feature scores present for each candidate",
            lambda: set(top.score_breakdown) >= {"transcript", "energy", "face", "scene", "style", "final"}
            or (_ for _ in ()).throw(RuntimeError("missing score breakdown fields")),
        ),
        check(
            "scores sum to the configured normalized value",
            lambda: abs(top.final_score - round(min(1.0, weighted_total), 4)) < 1e-6
            or (_ for _ in ()).throw(RuntimeError("weighting math mismatch")),
        ),
    ]
    return summarize(7, results)


if __name__ == "__main__":
    sys.exit(main())
