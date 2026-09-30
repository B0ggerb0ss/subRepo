from __future__ import annotations

import numpy as np

from services.audio_features import _merge_contiguous_windows, analyze_audio_energy


def test_analyze_audio_energy_returns_curve_and_peaks(energy_wav) -> None:
    peaks, curve = analyze_audio_energy(str(energy_wav), percentile=70, merge_gap=0.2)

    assert peaks
    assert curve.times
    assert curve.values
    assert max(curve.values) <= 1.0
    assert min(curve.values) >= 0.0


def test_merge_contiguous_windows_merges_small_gaps() -> None:
    times = np.array([0.0, 0.1, 0.2, 0.3, 0.4])
    rms = np.array([0.2, 0.8, 0.1, 0.7, 0.8])
    mask = np.array([False, True, False, True, True])

    peaks = _merge_contiguous_windows(times, rms, mask, merge_gap=0.2)

    assert len(peaks) == 1
    assert peaks[0].start == 0.1
    assert peaks[0].end == 0.4
