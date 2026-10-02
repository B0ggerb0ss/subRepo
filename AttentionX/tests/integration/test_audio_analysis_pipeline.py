from __future__ import annotations

from services.audio_features import analyze_audio_energy


def test_audio_analysis_detects_emphasis_windows(energy_wav) -> None:
    peaks, curve = analyze_audio_energy(str(energy_wav), percentile=70, merge_gap=0.15)

    assert len(curve.times) == len(curve.values)
    assert peaks
    assert any(0.9 <= peak.start <= 1.2 for peak in peaks)
