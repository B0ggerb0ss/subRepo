"""Gate 4 — Audio analysis validation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from gate_common import check, summarize
from services.audio_features import analyze_audio_energy
from tests.support.media_factory import write_pattern_wav


def main() -> int:
    print("\n=== Gate 4 — Audio Analysis ===\n")
    with tempfile.TemporaryDirectory(prefix="attentionx_gate4_") as tmp:
        wav_path = write_pattern_wav(Path(tmp) / "energy.wav", duration=3.0)
        peaks, curve = analyze_audio_energy(str(wav_path), percentile=70, merge_gap=0.15)

    results = [
        check(
            "RMS curve has time/value data",
            lambda: len(curve.times) == len(curve.values) > 0 or (_ for _ in ()).throw(RuntimeError("empty RMS curve")),
        ),
        check(
            "at least one energy peak identified",
            lambda: len(peaks) > 0 or (_ for _ in ()).throw(RuntimeError("no peaks found")),
        ),
        check(
            "peak overlaps emphasized audio window",
            lambda: any(0.9 <= peak.start <= 1.2 for peak in peaks) or (_ for _ in ()).throw(RuntimeError("expected peak near 1s")),
        ),
    ]
    return summarize(4, results)


if __name__ == "__main__":
    sys.exit(main())
