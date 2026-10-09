"""Synthetic-only immutable benchmark package and CLI regression tests."""

import gzip
import hashlib
import json
import lzma
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from research_core.market_context_artifact import _identity, build_dataset, load_context_rows, read_dataset


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write(path: Path, value: Any) -> dict[str, Any]:
    raw = json.dumps(value).encode()
    if path.name.endswith(".gz"):
        raw = gzip.compress(raw, mtime=0)
    path.write_bytes(raw)
    return {"path": path.name, "sha256": sha(raw)}


def source(root: Path, *, series_changes: dict[str, Any] | None = None, calendar_changes: dict[str, Any] | None = None) -> tuple[Path, str]:
    root.mkdir()
    dates = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(45)]
    calendar = {"calendar_id": "calendar:test", "dates": dates, **(calendar_changes or {})}
    series = {
        "code": "0050",
        "security_id": "TW:0050",
        "series_id": "series:test",
        "calendar_id": "calendar:test",
        "raw": [100.0] * 45,
        "adjusted": [100.0 + i for i in range(45)],
        "numeric_flags": {},
        **(series_changes or {}),
    }
    manifest = {
        "calendar_id": "calendar:test",
        "calendar": {**write(root / "calendar.json", calendar), "count": 45},
        "series": {"0050": {**write(root / "0050.json.gz", series), "security_id": "TW:0050", "series_id": "series:test"}},
        "price_basis": {"adjustment": "synthetic adjusted close"},
    }
    path = root / "manifest.json"
    ref = write(path, manifest)
    return path, ref["sha256"]


