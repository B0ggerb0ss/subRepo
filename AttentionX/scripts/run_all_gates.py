"""Run AttentionX gates in sequence."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from gate_common import REPO_ROOT, ensure_test_video

GATE_SCRIPTS = {
    1: ["scripts/gate1_smoke.py"],
    2: ["scripts/gate2_test.py"],
    3: ["scripts/gate3_transcription.py"],
    4: ["scripts/gate4_audio_analysis.py"],
    5: ["scripts/gate5_face_tracking.py"],
    6: ["scripts/gate6_scene_detection.py"],
    7: ["scripts/gate7_ranking.py"],
    8: ["scripts/gate8_captions.py"],
    9: ["scripts/gate9_render.py"],
    10: ["scripts/gate10_ui.py"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AttentionX validation gates.")
    parser.add_argument(
        "--gates",
        nargs="+",
        type=int,
        choices=sorted(GATE_SCRIPTS),
        default=sorted(GATE_SCRIPTS),
        help="Specific gate numbers to run. Defaults to all gates.",
    )
    parser.add_argument(
        "--video",
        default=None,
        help="Optional source video for Gate 2. Defaults to data/test/test_video.mp4 or a generated fallback.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp/attentionx-mpl")
    failures: list[int] = []
    gate2_video = str(ensure_test_video(args.video))

    for gate in args.gates:
        cmd = [sys.executable, *GATE_SCRIPTS[gate]]
        if gate == 2:
            cmd.append(gate2_video)
        print(f"\n>>> Running GATE {gate}: {' '.join(cmd[1:])}")
        result = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
        if result.returncode != 0:
            failures.append(gate)

    print("\n=== Gate Summary ===")
    if not failures:
        print("ALL GATES: PASS")
        return 0
    print(f"ALL GATES: FAIL ({', '.join(str(gate) for gate in failures)})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
