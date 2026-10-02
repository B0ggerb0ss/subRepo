from __future__ import annotations

from pathlib import Path

from utils.io_utils import cleanup_temp, make_session_dirs


def test_make_session_dirs_creates_unique_directories(tmp_path: Path) -> None:
    temp_one, output_one = make_session_dirs(
        base_temp=str(tmp_path / "temp"),
        base_output=str(tmp_path / "outputs"),
    )
    temp_two, output_two = make_session_dirs(
        base_temp=str(tmp_path / "temp"),
        base_output=str(tmp_path / "outputs"),
    )

    assert Path(temp_one).is_dir()
    assert Path(output_one).is_dir()
    assert temp_one != temp_two
    assert output_one != output_two


def test_cleanup_temp_removes_directory(tmp_path: Path) -> None:
    target = tmp_path / "session"
    target.mkdir()
    (target / "artifact.txt").write_text("temp", encoding="utf-8")

    cleanup_temp(str(target))

    assert not target.exists()
