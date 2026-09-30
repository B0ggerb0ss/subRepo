from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Settings:
    # Transcription
    whisper_model_size: str = "base"   # "base" | "small" — never "large" on CPU tier
    whisper_beam_size:  int = 5

    # Audio energy
    rms_peak_percentile: int   = 75
    rms_merge_gap_sec:   float = 0.5

    # Face tracking
    face_sample_fps:  float = 2.0
    face_confidence:  float = 0.5

    # Scene detection
    scene_threshold:      float = 27.0
    scene_snap_tolerance: float = 1.0

    # Segment building
    min_clip_duration:    float = 5.0
    max_clip_duration:    float = 20.0
    target_clip_duration: float = 15.0

    # Scoring / output
    top_n_clips:    int = 3
    max_upload_mb:  int = 500

    score_weights: dict = field(default_factory=lambda: {
        "transcript": 0.30,
        "energy":     0.25,
        "face":       0.25,
        "scene":      0.10,
        "style":      0.10,
    })


# Module-level singleton — import and use directly; never instantiate per-request.
settings = Settings()
