from __future__ import annotations

import shutil
import uuid
from pathlib import Path


def make_session_dirs(base_temp: str = "data/temp", base_output: str = "data/outputs") -> tuple[str, str]:
    """Create per-session subdirectories under base_temp and base_output.

    Returns (temp_dir, output_dir) as absolute path strings.
    Each call produces a unique session ID via uuid4.
    """
    session_id = uuid.uuid4().hex
    temp_dir   = Path(base_temp)   / session_id
    output_dir = Path(base_output) / session_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(temp_dir.resolve()), str(output_dir.resolve())


def cleanup_temp(temp_dir: str) -> None:
    """Remove the session temp directory. Ignores errors (best-effort cleanup)."""
    shutil.rmtree(temp_dir, ignore_errors=True)
