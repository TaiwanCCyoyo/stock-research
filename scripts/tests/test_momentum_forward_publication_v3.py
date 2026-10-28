from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Any, cast

import pandas as pd
import pytest

from research_core import artifact_store as store
from research_core import momentum_forward_attempts_v2 as journal
from research_core import momentum_forward_publication_v3 as pub


def identity(**changes: str) -> pub.CandidateIdentity:
    return replace(pub.CandidateIdentity("2026-10-22", "a" * 32, "b" * 32, "fixture-g22", "2026-10-22", "c" * 40), **changes)


def proposal(day: str = "2026-10-22") -> pub.CohortProposal:
    end_stamp = pd.Timestamp(day) + pd.DateOffset(months=12) - pd.Timedelta(days=1)
    assert isinstance(end_stamp, pd.Timestamp)
    end = end_stamp.strftime("%Y-%m-%d")
    return pub.CohortProposal("first", day, end, None, None)


def frame(day: str = "2026-10-22", value: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame({"t0": [day, day], "security_id": ["TW:1101", "TW:2330"], "value": [value, 2.0], "recorded_late": [False, False]})


def candidate(**changes: str) -> pub.SerializedCandidate:
    who = identity(**changes)
    return pub.serialize_candidate(frame(who.target_day), identity=who, cohort_proposal=proposal(who.target_day))


class Clock:
    def __init__(self, wall: str = "2026-10-23 08:59:59", zone: str = "Asia/Taipei") -> None:
        self.wall = cast(pd.Timestamp, pd.Timestamp(wall, tz=zone))
        self.order = 0
        self.events: list[str] = []

    def __call__(self) -> pub.ClockSample:
        self.order += 1
        self.events.append("clock")
        return pub.ClockSample(self.wall, self.order, "explicit-fixture-wall", True, True)

    def cross(self) -> None:
        self.wall = cast(pd.Timestamp, pd.Timestamp("2026-10-23 09:00:01", tz="Asia/Taipei"))


@pytest.fixture()
def legacy(tmp_path: Path) -> dict[Path, bytes]:
    files = {
        "attempts.jsonl": b'{"outcome":"legacy"}\n',
        "attempts-v2.jsonl": b"legacy-v2-ledger\n",
        "days/2026-10-21.parquet": b"frozen-legacy-day",
        "cohort.json": b'{"confirmatory_start":"2026-10-22"}',
        "attempt-journal-v2/old/started.json": b"legacy-start",
    }
    result: dict[Path, bytes] = {}
    for name, raw in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        result[path] = raw
    return result


def assert_unaccepted(root: Path) -> None:
    namespace = root / "publication-v3"
    assert not (namespace / "receipts").exists()
    assert not (namespace / "cohort.json").exists()
    assert not (namespace / "accepted").exists()


def test_serialization_is_immutable_complete_and_does_not_mutate_source(tmp_path: Path, legacy: dict[Path, bytes]) -> None:
    source = frame()
    source["recorded_at_utc"] = "legacy-before-serialization"
    source.attrs = {"source": {"recorded_late": False}}
    original = source.copy(deep=True)
    item = pub.serialize_candidate(source, identity=identity(), cohort_proposal=proposal())
    pd.testing.assert_frame_equal(source, original)
    assert source.attrs == original.attrs
    assert all(type(raw) is bytes for raw in (item.day_bytes, item.proposal_bytes, item.manifest_bytes))
    with pytest.raises(FrozenInstanceError):
        setattr(item, "manifest_sha256", "d" * 64)
    path = pub.publish_candidate(tmp_path, item).path
    assert set(entry.name for entry in path.iterdir()) == set(pub.MEMBERS)
    content = pub.inspect_candidate(tmp_path, target_day=item.identity.target_day, bundle_id=item.identity.bundle_id)
    assert content.identity == item.identity and content.manifest_sha256 == item.manifest_sha256
    assert content.security_ids == ("TW:1101", "TW:2330") and content.row_count == 2
    stored = pd.read_parquet(path / "day.parquet")
    assert not set(pub.PROVISIONAL) & set(stored.columns) and stored.attrs == {}
    assert not hasattr(content, "state") and not hasattr(content, "accepted_cohort")
    for old_path, raw in legacy.items():
        assert old_path.read_bytes() == raw
    assert_unaccepted(tmp_path)


@pytest.mark.parametrize("offset_us,expected", [(-1, "observed_before_deadline"), (0, "observed_late"), (1, "observed_late")])
@pytest.mark.parametrize("zone", ["UTC", "Asia/Taipei"])
def test_strict_boundary_and_equivalent_timezone_instants(tmp_path: Path, offset_us: int, expected: str, zone: str) -> None:
    clock = Clock()
    clock.wall = cast(pd.Timestamp, (pd.Timestamp("2026-10-23 09:00", tz="Asia/Taipei") + pd.Timedelta(microseconds=offset_us)).tz_convert(zone))
    observed = pub.publish_and_observe(tmp_path, candidate(), clock=clock)
    assert observed.state == expected and observed.deadline_utc == pd.Timestamp("2026-10-23 01:00", tz="UTC")
    assert clock.events == ["clock", "clock"]
    assert_unaccepted(tmp_path)


def test_early_observation_does_not_change_after_deadline_or_create_acceptance(tmp_path: Path) -> None:
    item, clock = candidate(), Clock()
    observation = pub.publish_and_observe(tmp_path, item, clock=clock)
    assert observation.state == "observed_before_deadline"
    before = {path.name: path.read_bytes() for path in observation.candidate.path.iterdir()}
    clock.cross()
    inspected = pub.inspect_candidate(tmp_path, target_day=item.identity.target_day, bundle_id=item.identity.bundle_id)
    assert observation.state == "observed_before_deadline" and inspected.manifest_sha256 == item.manifest_sha256
    assert before == {path.name: path.read_bytes() for path in observation.candidate.path.iterdir()}
    assert_unaccepted(tmp_path)


STAGES = [(name, stage) for name in pub.MEMBERS for stage in ("write", "flush", "fsync", "close")] + [("directory", "publish")]


def instrument_publication(monkeypatch: pytest.MonkeyPatch, clock: Clock, selected: tuple[str, str], *, fail: bool = False) -> None:
    original_open, original_fsync, original_publish = Path.open, store.os.fsync, store.publish_noreplace
    descriptors: dict[int, str] = {}

    def checkpoint(name: str, stage: str) -> None:
        clock.events.append(f"{name}:{stage}")
        if selected == (name, stage):
            clock.cross()
            if fail:
                raise OSError(f"fixture {name}:{stage}")

    class Stream:
        def __init__(self, handle: Any, name: str) -> None:
            self.handle, self.name = handle, name

        def __enter__(self) -> Stream:
            self.handle.__enter__()
            return self

        def __exit__(self, *args: Any) -> None:
            descriptor = self.handle.fileno()
            self.handle.__exit__(*args)
            descriptors.pop(descriptor, None)
            checkpoint(self.name, "close")

        def write(self, data: bytes) -> int:
            result = self.handle.write(data)
            checkpoint(self.name, "write")
            return result

        def flush(self) -> None:
            self.handle.flush()
            checkpoint(self.name, "flush")

        def fileno(self) -> int:
            descriptor = self.handle.fileno()
            descriptors[descriptor] = self.name
            return descriptor

    def opening(path: Path, *args: Any, **kwargs: Any) -> Any:
        handle = original_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        return Stream(handle, path.name) if mode == "xb" and path.name in pub.MEMBERS and path.parent.name.startswith(".staging-") else handle

    def syncing(descriptor: int) -> None:
        original_fsync(descriptor)
        if descriptor in descriptors:
            checkpoint(descriptors[descriptor], "fsync")

    def publishing(source: Path, destination: Path) -> None:
        original_publish(source, destination)
        checkpoint("directory", "publish")

    monkeypatch.setattr(Path, "open", opening)
    monkeypatch.setattr(store.os, "fsync", syncing)
    monkeypatch.setattr(store, "publish_noreplace", publishing)


@pytest.mark.parametrize("stage", STAGES)
def test_every_member_operation_and_native_publication_crossing_is_late(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: tuple[str, str]) -> None:
    item, clock = candidate(), Clock()
    instrument_publication(monkeypatch, clock, stage)
    observed = pub.publish_and_observe(tmp_path, item, clock=clock)
    assert observed.state == "observed_late"
    assert clock.events[0] == "clock" and clock.events[-1] == "clock"
    assert clock.events[-2] == "directory:publish"
    expected = [f"{name}:{operation}" for name in pub.MEMBERS for operation in ("write", "flush", "fsync", "close")]
    assert clock.events[1:-2] == expected
    assert_unaccepted(tmp_path)


def test_serialization_crossing_cannot_produce_early_observation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    original = pd.DataFrame.to_parquet

    def slow(frame: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
        raw = original(frame, *args, **kwargs)
        clock.cross()
        return raw

    monkeypatch.setattr(pd.DataFrame, "to_parquet", slow)
    item = candidate()
    assert pub.publish_and_observe(tmp_path, item, clock=clock).state == "observed_late"
    assert_unaccepted(tmp_path)


@pytest.mark.parametrize("stage", STAGES[:-1])
def test_io_failure_retains_staging_and_legacy_bytes(
    tmp_path: Path, legacy: dict[Path, bytes], monkeypatch: pytest.MonkeyPatch, stage: tuple[str, str]
) -> None:
    item, clock = candidate(), Clock()
    instrument_publication(monkeypatch, clock, stage, fail=True)
    with pytest.raises(OSError, match="fixture"):
        pub.publish_and_observe(tmp_path, item, clock=clock)
    base = tmp_path / "publication-v3" / "bundles" / item.identity.target_day
    assert list(base.glob(".staging-*")) and not (base / item.identity.bundle_id).exists()
    assert clock.events.count("clock") == 1
    for old_path, raw in legacy.items():
        assert old_path.read_bytes() == raw
    assert_unaccepted(tmp_path)


def test_native_publication_failure_retains_complete_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = store.publish_noreplace

    def occupied(source: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "foreign").write_bytes(b"never replace")
        original(source, destination)

    monkeypatch.setattr(store, "publish_noreplace", occupied)
    with pytest.raises(FileExistsError):
        pub.publish_and_observe(tmp_path, candidate(), clock=Clock())
    base = tmp_path / "publication-v3" / "bundles" / "2026-10-22"
    staging = next(base.glob(".staging-*"))
    assert set(path.name for path in staging.iterdir()) == set(pub.MEMBERS)
    assert (base / identity().bundle_id / "foreign").read_bytes() == b"never replace"
    assert_unaccepted(tmp_path)


@pytest.mark.parametrize(
    "bad",
    [
        "naive",
        "nat",
        "missing",
        "untrusted",
        "unhealthy",
        "source",
        "source_change",
        "rollback",
        "monotonic_back",
        "monotonic_equal",
        "monotonic_invalid",
        "raises",
    ],
)
def test_invalid_untrusted_and_reordered_clocks_are_unknown(tmp_path: Path, bad: str) -> None:
    samples = [Clock()(), replace(Clock()(), monotonic_ns=2)]
    if bad == "naive":
        samples[1] = replace(samples[1], wall_time=datetime_without_zone())
    elif bad == "nat":
        samples[1] = replace(samples[1], wall_time=pd.NaT)
    elif bad == "untrusted":
        samples[1] = replace(samples[1], trusted=False)
    elif bad == "unhealthy":
        samples[1] = replace(samples[1], healthy=False)
    elif bad == "source":
        samples[1] = replace(samples[1], source="")
    elif bad == "source_change":
        samples[1] = replace(samples[1], source="different-source")
    elif bad == "rollback":
        samples[1] = replace(samples[1], wall_time=pd.Timestamp("2026-10-23 08:59:58", tz="Asia/Taipei"))
    elif bad in {"monotonic_back", "monotonic_equal", "monotonic_invalid"}:
        samples[1] = replace(samples[1], monotonic_ns={"monotonic_back": 0, "monotonic_equal": 1, "monotonic_invalid": -1}[bad])
    iterator = iter(samples)

    def clock() -> Any:
        value = next(iterator)
        if value is samples[1]:
            if bad == "missing":
                return None
            if bad == "raises":
                raise OSError("fixture clock unavailable")
        return value

    assert pub.publish_and_observe(tmp_path, candidate(), clock=clock).state == "unknown"
    assert_unaccepted(tmp_path)


def datetime_without_zone() -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp("2026-10-23 08:59:59"))


@pytest.mark.parametrize("changes", [{"generation_asof": "2026-10-21"}, {"target_day": "2026-10-21", "generation_asof": "2026-10-21"}])
def test_stale_and_pre_mission_candidates_are_ineligible(tmp_path: Path, changes: dict[str, str]) -> None:
    observed = pub.publish_and_observe(tmp_path, candidate(**changes), clock=Clock("2026-10-21 08:59:59"))
    assert observed.state == "ineligible"
    assert_unaccepted(tmp_path)


@pytest.mark.parametrize("member", pub.MEMBERS)
@pytest.mark.parametrize("damage", ["modify", "missing", "directory"])
def test_tampered_missing_or_wrong_member_type_is_rejected(tmp_path: Path, member: str, damage: str) -> None:
    item = candidate()
    path = pub.publish_candidate(tmp_path, item).path / member
    if damage == "modify":
        path.write_bytes(path.read_bytes() + b"tampered")
    else:
        path.unlink()
        if damage == "directory":
            path.mkdir()
    with pytest.raises((ValueError, OSError)):
        pub.inspect_candidate(tmp_path, target_day=item.identity.target_day, bundle_id=item.identity.bundle_id)


def test_extra_member_is_rejected(tmp_path: Path) -> None:
    item = candidate()
    path = pub.publish_candidate(tmp_path, item).path
    (path / "receipt.json").write_bytes(b"not an allowed covered member")
    with pytest.raises(ValueError, match="exactly"):
        pub.inspect_candidate(tmp_path, target_day=item.identity.target_day, bundle_id=item.identity.bundle_id)


@pytest.mark.parametrize("damage", ["digest", "length", "identity", "unknown", "duplicate", "member_list", "rows", "protocol"])
def test_manifest_contract_is_strict(tmp_path: Path, damage: str) -> None:
    item = candidate()
    path = pub.publish_candidate(tmp_path, item).path / "manifest.json"
    value = json.loads(path.read_bytes())
    if damage == "digest":
        value["payloads"]["day.parquet"]["sha256"] = "f" * 64
    elif damage == "length":
        value["payloads"]["day.parquet"]["size_bytes"] += 1
    elif damage == "identity":
        value["identity"]["attempt_id"] = "d" * 32
    elif damage == "unknown":
        value["unknown"] = True
    elif damage == "member_list":
        value["required_members"].append("extra")
    elif damage == "rows":
        value["security_ids"] = ["TW:1101"]
    elif damage == "protocol":
        value["protocol"] = "unknown"
    raw = store.canonical(value)
    if damage == "duplicate":
        raw = raw[:-1] + b',"schema":"duplicate"}'
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        pub.inspect_candidate(tmp_path, target_day=item.identity.target_day, bundle_id=item.identity.bundle_id)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("damage", ["duplicate", "unknown", "identity", "interval", "chain"])
def test_proposal_json_is_strict_even_when_manifest_digest_is_updated(tmp_path: Path, damage: str) -> None:
    item = candidate()
    path = pub.publish_candidate(tmp_path, item).path
    value = json.loads(item.proposal_bytes)
    if damage == "unknown":
        value["proposal"]["accepted"] = True
    elif damage == "identity":
        value["identity"]["code_commit"] = "f" * 40
    elif damage == "interval":
        value["proposal"]["confirmatory_end"] = "2027-10-22"
    elif damage == "chain":
        value["proposal"]["anchor_receipt_sha256"] = "e" * 64
    raw = store.canonical(value)
    if damage == "duplicate":
        raw = raw[:-1] + b',"schema":"duplicate"}'
    (path / "cohort-proposal.json").write_bytes(raw)
    manifest = json.loads(item.manifest_bytes)
    import hashlib

    manifest["payloads"]["cohort-proposal.json"] = {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (path / "manifest.json").write_bytes(store.canonical(manifest))
    with pytest.raises(ValueError):
        pub.inspect_candidate(tmp_path, target_day=item.identity.target_day, bundle_id=item.identity.bundle_id)


@pytest.mark.parametrize(
    "changes", [{"bundle_id": "../escape"}, {"attempt_id": "foreign"}, {"target_day": "2026-02-30"}, {"generation": "../g"}, {"code_commit": "unknown"}]
)
def test_invalid_identity_rejected_before_publication(changes: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        candidate(**changes)


def test_manifest_pin_and_identity_cannot_be_replaced(tmp_path: Path) -> None:
    item = candidate()
    with pytest.raises(ValueError, match="pin mismatch"):
        pub.publish_candidate(tmp_path, replace(item, manifest_sha256="d" * 64))
    with pytest.raises(ValueError):
        pub.publish_candidate(tmp_path, replace(item, identity=identity(attempt_id="e" * 32)))
    assert not (tmp_path / "publication-v3").exists()


@pytest.mark.parametrize("part", ["day", "bundle"])
def test_inspection_path_traversal_is_rejected(tmp_path: Path, part: str) -> None:
    with pytest.raises(ValueError):
        pub.inspect_candidate(tmp_path, target_day="../escape" if part == "day" else "2026-10-22", bundle_id="../escape" if part == "bundle" else "b" * 32)


def test_windows_reparse_ancestor_is_rejected_without_following_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.lstat
    # Simulate the Windows attribute on an owned fixture path; native junction case below.
    from types import SimpleNamespace

    def status(path: Path) -> Any:
        result = original(path)
        return SimpleNamespace(st_file_attributes=1024, st_mode=result.st_mode) if path == tmp_path else result

    monkeypatch.setattr(Path, "lstat", status)
    with pytest.raises(ValueError, match="reparse"):
        pub.publish_candidate(tmp_path, candidate())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native junction")
def test_real_windows_junction_is_rejected_and_target_kept(tmp_path: Path) -> None:
    target, link = tmp_path / "target", tmp_path / "junction"
    target.mkdir()
    (target / "keep").write_bytes(b"owned target")
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    try:
        with pytest.raises(ValueError, match="reparse"):
            pub.publish_candidate(link, candidate())
        with pytest.raises(ValueError, match="reparse"):
            pub.inspect_candidate(link, target_day="2026-10-22", bundle_id="b" * 32)
        assert (target / "keep").read_bytes() == b"owned target"
    finally:
        link.rmdir()  # remove only this test's junction, never its target


@pytest.mark.parametrize("occupied", ["file", "empty", "populated", "duplicate"])
def test_existing_destinations_never_change(tmp_path: Path, occupied: str) -> None:
    item = candidate()
    destination = tmp_path / "publication-v3" / "bundles" / item.identity.target_day / item.identity.bundle_id
    if occupied == "duplicate":
        pub.publish_candidate(tmp_path, item)
    else:
        destination.parent.mkdir(parents=True)
        if occupied == "file":
            destination.write_bytes(b"foreign")
        else:
            destination.mkdir()
            if occupied == "populated":
                (destination / "foreign").write_bytes(b"foreign")
    before = destination.read_bytes() if destination.is_file() else {path.name: path.read_bytes() for path in destination.iterdir()}
    with pytest.raises(FileExistsError):
        pub.publish_candidate(tmp_path, item)
    after = destination.read_bytes() if destination.is_file() else {path.name: path.read_bytes() for path in destination.iterdir()}
    assert after == before


def race_child(root: Path, label: str) -> None:
    original = store.publish_noreplace

    def barrier(source: Path, destination: Path) -> None:
        sys.stdout.write("ready\n")
        sys.stdout.flush()
        sys.stdin.readline()
        original(source, destination)

    store.publish_noreplace = barrier
    who = identity(code_commit=label * 40)
    item = pub.serialize_candidate(frame(value=1.0 if label == "a" else 3.0), identity=who, cohort_proposal=proposal())
    try:
        pub.publish_candidate(root, item)
    except FileExistsError:
        raise SystemExit(17) from None


def child_ready(child: subprocess.Popen[str]) -> str:
    stream = child.stdout
    assert stream is not None
    result: Queue[str] = Queue()

    def read() -> None:
        result.put(stream.readline())

    Thread(target=read, daemon=True).start()
    return result.get(timeout=30)


def test_two_self_created_writers_use_native_no_replace(tmp_path: Path) -> None:
    program = (
        "from pathlib import Path; import sys; "
        "from scripts.tests.test_momentum_forward_publication_v3 import race_child; "
        "race_child(Path(sys.argv[1]), sys.argv[2])"
    )
    children = [
        subprocess.Popen(
            [sys.executable, "-u", "-c", program, str(tmp_path), label], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for label in ("a", "b")
    ]
    try:
        for child in children:
            assert child_ready(child).strip() == "ready"
        for child in children:
            assert child.stdin is not None
            child.stdin.write("go\n")
            child.stdin.flush()
        for child in children:
            child.communicate(timeout=30)
        assert sorted(child.returncode for child in children) == [0, 17]
        content = pub.inspect_candidate(tmp_path, target_day="2026-10-22", bundle_id="b" * 32)
        winner = "a" if children[0].returncode == 0 else "b"
        assert content.identity.code_commit == winner * 40
        path = tmp_path / "publication-v3" / "bundles" / "2026-10-22" / ("b" * 32)
        before = {member.name: member.read_bytes() for member in path.iterdir()}
        with pytest.raises(FileExistsError):
            pub.publish_candidate(tmp_path, candidate())
        assert before == {member.name: member.read_bytes() for member in path.iterdir()}
    finally:
        for child in children:
            if child.poll() is None:
                if child.stdin is not None:
                    if not child.stdin.closed:
                        child.stdin.close()
                    child.stdin = None
                try:
                    child.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()  # only this test's own unresponsive child
                    child.communicate(timeout=10)
    assert_unaccepted(tmp_path)


def crash_child(root: Path, stage: str) -> None:
    namespace = root / "publication-v3"
    attempt = journal.Attempt(namespace, requested_day="2026-10-22", mode="manual", code_commit="c" * 40)
    who = identity(attempt_id=attempt.attempt_id)
    item = pub.serialize_candidate(frame(), identity=who, cohort_proposal=proposal())
    if stage == "published":
        pub.publish_candidate(root, item)
    else:
        assert pub.publish_and_observe(root, item, clock=Clock()).state == "observed_before_deadline"
    os._exit(73)


@pytest.mark.parametrize("stage", ["published", "observed"])
def test_child_death_never_reconstructs_observation_or_receipt(tmp_path: Path, legacy: dict[Path, bytes], stage: str) -> None:
    program = (
        "from pathlib import Path; import sys; "
        "from scripts.tests.test_momentum_forward_publication_v3 import crash_child; "
        "crash_child(Path(sys.argv[1]), sys.argv[2])"
    )
    child = subprocess.run([sys.executable, "-c", program, str(tmp_path), stage], capture_output=True, timeout=30, check=False)
    assert child.returncode == 73, child.stderr.decode(errors="replace")
    namespace = tmp_path / "publication-v3"
    path = namespace / "bundles" / "2026-10-22" / ("b" * 32)
    before = {member.name: member.read_bytes() for member in path.iterdir()}
    inspection = pub.inspect_candidate(tmp_path, target_day="2026-10-22", bundle_id="b" * 32)
    assert isinstance(inspection, pub.CandidateInspection) and not hasattr(inspection, "state")
    assert journal.recover(namespace) == []
    row = journal.read_attempts(namespace)[0]
    assert row["outcome"] == "interrupted" and row["completion"] == "unknown" and row["finished_at_utc"] is None
    ledger_before = (namespace / journal.LEDGER).read_bytes()
    assert journal.recover(namespace) == [] and (namespace / journal.LEDGER).read_bytes() == ledger_before
    assert before == {member.name: member.read_bytes() for member in path.iterdir()}
    for old_path, raw in legacy.items():
        assert old_path.read_bytes() == raw
    assert_unaccepted(tmp_path)


@pytest.mark.parametrize("bad", ["empty", "duplicate_column", "duplicate_id", "wrong_day", "accepted", "generation", "code_commit"])
def test_invalid_source_frames_are_rejected_without_mutating_them(bad: str) -> None:
    source = frame()
    if bad == "empty":
        source = source.iloc[:0]
    elif bad == "duplicate_column":
        source.columns = ["t0", "security_id", "value", "value"]
    elif bad == "duplicate_id":
        source["security_id"] = "TW:1101"
    elif bad == "wrong_day":
        source["t0"] = "2026-10-21"
    elif bad == "accepted":
        source["accepted"] = True
    else:
        source[bad] = "conflicting-identity"
    before = source.copy(deep=True)
    with pytest.raises(ValueError):
        pub.serialize_candidate(source, identity=identity(), cohort_proposal=proposal())
    pd.testing.assert_frame_equal(source, before)


def test_continuation_proposal_is_only_an_opaque_candidate(tmp_path: Path) -> None:
    who = identity(target_day="2026-10-23", generation_asof="2026-10-23")
    proposed = pub.CohortProposal("continue", "2026-10-22", "2027-10-21", "d" * 64, "e" * 64)
    item = pub.serialize_candidate(frame(who.target_day), identity=who, cohort_proposal=proposed)
    pub.publish_candidate(tmp_path, item)
    checked = pub.inspect_candidate(tmp_path, target_day=who.target_day, bundle_id=who.bundle_id)
    assert checked.proposal == proposed and not hasattr(checked, "accepted_cohort")
    assert_unaccepted(tmp_path)


@pytest.mark.parametrize("first", [None, "not-a-sample"])
def test_invalid_prepublication_clock_is_not_repaired_by_a_later_valid_sample(tmp_path: Path, first: object) -> None:
    values = iter([first, Clock()()])

    def invalid_clock() -> Any:
        return next(values)

    assert pub.publish_and_observe(tmp_path, candidate(), clock=invalid_clock).state == "unknown"
    assert_unaccepted(tmp_path)
