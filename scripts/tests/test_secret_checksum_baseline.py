"""The checksum exceptions must not hide a newly introduced suspect value."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative", "fields"),
    [
        ("tasks/20261002-sector-wave-catalog/catalog-v1/manifest.json", ("input_identities_sha256", "price")),
        ("tasks/20261009-hhhl-pattern-probability/publication-v1/manifest.json", ("bundle", "sha256")),
        ("research_web/public/data/saved-research-studio.manifest.json", None),
        ("research_web/public/data/research-presentation.v1.json", ("sourceSha256",)),
        ("docs/en/evidence-format-migration.json", ("sourceArchiveSha256",)),
    ],
)
def test_checksum_baseline_accepts_known_value_and_rejects_new_value(tmp_path: Path, relative: str, fields: tuple[str, ...] | None) -> None:
    baseline = json.loads((REPO_ROOT / ".secrets.baseline").read_text(encoding="utf-8"))
    source_key = next(key for key in baseline["results"] if key.replace("\\", "/") == relative)
    if fields is None:
        # The studio payload lives outside public now. Exercise the same real
        # hook and baseline record contract with wholly invented bytes, without
        # restoring a private package or silently skipping this regression.
        known = hashlib.sha256(b"synthetic approved studio package fixture").hexdigest()
        template = next(item for item in baseline["results"][source_key] if item["type"] == "Hex High Entropy String")
        allowed = {**template, "hashed_secret": hashlib.sha1(known.encode()).hexdigest()}
    else:
        known = json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
        for field in fields:
            known = known[field]
        allowed = next(item for item in baseline["results"][source_key] if item["hashed_secret"] == hashlib.sha1(known.encode()).hexdigest())
    baseline["results"] = {relative: [{**allowed, "filename": relative, "line_number": 1}]}
    baseline_path = tmp_path / ".secrets.baseline"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"label": "記憶體相關", "checksum": known}, ensure_ascii=False) + "\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    hook_config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hook = next(hook for repo in hook_config["repos"] for hook in repo["hooks"] if hook["id"] == "detect-secrets")
    entry = shlex.split(hook["entry"])
    command = [sys.executable, *entry[1:], "--baseline", str(baseline_path), relative]
    accepted = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert accepted.returncode == 0, accepted.stderr
    suspect = hashlib.sha256(b"synthetic unapproved checksum fixture").hexdigest()
    assert suspect != known
    target.write_text(json.dumps({"label": "記憶體相關", "checksum": known, "new_value": suspect}, ensure_ascii=False) + "\n", encoding="utf-8")
    rejected = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert rejected.returncode == 1
    assert "Potential secrets" in rejected.stdout + rejected.stderr
