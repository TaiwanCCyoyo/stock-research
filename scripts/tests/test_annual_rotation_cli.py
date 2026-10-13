"""The study CLI fails closed before reading any market data."""

import subprocess
import sys
from pathlib import Path


def test_missing_input_pin_does_not_fallback_or_publish(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "tasks/20261013-annual-winner-rotation/run_study.py"
    absent = tmp_path / "absent-input-pin.json"
    output = tmp_path / "result.json"
    result = subprocess.run(
        [sys.executable, str(script), "run", "--input-pin", str(absent), "--output", str(output)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode != 0
    assert "absent-input-pin.json" in result.stderr
    assert "FileNotFoundError" in result.stderr
    assert not output.exists()
    assert not absent.exists()
