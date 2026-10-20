"""Target completion, retained results and owned scratch boundaries."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_local_remaining_v5 as module
from research_core.artifact_store import read_json, write_json


def test_only_final_results_are_receipted_and_completed_phases_are_not_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    output = repo / ".tmp" / "remaining"
    original = tmp_path / "original"
    original.mkdir()
    stock = original / "stock.json"
    stock.write_text("{}", encoding="utf-8")
    calls: list[str] = []
    receipt_results: list[list[str]] = []

    class Inputs:
        def __init__(self, stock_result: Path, temporary: Path) -> None:
            self.stock_result, self.temporary, self.run = stock_result, temporary, original
            self.source_id, self.input_id, self.original_code = "original-source", "original-input", {"commit": "old"}
            self.codes, self.shared_record = ("1101",), {"generation": "held-original"}
            temporary.mkdir(parents=True, exist_ok=True)

        def cache_target(self, target: str, directory: Path) -> None:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "unhashed-intermediate").write_text("temporary", encoding="utf-8")

    def final(name: str, destination: Path) -> list[Path]:
        calls.append(name)
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / "final.parquet"
        pd.DataFrame({"count": [1]}).to_parquet(path, index=False)
        return [path]

    def conditions(inputs: Inputs, target: str, destination: Path) -> tuple[dict, dict, list[Path]]:
        return {}, {}, final("conditions", destination)

    def receipt(path: Path, **kwargs: object) -> None:
        results = kwargs["results"]
        assert isinstance(results, dict)
        receipt_results.append(list(results))
        write_json(
            path,
            {
                "code": {"commit": "new", "dirty": False},
                "results": {name: {"path": str(result), "bytes": result.stat().st_size, "sha256": "final-result-only"} for name, result in results.items()},
            },
        )

    monkeypatch.setattr(module, "LocalInputs", Inputs)
    monkeypatch.setattr(module, "code_identity", lambda root: {"commit": "new", "dirty": False})
    monkeypatch.setattr(module, "fingerprint_inputs", lambda specs: {"inputs": {}})
    monkeypatch.setattr(module, "run_conditions", conditions)
    monkeypatch.setattr(module, "run_q4", lambda inputs, target, candidates, destination: final("q4", destination))
    monkeypatch.setattr(module, "run_followup", lambda inputs, target, candidates, destination: final("followup", destination))
    monkeypatch.setattr(module, "write_run_receipt", receipt)
    monkeypatch.setattr(module, "PATTERNS", ("H1",))
    result = module.run_remaining(stock, output, repo_root=repo, targets=("H1",))
    assert result["complete"] and result["release_pending"]
    assert calls == ["conditions", "q4", "followup"]
    assert receipt_results == [["final.parquet", "top-candidates.json"], ["final.parquet"], ["final.parquet"]]
    assert not (output / "_temporary/events/H1").exists()
    assert stock.read_text(encoding="utf-8") == "{}"
    for phase in module.PHASES:
        saved = read_json(output / "H1" / phase / "run-receipt.json")
        assert all(Path(item["path"]).is_file() for item in saved["results"].values())
    module.run_remaining(stock, output, repo_root=repo, targets=("H1",))
    assert calls == ["conditions", "q4", "followup"]


def test_scratch_cleanup_refuses_original_or_result_paths(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = output / "H1/conditions"
    result.mkdir(parents=True)
    original = tmp_path / "original"
    original.mkdir()
    for path in (output, result, original):
        with pytest.raises(ValueError, match="scratch cleanup"):
            module._remove_owned_temporary(path, output)
        assert path.exists()


@pytest.mark.parametrize("finished", (False, True))
def test_launcher_releases_only_after_all_original_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finished: bool) -> None:
    import subprocess

    from research_core import pattern_scan_execution_v1, research_measurement_v1

    repo = tmp_path / "repo"
    output = repo / ".tmp" / "run"
    output.mkdir(parents=True)
    completed: dict[str, dict[str, dict[str, str]]] = {"H1": dict.fromkeys(module.PHASES if finished else ("conditions",), {})}
    # Even an accidentally true completion flag cannot release a partial run.
    write_json(output / "progress.json", {"complete": True, "release_pending": True, "completed": completed})
    calls: list[list[str]] = []

    class Job:
        def __init__(self, limit: int) -> None:
            assert limit == 8 * 1024**3

        def start(self, command: list[str], root: Path) -> SimpleNamespace:
            return SimpleNamespace(poll=lambda: 0, returncode=0, args=command)

        def memory_receipt(self) -> dict[str, int]:
            return {"peak_committed_bytes": 10}

        def close(self) -> None:
            pass

    def release(command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert command[-3:] == ["release", "--holder", "pr17-pattern-scan"]
        calls.append(command)
        return SimpleNamespace(stdout="released")

    monkeypatch.setattr(pattern_scan_execution_v1, "_MemoryBoundJob", Job)
    monkeypatch.setattr(research_measurement_v1, "host_resources", lambda: {"physical_available_bytes": 16 * 1024**3})
    monkeypatch.setattr(subprocess, "run", release)
    monkeypatch.setattr(module, "PATTERNS", ("H1",))
    module.launch_remaining([], repo, output, timeout_seconds=10)
    assert len(calls) == int(finished)
    assert read_json(output / "progress.json")["release_pending"] is (not finished)
