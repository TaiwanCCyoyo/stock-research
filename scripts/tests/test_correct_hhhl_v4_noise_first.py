"""Synthetic saved-row correction checks; never inspect real research outputs."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
import zlib
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.hhhl_probability import first_per_security
from research_core.jobs import file_digest
from scripts.correct_hhhl_v4_noise_first import (
    _read_correction_bytes,
    create_correction,
    original_cells,
    read_correction,
    recompute_cells,
    write_correction_transport,
)
from scripts.publish_hhhl_v4_probability import convert_publication, main, publish, verify_publication
from scripts.tests.test_hhhl_v4_summary import _row, _summaries
from scripts.tests.test_supplement_hhhl_v4_diagnostics import _synthetic_publication


def _rewrite_packet(path: Path, changes: dict[str, bytes], *, metadata_update: dict[str, Any] | None = None) -> bytes:
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(members["manifest.json"])
    members.update(changes)
    for name, payload in changes.items():
        if name != "manifest.json":
            metadata["members"][name] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    if metadata_update:
        metadata.update(metadata_update)
    members["manifest.json"] = json.dumps(metadata).encode("utf-8")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return stream.getvalue()


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    stream = io.BytesIO()
    frame.to_parquet(stream, index=False)
    return stream.getvalue()


def fixture(tmp_path: Path) -> tuple[Path, Path, pd.DataFrame]:
    run, _, _ = _synthetic_publication(tmp_path)
    noise = pd.DataFrame([
        _row("N1", "2020-02-15", breakout_date="2020-01-01", adjusted_label=1, atlas_label=1, event_id="old"),
        _row("N1", "2020-01-10", breakout_date="2020-01-05", adjusted_label=0, atlas_label=0, event_id="new"),
        _row(
            "N2",
            "2020-01-02",
            adjusted_label=None,
            atlas_label=None,
            adjusted_reason="no_shift_candidate",
            atlas_reason="no_shift_candidate",
            event_id="unknown",
        ),
    ])
    noise.to_parquet(run / "noise.parquet", index=False)
    rows = _summaries()
    # Preserve an explicitly simulated old shifted-date selection in the packet.
    wrong = recompute_cells(first_per_security(noise), rows)
    replacements = {(row["horizon"], row["basis"]): row for row in wrong}
    rows = [replacements[(row["horizon"], row["basis"])] if row["family"] == "noise" and row["sampling"] == "first_per_security" else row for row in rows]
    (run / "summaries.json").write_text(json.dumps(rows), encoding="utf-8")
    manifest = json.loads((run / "manifest.json").read_bytes())
    manifest["code_commit"] = "70a6872037e9-synthetic-only"
    manifest["counts"]["noise"] = len(noise)
    for name in ("noise.parquet", "summaries.json"):
        path = run / name
        manifest["artifacts"][name] = {"sha256": file_digest(path), "bytes": path.stat().st_size}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    v1, v2 = tmp_path / "noise-v1", tmp_path / "noise-v2"
    publish(run, v1)
    convert_publication(v1, v2)
    return run, v2, noise


def test_portable_overlay_changes_only_four_cells_without_original_mutation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run, publication, noise = fixture(tmp_path)
    before = {path: file_digest(path) for path in [*run.iterdir(), *publication.iterdir()] if path.is_file()}
    output = tmp_path / "correction.zip"
    receipt = create_correction(run, publication, output)
    assert receipt["source_noise_rows"] == 3 and receipt["selected_rows"] == 2
    verified = verify_publication(publication)
    result = read_correction(output, verified, publication)
    assert len(result["summaries"]) == 1080
    assert sum(a != b for a, b in zip(result["summaries"], result["original_summaries"], strict=True)) == 4
    for row in original_cells(result["summaries"]):
        assert (row["hits"], row["known"], row["unknown"], row["rate"]) == (1, 1, 1, 1.0)
        assert row["unknown_reasons"] == {"no_shift_candidate": 1}
    assert original_cells(result["summaries"]) == recompute_cells(noise, verified["summaries"])
    assert all(file_digest(path) == digest for path, digest in before.items())
    # Standalone query uses publication and overlay, never the saved noise table.
    (run / "noise.parquet").unlink()
    args = ["--publication", str(publication), "--family", "noise", "--sampling", "first_per_security"]
    assert main(args) == 1
    assert not capsys.readouterr().out
    assert main([*args, "--noise-first-correction", str(output)]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 4
    assert main(["--publication", str(publication), "--family", "E-clean"]) == 0


def test_correction_normalizes_deflate_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, publication, _ = fixture(tmp_path)
    output = tmp_path / "bad-deflate.zip"
    create_correction(run, publication, output)
    verified = verify_publication(publication)

    def broken_read(*_args: Any, **_kwargs: Any) -> bytes:
        raise zlib.error("synthetic invalid distance")

    monkeypatch.setattr(zipfile.ZipExtFile, "read", broken_read)
    with pytest.raises(ValueError, match="cannot read correction ZIP member") as failure:
        read_correction(output, verified, publication)
    assert isinstance(failure.value.__cause__, zlib.error)


@pytest.mark.parametrize("bad", ["cells", "source", "duplicate", "counts"])
def test_tampered_correction_is_rejected(tmp_path: Path, bad: str) -> None:
    run, publication, _ = fixture(tmp_path)
    output = tmp_path / "correction.zip"
    create_correction(run, publication, output)
    with zipfile.ZipFile(output) as archive:
        values = {name: archive.read(name) for name in archive.namelist()}
    if bad == "cells":
        values["cells.json"] = b"[]"
    elif bad == "source":
        metadata: dict[str, Any] = json.loads(values["manifest.json"])
        metadata["source_noise_rows"] += 1
        values["manifest.json"] = json.dumps(metadata).encode()
    elif bad == "counts":
        cells = json.loads(values["cells.json"])
        cells[0]["nonhits"] += 1
        values["cells.json"] = json.dumps(cells).encode()
        metadata = json.loads(values["manifest.json"])
        metadata["members"]["cells.json"] = {
            "bytes": len(values["cells.json"]),
            "sha256": hashlib.sha256(values["cells.json"]).hexdigest(),
        }
        values["manifest.json"] = json.dumps(metadata).encode()
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(corrupt, "w") as archive:
        for name, data in values.items():
            archive.writestr(name, data)
        if bad == "duplicate":
            archive.writestr("cells.json", values["cells.json"])
    with pytest.raises(ValueError):
        read_correction(corrupt, verify_publication(publication), publication)


@pytest.mark.parametrize("field", ["wait-p10", "wait-p90", "path", "reason"])
def test_hash_consistent_but_wrong_statistics_are_recomputed_and_rejected(tmp_path: Path, field: str) -> None:
    run, publication, _ = fixture(tmp_path)
    output = tmp_path / "correction.zip"
    create_correction(run, publication, output)
    with zipfile.ZipFile(output) as archive:
        cells = json.loads(archive.read("cells.json"))
    if field == "wait-p10":
        cells[0]["hit_wait_p10"] = {"value": 999.0, "known": 1, "unknown": 0}
    elif field == "wait-p90":
        cells[0]["hit_wait_p90"] = 999
    elif field == "path":
        cells[0]["nonhit_min_return_p10"]["value"] = 999.0
    else:
        cells[0]["unknown_reasons"] = {"invented_reason": 1}
    corrupt = tmp_path / f"wrong-{field}.zip"
    corrupt.write_bytes(_rewrite_packet(output, {"cells.json": json.dumps(cells).encode("utf-8")}))

    with pytest.raises(ValueError, match="do not match recomputation"):
        read_correction(corrupt, verify_publication(publication), publication)


def test_wrong_selected_id_digest_is_rejected(tmp_path: Path) -> None:
    run, publication, _ = fixture(tmp_path)
    output = tmp_path / "correction.zip"
    create_correction(run, publication, output)
    corrupt = tmp_path / "wrong-id-digest.zip"
    corrupt.write_bytes(_rewrite_packet(output, {}, metadata_update={"selected_event_ids_sha256": "0" * 64}))

    with pytest.raises(ValueError, match="selected event ID digest mismatch"):
        read_correction(corrupt, verify_publication(publication), publication)


@pytest.mark.parametrize("change", ["duplicate", "wrong-earliest", "selected-index"])
def test_selection_index_and_selected_rows_are_verified(tmp_path: Path, change: str) -> None:
    run, publication, _ = fixture(tmp_path)
    output = tmp_path / "correction.zip"
    create_correction(run, publication, output)
    with zipfile.ZipFile(output) as archive:
        index = pd.read_parquet(io.BytesIO(archive.read("selection-index.parquet")))
        selected = pd.read_parquet(io.BytesIO(archive.read("selected-noise.parquet")))
    metadata_update: dict[str, Any] = {}
    changes: dict[str, bytes] = {}
    if change == "duplicate":
        index.loc[1, "event_id"] = index.loc[0, "event_id"]
        changes["selection-index.parquet"] = _parquet_bytes(index)
    elif change == "wrong-earliest":
        index.loc[index["event_id"].eq("new"), "breakout_date"] = "2019-12-31"
        changes["selection-index.parquet"] = _parquet_bytes(index)
        ids = ["new", "unknown"]
        id_bytes = (json.dumps(ids, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        metadata_update["selected_event_ids_sha256"] = hashlib.sha256(id_bytes).hexdigest()
    else:
        selected.loc[selected["event_id"].eq("old"), "breakout_date"] = "2099-01-01"
        changes["selected-noise.parquet"] = _parquet_bytes(selected)
    corrupt = tmp_path / f"bad-selection-{change}.zip"
    corrupt.write_bytes(_rewrite_packet(output, changes, metadata_update=metadata_update))

    with pytest.raises(ValueError, match="duplicate event IDs|earliest eligible|source selection-index"):
        read_correction(corrupt, verify_publication(publication), publication)


@pytest.mark.parametrize("change", ["code-bytes", "code-identity", "dtype"])
def test_embedded_code_identity_and_saved_dtypes_are_checked(tmp_path: Path, change: str) -> None:
    run, publication, _ = fixture(tmp_path)
    output = tmp_path / "correction.zip"
    create_correction(run, publication, output)
    with zipfile.ZipFile(output) as archive:
        metadata = json.loads(archive.read("manifest.json"))
        code_member = "code/research_core/hhhl_probability.py"
        code_bytes = archive.read(code_member)
    changes: dict[str, bytes] = {}
    metadata_update: dict[str, Any] = {}
    if change == "code-bytes":
        changes[code_member] = code_bytes + b"\n# altered"
    elif change == "code-identity":
        identities = dict(metadata["correction_code_identity"])
        identities["research_core/hhhl_probability.py"] = "0" * 64
        metadata_update["correction_code_identity"] = identities
    else:
        dtypes = dict(metadata["noise_dtypes"])
        dtypes["base_eligible"] = "int64"
        metadata_update["noise_dtypes"] = dtypes
    corrupt = tmp_path / f"bad-{change}.zip"
    corrupt.write_bytes(_rewrite_packet(output, changes, metadata_update=metadata_update))

    with pytest.raises(ValueError, match="embedded correction code identity|dtypes"):
        read_correction(corrupt, verify_publication(publication), publication)


def test_legacy_v1_correction_is_explicitly_rejected_for_current_queries(tmp_path: Path) -> None:
    run, publication, _ = fixture(tmp_path)
    legacy = tmp_path / "legacy-v1.zip"
    with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": "hhhl-v4-noise-first-correction.v1"}))
        archive.writestr("cells.json", b"[]")

    with pytest.raises(ValueError, match="legacy v1 correction is not accepted"):
        read_correction(legacy, verify_publication(publication), publication)


def test_changed_source_and_existing_output_are_rejected(tmp_path: Path) -> None:
    run, publication, _ = fixture(tmp_path)
    output = tmp_path / "correction.zip"
    create_correction(run, publication, output)
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        create_correction(run, publication, output)
    assert output.read_bytes() == before
    (run / "noise.parquet").write_bytes(b"changed source")
    with pytest.raises(ValueError, match="hash/byte mismatch"):
        create_correction(run, publication, tmp_path / "new.zip")


def test_lossless_transport_and_missing_or_changed_part(tmp_path: Path) -> None:
    run, publication, _ = fixture(tmp_path)
    packet = tmp_path / "correction.zip"
    create_correction(run, publication, packet)
    transport = tmp_path / "transport"
    metadata = write_correction_transport(packet, transport)
    assert _read_correction_bytes(transport) == packet.read_bytes()
    assert all(part["bytes"] <= 400_000 for part in metadata["bundle_parts"])
    verified = verify_publication(publication)
    assert read_correction(transport, verified, publication)["summaries"] == read_correction(packet, verified, publication)["summaries"]
    with pytest.raises(FileExistsError):
        write_correction_transport(packet, transport)
    first = transport / metadata["bundle_parts"][0]["path"]
    first.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="byte count mismatch"):
        read_correction(transport, verified, publication)
    first.unlink()
    with pytest.raises(ValueError, match="missing or not a regular file"):
        read_correction(transport, verified, publication)


def test_multiple_transport_parts_preserve_every_byte(tmp_path: Path) -> None:
    packet = tmp_path / "byte-transport-only.bin"
    data = bytes(range(251)) * 3600
    packet.write_bytes(data)
    output = tmp_path / "parts"
    metadata = write_correction_transport(packet, output)
    assert [part["bytes"] for part in metadata["bundle_parts"]] == [400_000, 400_000, 103_600]
    assert _read_correction_bytes(output) == data
    metadata_path = output / "correction-transport.zip"
    metadata["bundle_sha256"] = "0" * 64
    from scripts.supplement_hhhl_v4_diagnostics import _zip_bytes

    metadata_path.write_bytes(_zip_bytes({"publication.json": json.dumps(metadata).encode("utf-8")}))
    with pytest.raises(ValueError, match="assembled publication bundle hash/byte mismatch"):
        _read_correction_bytes(output)
