"""Sealed source identities survive real Git checkouts on Windows and Linux."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_core.artifact_store import describe_file, verify_files

ROOT = Path(__file__).resolve().parents[2]


def git(directory: Path, *arguments: str) -> None:
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *arguments], cwd=directory, capture_output=True, check=True)


@pytest.mark.parametrize("autocrlf", ["true", "false", "input"])
def test_byte_pins_survive_clean_checkout_and_detect_edits(tmp_path: Path, autocrlf: str) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    fixtures = {
        "research_core/artifact_store.py": b'"""Synthetic dependency."""\r\nvalue = 1\r\n',
        "research_core/hhhl_variants_run.py": b'"""Synthetic v1 engine."""\nvalue = 2\n',
        "tasks/20261012-hhhl-v4-variants/params/input-pins-v1.json": b'{"synthetic": true}\n',
        "tasks/20261012-hhhl-v4-variants/evidence/verify_summary.py": b'"""Synthetic auditor."""\nvalue = 3\n',
    }
    for name, data in fixtures.items():
        path = seed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    descriptors = [describe_file(seed, seed / name) for name in fixtures]
    git(seed, "init", "--quiet")
    git(seed, "-c", "core.autocrlf=false", "add", ".")
    git(seed, "commit", "--quiet", "-m", "Synthetic source identities")
    checkout = tmp_path / "checkout"
    git(tmp_path, "-c", f"core.autocrlf={autocrlf}", "clone", "--quiet", "--no-local", str(seed), str(checkout))
    verify_files(checkout, descriptors)
    for name, data in fixtures.items():
        assert (checkout / name).read_bytes() == data
    git(checkout, "diff", "--exit-code")
    altered = checkout / "research_core/hhhl_variants_run.py"
    altered.write_bytes(fixtures["research_core/hhhl_variants_run.py"] + b"value = 99\n")
    with pytest.raises(ValueError, match="mismatch"):
        verify_files(checkout, descriptors)