def test_roundtrip_portable_and_cli(tmp_path: Path) -> None:
    path, digest = source(tmp_path / "source")
    output = tmp_path / "dataset"
    manifest = build_dataset(path, digest, output)
    assert lzma.decompress((output / "inputs/source-manifest.json.xz").read_bytes(), format=lzma.FORMAT_XZ) == path.read_bytes()
    assert gzip.decompress((output / "inputs/calendar.json.gz").read_bytes()) == (path.parent / "calendar.json").read_bytes()
    assert (output / "manifest.json").read_bytes().endswith(b"\n")
    assert (output / "definition.json").read_bytes().endswith(b"\n")
    assert (output / "summary.json").read_bytes().endswith(b"\n")
    summary = read_dataset(output, recompute=True)
    assert summary["calendar_slots"] == 45
    assert summary["dataset_id"] == manifest["dataset_id"]
    assert len(load_context_rows(output, layer="past_only", date="2020-01-30")) == 1
    result = subprocess.run(
        [sys.executable, "scripts/query_market_context.py", "--dataset", str(output), "--verify", "--layer", "retrospective", "--date", "2020-01-30"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["rows"][0]["layer"] == "retrospective"
    # Source package is no longer needed: all consumed data physically retained.
    path.rename(path.with_name("unavailable.json"))
    assert read_dataset(output)["verified"] is True


def test_overwrite_refused(tmp_path: Path) -> None:
    path, digest = source(tmp_path / "source")
    output = tmp_path / "dataset"
    output.mkdir()
    (output / "partial.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        build_dataset(path, digest, output)
    assert (output / "partial.txt").read_text() == "keep"


def test_builder_cli_and_historical_reader_without_active_definition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import market_context

    path, digest = source(tmp_path / "source")
    output = tmp_path / "dataset"
    result = subprocess.run(
        [sys.executable, "scripts/build_market_context.py", "--source-manifest", str(path), "--expected-source-sha256", digest, "--output", str(output)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["summary"]["calendar_slots"] == 45
    monkeypatch.setattr(market_context, "definition", lambda: {"version": "future.rules"})
    assert read_dataset(output)["verified"]
    with pytest.raises(ValueError, match="producer drift"):
        read_dataset(output, recompute=True)


@pytest.mark.parametrize(
    "relative",
    [
        "inputs/0050.json.gz",
        "inputs/calendar.json.gz",
        "definition.json",
        "past-only.json.gz",
        "retrospective.json.gz",
        "summary.json",
        "producer/market_context.py.gz",
    ],
)
def test_corruption_rejected(tmp_path: Path, relative: str) -> None:
    path, digest = source(tmp_path / "source")
    output = tmp_path / "dataset"
    build_dataset(path, digest, output)
    target = output / relative
    target.write_bytes(target.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="SHA256"):
        read_dataset(output)


@pytest.mark.parametrize(
    "changes",
    [
        {"security_id": "TW:9999"},
        {"code": "9999"},
        {"calendar_id": "wrong"},
        {"adjusted": [100.0]},
        {"numeric_flags": {"999": ["bad"]}},
        {"numeric_flags": [[], []]},
        {"numeric_flags": {"0": "bad"}},
    ],
)
def test_invalid_series_rejected(tmp_path: Path, changes: dict[str, Any]) -> None:
    path, digest = source(tmp_path / "source", series_changes=changes)
    with pytest.raises(ValueError):
        build_dataset(path, digest, tmp_path / "dataset")


@pytest.mark.parametrize("changes", [{"dates": []}, {"dates": ["2020-99-99"] * 45}, {"dates": ["2020-01-01"] * 45}, {"calendar_id": "wrong"}])
def test_invalid_calendar_rejected(tmp_path: Path, changes: dict[str, Any]) -> None:
    path, digest = source(tmp_path / "source", calendar_changes=changes)
    with pytest.raises(ValueError):
        build_dataset(path, digest, tmp_path / "dataset")


@pytest.mark.parametrize("escape", ["../0050.json.gz", "C:/outside.json.gz", "..\\0050.json.gz"])
def test_source_path_escape_rejected(tmp_path: Path, escape: str) -> None:
    path, _ = source(tmp_path / "source")
    manifest = json.loads(path.read_bytes())
    manifest["series"]["0050"]["path"] = escape
    write(path, manifest)
    with pytest.raises(ValueError):
        build_dataset(path, sha(path.read_bytes()), tmp_path / "dataset")


def test_masks_missing_nonfinite_nonpositive_and_flagged(tmp_path: Path) -> None:
    closes: list[float | None] = [100.0] * 45
    closes[5:10] = [None, float("nan"), float("inf"), 0, -1]
    path, digest = source(tmp_path / "source", series_changes={"adjusted": closes, "numeric_flags": {"10": ["bad"]}})
    output = tmp_path / "dataset"
    build_dataset(path, digest, output)
    assert read_dataset(output, recompute=True)["usable_closes"] == 39
    assert load_context_rows(output, layer="past_only", date="2020-01-25")[0]["state"] == "unknown"


def test_source_hash_missing_and_malformed_descriptors(tmp_path: Path) -> None:
    path, digest = source(tmp_path / "source")
    with pytest.raises(ValueError, match="SHA256"):
        build_dataset(path, "0" * 64, tmp_path / "dataset")
    output = tmp_path / "dataset"
    build_dataset(path, digest, output)
    manifest = json.loads((output / "manifest.json").read_bytes())
    manifest["artifacts"][0]["path"] = "../escape"
    write(output / "manifest.json", manifest)
    with pytest.raises(ValueError):
        read_dataset(output)
    with pytest.raises(FileNotFoundError):
        read_dataset(tmp_path / "missing")


@pytest.mark.parametrize(("close", "state"), [(103.0, "up"), (97.0, "down"), (102.999999, "consolidation")])
def test_reader_matches_exact_decimal_boundaries(tmp_path: Path, close: float, state: str) -> None:
    path, digest = source(tmp_path / "source", series_changes={"adjusted": [100.0] * 20 + [close] * 25})
    output = tmp_path / "dataset"
    build_dataset(path, digest, output)
    assert read_dataset(output, recompute=True)["verified"]
    assert load_context_rows(output, layer="past_only", date="2020-01-21")[0]["state"] == state


@pytest.mark.parametrize(
    ("field", "value"),
    [("event", "resumption"), ("information_cutoff", "2020-01-30"), ("window_start", "2020-01-02"), ("missing_reason", "warmup"), ("window_return", 0.5)],
)
def test_reader_rejects_rehashed_semantic_corruption(tmp_path: Path, field: str, value: Any) -> None:
    path, digest = source(tmp_path / "source")
    output = tmp_path / "dataset"
    build_dataset(path, digest, output)
    target = output / "past-only.json.gz"
    rows = json.loads(gzip.decompress(target.read_bytes()))
    rows[20][field] = value
    write(target, rows)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for ref in manifest["artifacts"]:
        if ref["path"] == "past-only.json.gz":
            ref["sha256"] = sha(target.read_bytes())
    manifest["dataset_id"] = _identity(manifest["artifacts"])
    write(manifest_path, manifest)
    with pytest.raises(ValueError):
        read_dataset(output)


def test_reader_rejects_rehashed_invalid_xz(tmp_path: Path) -> None:
    path, digest = source(tmp_path / "source")
    output = tmp_path / "dataset"
    build_dataset(path, digest, output)
    target = output / "inputs/source-manifest.json.xz"
    target.write_bytes(b"invalid xz archive")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for ref in manifest["artifacts"]:
        if ref["path"] == "inputs/source-manifest.json.xz":
            ref["sha256"] = sha(target.read_bytes())
    manifest["dataset_id"] = _identity(manifest["artifacts"])
    write(manifest_path, manifest)
    with pytest.raises(ValueError, match="malformed compressed artifact"):
        read_dataset(output)


@pytest.mark.parametrize(("retained_newline", "active_newline"), [(b"\n", b"\r\n"), (b"\r\n", b"\n")])
def test_recompute_accepts_only_checkout_newline_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retained_newline: bytes, active_newline: bytes) -> None:
    from research_core import market_context

    path, digest = source(tmp_path / "source")
    output = tmp_path / "dataset"
    build_dataset(path, digest, output)
    core_path = Path(market_context.__file__).resolve()
    canonical = core_path.read_bytes().replace(b"\r\n", b"\n")
    retained = canonical.replace(b"\n", retained_newline)
    relative = "producer/market_context.py.gz"
    (output / relative).write_bytes(gzip.compress(retained, mtime=0))
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for ref in manifest["artifacts"]:
        if ref["path"] == relative:
            ref["sha256"] = sha((output / relative).read_bytes())
    manifest["retained_byte_hashes"][relative] = sha(retained)
    manifest["dataset_id"] = _identity(manifest["artifacts"])
    write(manifest_path, manifest)
    read_bytes = Path.read_bytes
    active = canonical.replace(b"\n", active_newline)
    monkeypatch.setattr(Path, "read_bytes", lambda self: active if self.resolve() == core_path else read_bytes(self))
    assert read_dataset(output, recompute=True)["verified"]
    active += b"\n# a real source change\n"
    with pytest.raises(ValueError, match="producer drift"):
        read_dataset(output, recompute=True)
    manifest["retained_byte_hashes"][relative] = sha(canonical if retained_newline == b"\r\n" else canonical.replace(b"\n", b"\r\n"))
    write(manifest_path, manifest)
    with pytest.raises(ValueError, match="retained original byte SHA256"):
        read_dataset(output)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timing_caveat", "certified point in time"),
        ("retrospective_caveat", "valid trading feature"),
        ("events", {"reset": "never reset"}),
        ("missing_reasons", ["fill missing"]),
        ("units", "percent"),
    ],
)
def test_reader_rejects_rehashed_full_definition_drift(tmp_path: Path, field: str, value: Any) -> None:
    path, digest = source(tmp_path / "source")
    output = tmp_path / "dataset"
    build_dataset(path, digest, output)
    target = output / "definition.json"
    rules = json.loads(target.read_bytes())
    rules[field] = value
    write(target, rules)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for ref in manifest["artifacts"]:
        if ref["path"] == "definition.json":
            ref["sha256"] = sha(target.read_bytes())
    manifest["dataset_id"] = _identity(manifest["artifacts"])
    write(manifest_path, manifest)
    with pytest.raises(ValueError, match="definition content identity"):
        read_dataset(output)
