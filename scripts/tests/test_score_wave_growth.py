from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.score_wave_growth import evaluate


@pytest.mark.parametrize("threshold", [0, float("inf")])
def test_empty_input_still_rejects_invalid_threshold(threshold: float):
    with pytest.raises(ValueError, match="finite and positive"):
        evaluate([], threshold)


def test_cli_reads_spaced_input_path_from_spaced_working_directory(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    workdir = tmp_path / "working directory with spaces"
    workdir.mkdir()
    input_path = tmp_path / "input file with spaces.json"
    payload = {
        "rows": [
            {
                "securityId": "stock:1234",
                "waveId": "wave:a",
                "start": "2020-01-01",
                "date": "2020-01-02",
                "gain": 100,
            }
        ]
    }
    original = json.dumps(payload).encode("utf-8")
    input_path.write_bytes(original)

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "score_wave_growth.py"),
            "--input",
            str(input_path),
            "--threshold",
            "100",
        ],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=True,
    )

    output = json.loads(result.stdout)
    assert output["schema"] == "wave-growth-evaluation.v1"
    assert output["rule"] == {
        "id": "wave-growth-display.v1",
        "yearDays": 365.25,
        "thresholdPct": 100.0,
    }
    assert output["rows"][0]["input"] == payload["rows"][0]
    assert output["rows"][0]["eligibility"] == "eligible"
    assert output["rows"][0]["growth"]["basis"] == "actual"
    assert input_path.read_bytes() == original
