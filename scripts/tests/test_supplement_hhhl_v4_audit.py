"""Synthetic original-ten audit checks; no market artifacts are inspected."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import scripts.supplement_hhhl_v4_audit as supplement
from research_core.bounded_parquet import read_evidence_parquet
from research_core.hhhl_v4_landmark_view import AUDIT_LANDMARK_COLUMNS, VIEW_VERSION, attach_l20_audit
from scripts.build_hhhl_v4_probability import EVENT_COLUMNS
from scripts.publish_hhhl_v4_probability import OUTPUT_ARTIFACTS, _sha


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    events, landmarks = [], []
    for index in range(10):
        event = dict.fromkeys(EVENT_COLUMNS)
        event.update(
            event_id=f"event-{index}",
            security_id=f"S{index}",
            base_eligible=True,
            pattern=True,
            asof_date=pd.Timestamp("2020-01-01"),
            anchor_date="2020-01-01",
            breakout_date="2020-01-01",
            year=2020,
            Z2=80.0,
        )
        events.append(event)
        status = ("active", "early_hit", "early_failed", "unknown")[index % 4]
        landmark = dict.fromkeys(AUDIT_LANDMARK_COLUMNS)
        landmark.update(
            event_id=event["event_id"],
            security_id=event["security_id"],
            base_eligible=True,
            anchor_date=event["anchor_date"],
            breakout_date=event["breakout_date"],
            year=2020,
            Z2=80.0,
            landmark=20,
            status=status,
            reason="window_end" if status == "unknown" else None,
            group="cross_old_only" if status == "active" else None,
            rise_bin="b1_1p10" if status == "active" else None,
            rise_ratio=1.05 if status == "active" else None,
            cross_old=status == "active",
            cross_recent_far=False,
            landmark_date=None if status == "unknown" else "2020-01-29",
            landmark_index=20 + index,
            deadline_index=126 + index,
            target_close=200.0,
            first_cross_old_index=5 if status == "active" else None,
            first_cross_old_date="2020-01-08" if status == "active" else None,
            label_126=0 if status == "active" else None,
            complete_126=status == "active",
            unknown_reason_126="window_end" if status == "unknown" else None,
        )
        landmarks.append(landmark)
    return pd.DataFrame(events, columns=pd.Index(EVENT_COLUMNS)), pd.DataFrame(landmarks, columns=pd.Index(AUDIT_LANDMARK_COLUMNS))


@pytest.fixture
def audit_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    run, publication = tmp_path / "run", tmp_path / "publication"
    run.mkdir()
    publication.mkdir()
    audit, landmarks = _frames()
    audit.to_parquet(run / "audit-sample.parquet", index=False)
    landmarks.to_parquet(run / "landmarks.parquet", index=False)
    artifacts = {name: {"sha256": _sha(b"placeholder"), "bytes": 11} for name in OUTPUT_ARTIFACTS}
    for name in supplement.SOURCE_FILES:
        data = (run / name).read_bytes()
        artifacts[name] = {"sha256": _sha(data), "bytes": len(data)}
    manifest = {
        "schema_version": "hhhl-probability.v4",
        "complete": True,
        "code_commit": "synthetic-code",
        "identity": {"mission.md": _sha(b"synthetic")},
        "artifacts": artifacts,
    }
    manifest_bytes = supplement._json_bytes(manifest)
    (run / "manifest.json").write_bytes(manifest_bytes)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("outputs/audit-sample.parquet", (run / "audit-sample.parquet").read_bytes())
    bundle = stream.getvalue()
    (publication / "bundle.zip").write_bytes(bundle)
    metadata = {"run_manifest_sha256": _sha(manifest_bytes), "bundle_sha256": _sha(bundle)}
    # Stub only the already-verified publication boundary; exercise real audit
    # Parquet decoding, descriptor checks, source checks, join and packet reader.
    monkeypatch.setattr(supplement, "_validated_publication", lambda _root: (metadata, manifest, manifest_bytes, b"{}"))
    monkeypatch.setattr(supplement, "_assemble_transport_bundle", lambda root, _metadata: (root / "bundle.zip").read_bytes())
    return {
        "run": run,
        "publication": publication,
        "audit": audit,
        "landmarks": landmarks,
        "manifest": manifest,
        "metadata": metadata,
        "output": tmp_path / "audit.json",
    }


def test_attach_same_ten_events_preserves_sources_and_corrects_only_view_coordinates() -> None:
    audit, landmarks = _frames()
    audit_before, landmarks_before = audit.copy(deep=True), landmarks.copy(deep=True)
    joined = attach_l20_audit(audit, landmarks.iloc[::-1])
    assert joined["event_id"].tolist() == audit["event_id"].tolist()
    assert set(joined["l20_status"]) == {"active", "early_hit", "early_failed", "unknown"}
    unknown = joined["l20_status"].eq("unknown")
    assert joined.loc[unknown, "l20_landmark_index"].isna().all()
    assert landmarks.loc[landmarks["status"].eq("unknown"), "landmark_index"].notna().all()
    assert joined.attrs == {"coordinate_view_version": VIEW_VERSION, "censored_indices_nullified": 2}
    pd.testing.assert_frame_equal(joined.loc[:, EVENT_COLUMNS], audit)
    pd.testing.assert_frame_equal(audit, audit_before)
    pd.testing.assert_frame_equal(landmarks, landmarks_before)


@pytest.mark.parametrize("defect", ["duplicate-event", "duplicate-l20", "missing-l20", "other-l-only", "security", "Z2", "double-prefix"])
def test_attach_rejects_incomplete_or_mismatched_identity(defect: str) -> None:
    audit, landmarks = _frames()
    if defect == "duplicate-event":
        audit.loc[1, "event_id"] = audit.loc[0, "event_id"]
    elif defect == "duplicate-l20":
        landmarks = pd.concat([landmarks, landmarks.iloc[:1]], ignore_index=True)
    elif defect == "missing-l20":
        landmarks = landmarks.iloc[1:]
    elif defect == "other-l-only":
        landmarks.loc[0, "landmark"] = 10
    elif defect == "security":
        landmarks.loc[0, "security_id"] = "other"
    elif defect == "Z2":
        landmarks.loc[0, "Z2"] = 81
    else:
        audit = attach_l20_audit(audit, landmarks)
    with pytest.raises(ValueError):
        attach_l20_audit(audit, landmarks)


def test_create_and_portable_verify_bind_original_bundle_and_source_descriptors(audit_source: dict[str, Any]) -> None:
    source = audit_source
    before = {path: path.read_bytes() for path in [*source["run"].iterdir(), *source["publication"].iterdir()]}
    created = supplement.create_supplement(source["run"], source["publication"], source["output"])
    packet = json.loads(source["output"].read_bytes())
    assert packet["original_bundle_sha256"] == source["metadata"]["bundle_sha256"]
    assert packet["original_run_manifest_sha256"] == source["metadata"]["run_manifest_sha256"]
    assert packet["source_artifacts"] == {name: source["manifest"]["artifacts"][name] for name in supplement.SOURCE_FILES}
    assert len(packet["audit_rows"]) == len(packet["landmark_rows"]) == 10
    unknown = next(row for row in packet["landmark_rows"] if row["status"] == "unknown")
    assert unknown["landmark_index"] is not None
    assert next(row for row in packet["audit_rows"] if row["event_id"] == unknown["event_id"])["l20_landmark_index"] is None
    assert all(path.read_bytes() == data for path, data in before.items())
    # Portable verification consumes publication bytes, not the local run tables.
    source["run"].rename(source["run"].with_name("source-preserved"))
    verified = supplement.verify_supplement(source["output"], source["publication"])
    pd.testing.assert_frame_equal(created["audit"], verified["audit"])


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("name", ["audit-sample.parquet", "landmarks.parquet", "manifest.json"])
def test_create_rejects_source_identity_change_pre_and_post_read(audit_source: dict[str, Any], monkeypatch: pytest.MonkeyPatch, phase: str, name: str) -> None:
    source = audit_source
    path = source["run"] / name
    if phase == "before":
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        original_records = supplement._records
        changed = False

        def mutate_after_read(frame: pd.DataFrame) -> list[dict[str, Any]]:
            nonlocal changed
            result = original_records(frame)
            if not changed:
                path.write_bytes(path.read_bytes() + b"changed")
                changed = True
            return result

        monkeypatch.setattr(supplement, "_records", mutate_after_read)
    with pytest.raises(ValueError, match="manifest|hash/byte"):
        supplement.create_supplement(source["run"], source["publication"], source["output"])
    assert not source["output"].exists()


def test_existing_output_is_never_overwritten(audit_source: dict[str, Any]) -> None:
    source = audit_source
    source["output"].write_bytes(b"preserve existing owner bytes")
    with pytest.raises(FileExistsError):
        supplement.create_supplement(source["run"], source["publication"], source["output"])
    assert source["output"].read_bytes() == b"preserve existing owner bytes"


@pytest.mark.parametrize("defect", ["audit-row", "bundle", "manifest", "source", "view", "code", "landmark-count", "landmark-schema", "status"])
def test_portable_packet_rejects_tampered_rows_and_metadata(audit_source: dict[str, Any], defect: str) -> None:
    source = audit_source
    supplement.create_supplement(source["run"], source["publication"], source["output"])
    packet = json.loads(source["output"].read_bytes())
    if defect == "audit-row":
        packet["audit_rows"][0]["l20_status"] = "early_failed"
    elif defect in ("bundle", "manifest"):
        packet[f"original_{'bundle' if defect == 'bundle' else 'run_manifest'}_sha256"] = "0" * 64
    elif defect == "source":
        packet["source_artifacts"]["landmarks.parquet"]["sha256"] = "0" * 64
    elif defect == "view":
        packet["coordinate_view_version"] = "other-view"
    elif defect == "code":
        packet["code_sha256"]["helper"] = "invalid"
    elif defect == "landmark-count":
        packet["landmark_rows"].pop()
    elif defect == "landmark-schema":
        del packet["landmark_rows"][0]["Z2"]
    else:
        packet["landmark_rows"][0]["status"] = "invalid"
    source["output"].write_bytes(supplement._json_bytes(packet))
    with pytest.raises(ValueError):
        supplement.verify_supplement(source["output"], source["publication"])


@pytest.mark.parametrize("bad", [b"[]", b'{"duplicate":1,"duplicate":2}', b'{"value":NaN}', b"not-json"])
def test_reader_rejects_malformed_json(audit_source: dict[str, Any], bad: bytes) -> None:
    source = audit_source
    source["output"].write_bytes(bad)
    with pytest.raises(ValueError):
        supplement.verify_supplement(source["output"], source["publication"])


def test_reader_rejects_oversize_before_opening(audit_source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    source = audit_source
    source["output"].write_bytes(b" " * (supplement.MAX_BYTES + 1))

    def forbidden_open(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("oversized packet must reject before any read")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(ValueError, match="bounded regular file"):
        supplement.verify_supplement(source["output"], source["publication"])


def test_reader_remains_bounded_if_packet_grows_after_stat(audit_source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    source = audit_source
    source["output"].write_bytes(b"{}")
    original_open = Path.open
    requests: list[int] = []

    class GrowingStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size == supplement.MAX_BYTES + 1
            requests.append(size)
            return super().read(size)

    def growing_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == source["output"]:
            return GrowingStream(b" " * (supplement.MAX_BYTES + 1))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)
    with pytest.raises(ValueError, match="exceeds its byte limit"):
        supplement.verify_supplement(source["output"], source["publication"])
    assert requests == [supplement.MAX_BYTES + 1]


def test_create_rejects_oversized_packet_before_output(audit_source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    source = audit_source
    monkeypatch.setattr(supplement, "MAX_BYTES", 1)
    with pytest.raises(ValueError, match="exceeds its byte limit"):
        supplement.create_supplement(source["run"], source["publication"], source["output"])
    assert not source["output"].exists()


def test_publication_audit_rejects_wrong_original_descriptor(audit_source: dict[str, Any]) -> None:
    source = audit_source
    source["manifest"]["artifacts"]["audit-sample.parquet"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="published audit identity mismatch"):
        supplement._publication_audit(source["publication"])


def test_publication_audit_accepts_only_explicit_original_asof_timestamp(audit_source: dict[str, Any]) -> None:
    source = audit_source
    _, _, _, audit = supplement._publication_audit(source["publication"])
    pd.testing.assert_frame_equal(audit, source["audit"])
    assert str(audit["asof_date"].dtype) == "datetime64[ns]"
    records = supplement._records(audit)
    assert records[0]["asof_date"] == "2020-01-01T00:00:00"


@pytest.mark.parametrize("allowance", [(), ("breakout_date",), ("wrong-name",)])
def test_bounded_decoder_rejects_timestamp_without_exact_named_allowance(audit_source: dict[str, Any], allowance: tuple[str, ...]) -> None:
    data = (audit_source["run"] / "audit-sample.parquet").read_bytes()
    with pytest.raises(ValueError, match="primitive fields|timestamp allowances"):
        read_evidence_parquet(data, 10, EVENT_COLUMNS, timestamp_columns=allowance)


def test_publication_audit_rejects_timezone_timestamp_even_with_matching_descriptor(audit_source: dict[str, Any]) -> None:
    source = audit_source
    audit = source["audit"].copy(deep=True)
    audit["asof_date"] = audit["asof_date"].dt.tz_localize("UTC")
    parquet = io.BytesIO()
    audit.to_parquet(parquet, index=False)
    data = parquet.getvalue()
    source["manifest"]["artifacts"]["audit-sample.parquet"] = {"sha256": _sha(data), "bytes": len(data)}
    with zipfile.ZipFile(source["publication"] / "bundle.zip", "w") as archive:
        archive.writestr("outputs/audit-sample.parquet", data)
    with pytest.raises(ValueError, match="primitive fields"):
        supplement._publication_audit(source["publication"])


def test_records_preserve_nullable_scalars_and_exact_float_precision() -> None:
    value = 0.12345678901234566
    frame = pd.DataFrame({"asof_date": [pd.Timestamp("2020-01-01"), pd.NaT], "value": [value, None], "index": pd.Series([3, None], dtype="Int64")})
    records = supplement._records(frame)
    assert records == [{"asof_date": "2020-01-01T00:00:00", "value": value, "index": 3}, {"asof_date": None, "value": None, "index": None}]
    assert json.loads(supplement._json_bytes(records))[0]["value"] == value


def test_public_cli_create_verify_and_failure(audit_source: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    source = audit_source
    common = ["--publication", str(source["publication"])]
    assert supplement.main([*common, "--run", str(source["run"]), "--output", str(source["output"])]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 10
    assert supplement.main([*common, "--verify", str(source["output"])]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    source["output"].write_bytes(b"invalid")
    assert supplement.main([*common, "--verify", str(source["output"])]) == 1
    assert not capsys.readouterr().out


def test_transport_preserves_exact_original_json_and_verifies_identical_audit(audit_source: dict[str, Any]) -> None:
    source = audit_source
    original = supplement.create_supplement(source["run"], source["publication"], source["output"])
    before = source["output"].read_bytes()
    packed = source["output"].with_suffix(".zip")
    result = supplement.write_transport(source["output"], source["publication"], packed)
    with zipfile.ZipFile(packed) as archive:
        assert archive.namelist() == ["publication.json"]
        assert archive.read("publication.json") == before
    assert source["output"].read_bytes() == before
    pd.testing.assert_frame_equal(result["audit"], original["audit"])
    pd.testing.assert_frame_equal(supplement.verify_supplement(packed, source["publication"])["audit"], original["audit"])


def test_transport_never_overwrites_existing_output(audit_source: dict[str, Any]) -> None:
    source = audit_source
    supplement.create_supplement(source["run"], source["publication"], source["output"])
    packed = source["output"].with_suffix(".zip")
    packed.write_bytes(b"existing owner archive")
    with pytest.raises(FileExistsError):
        supplement.write_transport(source["output"], source["publication"], packed)
    assert packed.read_bytes() == b"existing owner archive"


def test_transport_rejects_json_above_transport_limit_with_bounded_read(audit_source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    source = audit_source
    supplement.create_supplement(source["run"], source["publication"], source["output"])
    original = source["output"].read_bytes()
    transport_limit = len(original) - 1
    monkeypatch.setattr(supplement, "MAX_TRANSPORT_METADATA_BYTES", transport_limit)
    assert len(supplement.verify_supplement(source["output"], source["publication"])["audit"]) == 10
    original_open = Path.open
    requests: list[int] = []

    class TrackingStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size is not None
            requests.append(size)
            assert size > 0
            return super().read(size)

    def tracking_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == source["output"] and args and args[0] == "rb":
            return TrackingStream(original)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    packed = source["output"].with_suffix(".zip")
    with pytest.raises(ValueError, match="single-member ZIP transport limit"):
        supplement.write_transport(source["output"], source["publication"], packed)
    assert transport_limit + 1 in requests
    assert not packed.exists()


def test_transport_rejects_source_change_after_verified_read(audit_source: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    source = audit_source
    supplement.create_supplement(source["run"], source["publication"], source["output"])
    original_verify = supplement.verify_supplement

    def changing_verify(path: Path, publication: Path) -> dict[str, Any]:
        result = original_verify(path, publication)
        if path == source["output"]:
            path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(supplement, "verify_supplement", changing_verify)
    packed = source["output"].with_suffix(".zip")
    with pytest.raises(ValueError, match="JSON changed during transport"):
        supplement.write_transport(source["output"], source["publication"], packed)
    assert not packed.exists()


def test_cli_pack_succeeds_and_zip_with_wrong_member_is_rejected(audit_source: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    source = audit_source
    supplement.create_supplement(source["run"], source["publication"], source["output"])
    packed = source["output"].with_suffix(".zip")
    args = ["--publication", str(source["publication"])]
    assert supplement.main([*args, "--pack", str(source["output"]), "--output", str(packed)]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 10
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("wrong.json", source["output"].read_bytes())
    with pytest.raises(ValueError):
        supplement.verify_supplement(packed, source["publication"])
    assert supplement.main([*args, "--verify", str(packed)]) == 1
    assert not capsys.readouterr().out
