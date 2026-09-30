from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_run_all_gates_supports_subset_execution(repo_root: Path) -> None:
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp/attentionx-mpl")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_all_gates.py",
            "--gates",
            "7",
            "8",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "GATE 7" in result.stdout
    assert "GATE 8" in result.stdout
