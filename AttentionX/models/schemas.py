from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Pipeline exceptions — raised at stage boundaries, never swallowed
# ---------------------------------------------------------------------------

class NormalizationError(RuntimeError):
    pass

class AudioExtractionError(RuntimeError):
    pass

class TranscriptionError(RuntimeError):
    pass

class AudioAnalysisError(RuntimeError):
    pass

class SceneDetectionError(RuntimeError):
    pass

class RenderError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

@dataclass
class TranscriptSegment:
    start: float   # seconds from video start
    end:   float
    text:  str


# ---------------------------------------------------------------------------
# Audio energy
# ---------------------------------------------------------------------------

@dataclass
class EnergyPeak:
    start:     float   # seconds
    end:       float
    rms_score: float   # normalized [0, 1]

@dataclass
class RMSCurve:
    times:  list[float]   # one entry per analysis frame
    values: list[float]   # normalized RMS [0, 1]


# ---------------------------------------------------------------------------
# Face tracking
# ---------------------------------------------------------------------------

@dataclass
class FaceTrack:
    frame_times:      list[float]   # sampled frame timestamps (seconds)
    centers_x:        list[float]   # normalized [0, 1] horizontal face center
    centers_y:        list[float]   # normalized [0, 1] vertical face center
    visibility_ratio: float         # fraction of frames with a detected face
    stability_score:  float         # 1 - normalized_variance of centers [0, 1]
    # Per-sample detection mask. A detected face exactly at (0.5, 0.5) is valid,
    # so coordinates must never double as an absence sentinel.
    detected:         list[bool] = field(default_factory=list)
    detector_status:  str = "unknown"  # "available" | "missing" | "unknown"

    def detection_mask(self) -> list[bool]:
        if len(self.detected) == len(self.frame_times):
            return list(self.detected)
        # Legacy tracks without a mask: only an all-visible track is unambiguous.
        if self.visibility_ratio >= 1.0:
            return [True] * len(self.frame_times)
        return [
            abs(cx - 0.5) > 1e-6 or abs(cy - 0.5) > 1e-6
            for cx, cy in zip(self.centers_x, self.centers_y)
        ]


# ---------------------------------------------------------------------------
# Segment building
# ---------------------------------------------------------------------------

@dataclass
class CandidateSegment:
    start:           float
    end:             float
    transcript_text: str
    transcript_segs: list[TranscriptSegment]
    energy_score:    float   # [0, 1]
    face_score:      float   # [0, 1]
    scene_score:     float   # [0, 1]
    duration:        float   # end - start


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class StyleProfile:
    mean_duration:        float
    mean_face_ratio:      float
    mean_caption_density: float

@dataclass
class ScoredSegment:
    candidate:        CandidateSegment
    final_score:      float
    transcript_score: float
    energy_score:     float
    face_score:       float
    scene_score:      float
    style_score:      float
    score_breakdown:  dict = field(default_factory=dict)
