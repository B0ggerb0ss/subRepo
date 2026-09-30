"""F04 — Audio Energy Analysis

Spec reference: Features/F04-audio-energy/SPEC.md
"""
from __future__ import annotations

import os
from pathlib import Path

Path("/tmp/attentionx-numba").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/attentionx-numba")

import librosa
import numpy as np

from models.schemas import AudioAnalysisError, EnergyPeak, RMSCurve


def analyze_audio_energy(
    wav_path: str,
    percentile: int = 75,
    merge_gap: float = 0.5,
) -> tuple[list[EnergyPeak], RMSCurve]:
    """Compute RMS energy curve and return high-energy peak windows.

    Returns (peaks, curve). Raises AudioAnalysisError on failure.
    """
    try:
        y, sr = librosa.load(wav_path, sr=22050, mono=True)
    except Exception as e:
        raise AudioAnalysisError(f"failed to load WAV: {e}") from e

    rms = librosa.feature.rms(y=y, hop_length=512)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

    norm_rms = rms / rms.max() if rms.max() > 0 else rms
    threshold = float(np.percentile(norm_rms, percentile))

    above = norm_rms > threshold
    peaks = _merge_contiguous_windows(times, norm_rms, above, merge_gap)

    curve = RMSCurve(times=times.tolist(), values=norm_rms.tolist())
    return peaks, curve


def _merge_contiguous_windows(
    times: np.ndarray,
    rms: np.ndarray,
    mask: np.ndarray,
    merge_gap: float,
) -> list[EnergyPeak]:
    """Group contiguous True regions into EnergyPeak objects, merging close gaps."""
    if not mask.any():
        return []

    runs: list[tuple[float, float, float]] = []  # (start, end, score)
    in_run = False
    run_start_idx = 0

    for i, val in enumerate(mask):
        if val and not in_run:
            in_run = True
            run_start_idx = i
        elif not val and in_run:
            in_run = False
            seg_times = times[run_start_idx:i]
            seg_rms = rms[run_start_idx:i]
            runs.append((float(seg_times[0]), float(seg_times[-1]), float(seg_rms.mean())))

    if in_run:
        seg_times = times[run_start_idx:]
        seg_rms = rms[run_start_idx:]
        runs.append((float(seg_times[0]), float(seg_times[-1]), float(seg_rms.mean())))

    # Merge adjacent runs separated by less than merge_gap seconds
    merged: list[tuple[float, float, float]] = []
    for start, end, score in runs:
        if merged and start - merged[-1][1] < merge_gap:
            prev_start, _, prev_score = merged[-1]
            merged[-1] = (prev_start, end, max(prev_score, score))
        else:
            merged.append((start, end, score))

    return [EnergyPeak(start=s, end=e, rms_score=round(sc, 4)) for s, e, sc in merged]
