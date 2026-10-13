"""Synthetic, offline verification of frozen annual study results."""

import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import research_core.annual_publication as annual_publication
from research_core.annual_publication import reuse_rank_rows, verified_result
from research_core.artifact_store import canonical, write_json
from research_core.research_data_builder import publish_bundle
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots


def _metadata(data_id: str, kind: str, parameters: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_id": data_id,
        "kind": kind,
        "definition_version": "annual-rotation.v1",
        "parameters": parameters,
        "inputs": inputs,
        "coverage": {
            "scope": "synthetic annual fixture",
            "raw_input_period": {"start": "2020-01-01", "end": "2021-12-31", "reason": None},
            "valid_indicator_period": {"start": None, "end": None, "reason": "not applicable"},
            "complete_label_period": {"start": None, "end": None, "reason": "synthetic fixture"},
        },
        "status": "partial",
        "limitations": ["synthetic fixture only"],
        "backup": {"status": "not_backed_up", "off_machine": False},
    }


@pytest.fixture
def published_result(tmp_path: Path) -> tuple[DataCatalog, Path, dict[str, Any]]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    catalog = DataCatalog(DataRoots.from_env({DATA_ROOT_ENV: str(primary / "research_data")}))
    parameters = {"fixture": "annual-publication.v1", "seed": 7}
    code = b"# Synthetic source only.\n"
    source = {"head": "synthetic-head", "files": {"research_core/annual_rotation.py": hashlib.sha256(code).hexdigest()}}

    input_entry = publish_bundle(
        catalog,
        _metadata("annual-rotation-inputs", "prices", parameters, {"fixture_input": "invented-v1"}),
        {"fixture-input.json": b'{"source":"synthetic"}'},
    )
    public = {
        "schema": "annual-rotation-results.v1",
        "verdict": "synthetic-verification-only",
        "input_entry": input_entry,
        "source": source,
        "arms": {"fixture": {"years": [{"year": 2021, "net_multiplier": 1.0}]}},
    }
    process_inputs = {
        "input_version": input_entry["version_id"],
        "input_manifest_sha256": input_entry["manifest"]["sha256"],
        "source": source,
    }
    process_entry = publish_bundle(
        catalog,
        _metadata("annual-rotation-process", "episodes", parameters, process_inputs),
        {"results.json": canonical(public), "study.json": canonical(parameters), "implementation/research_core/annual_rotation.py": code},
        lineage={"input_entry": input_entry},
    )
    result = {**public, "process_entry": process_entry}
    path = tmp_path / "public-result.json"
    write_json(path, result)
    return catalog, path, result


def test_verified_result_reads_and_verifies_synthetic_registered_bundles(published_result: tuple[DataCatalog, Path, dict[str, Any]]) -> None:
    catalog, path, expected = published_result

    result, process_root, manifest = verified_result(path, catalog)

    assert result == expected
    assert json.loads((process_root / "results.json").read_text(encoding="utf-8")) == {key: value for key, value in expected.items() if key != "process_entry"}
    assert manifest["lineage"]["input_entry"] == expected["input_entry"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("arms", {"fixture": {"years": [{"year": 2021, "net_multiplier": 2.0}]}}),
        ("verdict", "a different verdict"),
    ],
)
def test_verified_result_rejects_modified_public_arms_or_verdict(published_result: tuple[DataCatalog, Path, dict[str, Any]], key: str, value: Any) -> None:
    catalog, path, result = published_result
    tampered = {**result, key: value}
    path.write_bytes(canonical(tampered))

    with pytest.raises(ValueError, match="public results differ"):
        verified_result(path, catalog)


def test_verified_result_rejects_another_valid_input_entry(published_result: tuple[DataCatalog, Path, dict[str, Any]]) -> None:
    catalog, path, result = published_result
    second_input = publish_bundle(
        catalog,
        _metadata(
            "annual-rotation-inputs",
            "prices",
            {"fixture": "annual-publication.v1", "seed": 7},
            {"fixture_input": "invented-v2"},
        ),
        {"fixture-input.json": b'{"source":"another synthetic input"}'},
    )
    path.write_bytes(canonical({**result, "input_entry": second_input}))

    with pytest.raises(ValueError, match="input/process identity mismatch"):
        verified_result(path, catalog)


def test_task_verify_cli_accepts_only_the_synthetic_publication(synthetic_cli_publication: tuple[Path, Path, Path, dict[str, Any], dict[str, str]]) -> None:
    worktree, primary, path, result, environment = synthetic_cli_publication
    completed = _run_synthetic_verify(worktree, path, environment)

    assert completed.returncode == 0, completed.stderr
    assert result["process_entry"]["version_id"] in completed.stdout


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("arms", {"fixture": {"years": [{"year": 2021, "net_multiplier": 3.0}]}}),
        ("verdict", "tampered synthetic verdict"),
    ],
)
def test_task_verify_cli_rejects_modified_public_arms_or_verdict(
    synthetic_cli_publication: tuple[Path, Path, Path, dict[str, Any], dict[str, str]], key: str, value: Any
) -> None:
    worktree, _, path, result, environment = synthetic_cli_publication
    path.write_bytes(canonical({**result, key: value}))

    completed = _run_synthetic_verify(worktree, path, environment)

    assert completed.returncode != 0
    assert "public results differ" in completed.stderr


def test_task_verify_cli_rejects_a_different_valid_input_entry(synthetic_cli_publication: tuple[Path, Path, Path, dict[str, Any], dict[str, str]]) -> None:
    worktree, primary, path, result, environment = synthetic_cli_publication
    catalog = DataCatalog(DataRoots.from_env(environment, worktree=worktree))
    second_input = publish_bundle(
        catalog,
        _metadata(
            "annual-rotation-inputs",
            "prices",
            {"fixture": "annual-publication.cli.v1", "seed": 11},
            {"fixture_input": "another-valid-input"},
        ),
        {"fixture-input.json": b'{"source":"another synthetic CLI input"}'},
    )
    path.write_bytes(canonical({**result, "input_entry": second_input}))

    completed = _run_synthetic_verify(worktree, path, environment)

    assert completed.returncode != 0
    assert "input/process identity mismatch" in completed.stderr


_CLI_SOURCE_FILES = (
    "research_core/annual_rotation.py",
    "research_core/annual_statistics.py",
    "research_core/annual_ranking_pool.py",
    "research_core/annual_publication.py",
    "research_core/price_basis.py",
    "research_core/artifact_store.py",
    "research_core/research_data_builder.py",
    "research_core/research_data_catalog.py",
    "research_core/research_data_paths.py",
    "research_core/research_measurement_v1.py",
    "StockProject/engine/data_loader.py",
    "uv.lock",
    "pyproject.toml",
    "tasks/20261013-annual-winner-rotation/run_study.py",
    "tasks/20261013-annual-winner-rotation/mission.md",
    "tasks/20261013-annual-winner-rotation/params/study-v1.json",
)
_CLI_PACKAGE_FILES = (
    "research_core/__init__.py",
    "StockProject/__init__.py",
    "StockProject/engine/__init__.py",
)


@pytest.fixture
def synthetic_cli_publication(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, Any], dict[str, str]]:
    """Create a tiny registered Git worktree and publish only synthetic bundles."""
    repo = Path(__file__).resolve().parents[2]
    primary = tmp_path / "synthetic-primary"
    primary.mkdir()
    git = [
        "git",
        "-c",
        "init.templateDir=",
        "-c",
        f"core.hooksPath={primary / 'disabled-fixture-hooks'}",
        "-c",
        "commit.gpgSign=false",
        "-C",
        str(primary),
    ]
    subprocess.run([*git, "init", "-b", "main"], check=True, capture_output=True, text=True)

    for relative in (*_CLI_SOURCE_FILES, *_CLI_PACKAGE_FILES):
        source_path = repo / relative
        if source_path.is_file():
            target = primary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source_path.read_bytes())
        elif relative in _CLI_SOURCE_FILES:
            raise FileNotFoundError(f"required synthetic CLI source is missing: {relative}")

    package_files = tuple(relative for relative in _CLI_PACKAGE_FILES if (repo / relative).is_file())
    subprocess.run([*git, "add", "--", *_CLI_SOURCE_FILES, *package_files], check=True, capture_output=True, text=True)
    subprocess.run(
        [*git, "-c", "user.name=Synthetic fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "synthetic CLI fixture"],
        check=True,
        capture_output=True,
        text=True,
    )
    worktree = primary / ".worktrees" / "annual-publication-cli"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([*git, "worktree", "add", "--detach", str(worktree), "HEAD"], check=True, capture_output=True, text=True)

    environment = os.environ.copy()
    environment[DATA_ROOT_ENV] = str(primary / "research_data")
    catalog = DataCatalog(DataRoots.from_env(environment, worktree=worktree))
    parameters = {"fixture": "annual-publication.cli.v1", "seed": 11}
    input_entry = publish_bundle(
        catalog,
        _metadata("annual-rotation-inputs", "prices", parameters, {"fixture_input": "synthetic-cli-input"}),
        {"fixture-input.json": b'{"source":"synthetic CLI only"}'},
    )
    committed_head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    source_files = (*_CLI_SOURCE_FILES,)
    source = {
        "head": committed_head,
        "files": {relative: hashlib.sha256((worktree / relative).read_bytes()).hexdigest() for relative in source_files},
    }
    public = {
        "schema": "annual-rotation-results.v1",
        "verdict": "synthetic-cli-verification-only",
        "input_entry": input_entry,
        "source": source,
        "arms": {"fixture": {"years": [{"year": 2021, "net_multiplier": 1.0}]}},
    }
    process_entry = publish_bundle(
        catalog,
        _metadata(
            "annual-rotation-process",
            "episodes",
            parameters,
            {
                "input_version": input_entry["version_id"],
                "input_manifest_sha256": input_entry["manifest"]["sha256"],
                "source": source,
            },
        ),
        {
            "results.json": canonical(public),
            "study.json": canonical(parameters),
            "candidates.json.gz": gzip.compress(canonical([{"code": "1101", "year": 2021}, {"code": "2330", "year": 2021}])),
            "execution.json": canonical({"row_count": 2, "worker_count": 1}),
            **{f"implementation/{relative}": (worktree / relative).read_bytes() for relative in source_files},
        },
        lineage={"input_entry": input_entry},
    )
    result = {**public, "process_entry": process_entry}
    path = tmp_path / "synthetic-cli-public-result.json"
    write_json(path, result)
    return worktree, primary, path, result, environment


def _run_synthetic_verify(worktree: Path, path: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    runner = worktree / "tasks/20261013-annual-winner-rotation/run_study.py"
    return subprocess.run(
        [sys.executable, str(runner), "verify", "--output", str(path)],
        cwd=worktree,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def test_reuse_rank_rows_accepts_holding_tail_only_change(synthetic_cli_publication: tuple[Path, Path, Path, dict[str, Any], dict[str, str]]) -> None:
    worktree, _, path, result, environment = synthetic_cli_publication
    module_path = worktree / "research_core/annual_rotation.py"
    module_path.write_bytes(module_path.read_bytes() + b"\n# synthetic holding-tail revision\n")
    catalog = DataCatalog(DataRoots.from_env(environment, worktree=worktree))
    parameters = {"fixture": "annual-publication.cli.v1", "seed": 11}

    reused = reuse_rank_rows(
        path,
        catalog,
        repo=worktree,
        input_entry=result["input_entry"],
        parameters=parameters,
    )

    assert reused["rows"] == [{"code": "1101", "year": 2021}, {"code": "2330", "year": 2021}]
    assert reused["performance"]["rank_reuse"]["entry"] == result["process_entry"]
    assert reused["performance"]["rank_reuse"]["new_stocks_calculated"] == 0


@pytest.mark.parametrize("change", ["ranking_prefix", "dependency", "scope", "parameters"])
def test_reuse_rank_rows_rejects_incompatible_synthetic_changes(
    synthetic_cli_publication: tuple[Path, Path, Path, dict[str, Any], dict[str, str]], change: str
) -> None:
    worktree, _, path, result, environment = synthetic_cli_publication
    catalog = DataCatalog(DataRoots.from_env(environment, worktree=worktree))
    parameters = {"fixture": "annual-publication.cli.v1", "seed": 11}
    if change == "ranking_prefix":
        target = worktree / "research_core/annual_rotation.py"
        target.write_bytes(b"# changed synthetic ranking prefix\n" + target.read_bytes())
        expected_error = "ranking/economic implementation prefix changed"
    elif change == "dependency":
        target = worktree / "research_core/annual_ranking_pool.py"
        target.write_bytes(target.read_bytes() + b"\n# changed synthetic ranking dependency\n")
        expected_error = "ranking dependency changed"
    elif change == "scope":
        target = worktree / "tasks/20261013-annual-winner-rotation/run_study.py"
        original = target.read_text(encoding="utf-8")
        signature = "def scope(prices: pd.DataFrame, types: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:\n"
        assert signature in original
        target.write_text(original.replace(signature, signature + "    scope_fixture_marker = True\n", 1), encoding="utf-8", newline="\n")
        expected_error = "historical scope implementation changed"
    else:
        parameters = {**parameters, "fixture_parameter": "changed"}
        expected_error = "rank reuse inputs/parameters mismatch"

    with pytest.raises(ValueError, match=expected_error):
        reuse_rank_rows(
            path,
            catalog,
            repo=worktree,
            input_entry=result["input_entry"],
            parameters=parameters,
        )


def test_json_delivery_receipt_accepts_formatting_differences_and_is_repeatable() -> None:
    original = b'{"amount":0.0,"flag":true,"items":[1,2],"nested":{"a":1,"b":2}}'
    delivery = b'{\n  "nested": { "b": 2, "a": 1 },\n  "items": [1, 2], "flag": true, "amount": 0\n}'
    original_before = original[:]

    receipt = annual_publication.json_delivery_receipt(original, delivery)
    repeated = annual_publication.json_delivery_receipt(original, delivery)

    assert receipt == repeated
    assert receipt == {
        "schema": "annual-json-delivery.v1",
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "delivery_sha256": hashlib.sha256(delivery).hexdigest(),
        "source_bytes": len(original),
        "delivery_bytes": len(delivery),
        "content_equal": True,
    }
    assert original == original_before


@pytest.mark.parametrize(
    ("original", "delivery"),
    [
        (b'{"value":1}', b'{"value":2}'),
        (b'{"value":1}', b'{"value":1,"extra":true}'),
        (b'{"items":[1,2]}', b'{"items":[2,1]}'),
        (b'{"value":true}', b'{"value":1}'),
    ],
)
def test_json_delivery_receipt_rejects_semantically_different_content(original: bytes, delivery: bytes) -> None:
    with pytest.raises(ValueError):
        annual_publication.json_delivery_receipt(original, delivery)


@pytest.mark.parametrize(
    "invalid",
    [
        b'{"value":1,"value":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
    ],
)
@pytest.mark.parametrize("invalid_side", ["original", "delivery"])
def test_json_delivery_receipt_rejects_duplicate_keys_and_nonfinite_numbers(invalid: bytes, invalid_side: str) -> None:
    valid = b'{"value":1}'
    original, delivery = (invalid, valid) if invalid_side == "original" else (valid, invalid)

    with pytest.raises(ValueError):
        annual_publication.json_delivery_receipt(original, delivery)


@pytest.mark.parametrize("invalid_side", ["original", "delivery"])
def test_json_delivery_receipt_rejects_invalid_utf8(invalid_side: str) -> None:
    valid = b'{"value":1}'
    invalid = b'{"value":"\xff"}'
    original, delivery = (invalid, valid) if invalid_side == "original" else (valid, invalid)

    with pytest.raises(ValueError):
        annual_publication.json_delivery_receipt(original, delivery)


def test_finalize_delivery_cli_rejects_unowned_output_paths_without_creating_them(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    script = repo / "tasks/20261013-annual-winner-rotation/finalize_delivery.py"
    output = tmp_path / "unowned_delivery"
    pin_output = tmp_path / "pin.json"

    completed = subprocess.run(
        [sys.executable, str(script), "--output", str(output), "--pin-output", str(pin_output)],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )

    assert completed.returncode != 0
    assert "new delivery must use this task's delivery-v1 directory" in completed.stderr
    assert not output.exists()
    assert not pin_output.exists()


def _format_synthetic_json(paths: list[Path]) -> None:
    for path in paths:
        parsed = json.loads(path.read_bytes())
        path.write_text(json.dumps(parsed, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def _create_synthetic_delivery(
    tmp_path: Path,
) -> tuple[
    dict[str, bytes],
    Path,
    dict[str, Any],
    dict[str, str],
    dict[str, str],
    dict[str, Any],
    bytes,
    list[list[str]],
]:
    originals = {
        "input-pin.json": b'{"data_id":"synthetic-input","version_id":"v1"}',
        "results.json": b'{"verdict":"synthetic-only","arms":[{"year":2021,"value":1.0}]}',
    }
    formatter_identity = {"name": "synthetic-json-formatter", "version": "1"}
    implementation_sha256 = {"research_core/annual_publication.py": "a" * 64}
    references = {"input_version": "synthetic-input-v1"}
    output = tmp_path / "delivery-v1"
    format_calls: list[list[str]] = []

    def tracked_formatter(paths: list[Path]) -> None:
        format_calls.append([path.name for path in paths])
        _format_synthetic_json(paths)

    receipt = annual_publication.finalize_json_delivery_set(
        originals,
        output,
        references=references,
        formatter_identity=formatter_identity,
        implementation_sha256=implementation_sha256,
        formatter=tracked_formatter,
    )
    return (
        originals,
        output,
        formatter_identity,
        implementation_sha256,
        references,
        receipt,
        (output / "receipt.json").read_bytes(),
        format_calls,
    )


def _delivery_tree_bytes(output: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}


def test_finalize_json_delivery_set_formats_hashes_and_reuses_existing_version_read_only(tmp_path: Path) -> None:
    (
        originals,
        output,
        formatter_identity,
        implementation_sha256,
        references,
        receipt,
        completed_receipt,
        initial_calls,
    ) = _create_synthetic_delivery(tmp_path)
    original_snapshot = dict(originals)
    before_reuse = _delivery_tree_bytes(output)
    calls: list[list[str]] = []

    def tracked_formatter(paths: list[Path]) -> None:
        calls.append([path.name for path in paths])
        _format_synthetic_json(paths)

    # The first finalization formats every file and then the receipt.
    assert set(receipt["files"]) == set(originals)
    assert {name for call in initial_calls for name in call} == set(originals) | {"receipt.json"}
    assert "receipt.json" in initial_calls[-1]
    for name, original in originals.items():
        delivered = (output / name).read_bytes()
        assert json.loads(delivered) == json.loads(original)
        assert receipt["files"][name] == annual_publication.json_delivery_receipt(original, delivered)
    assert (output / "receipt.json").read_bytes() == completed_receipt
    assert originals == original_snapshot

    reused = annual_publication.finalize_json_delivery_set(
        originals,
        output,
        references=references,
        formatter_identity=formatter_identity,
        implementation_sha256=implementation_sha256,
        formatter=tracked_formatter,
        completed_receipt=completed_receipt,
    )

    assert reused == receipt
    assert calls == []
    assert _delivery_tree_bytes(output) == before_reuse
    assert originals == original_snapshot


@pytest.mark.parametrize("identity_change", ["formatter", "source", "implementation", "references"])
def test_finalize_json_delivery_set_rejects_changed_identity_without_mutating_completed_version(tmp_path: Path, identity_change: str) -> None:
    (
        originals,
        output,
        formatter_identity,
        implementation_sha256,
        references,
        _,
        completed_receipt,
        _,
    ) = _create_synthetic_delivery(tmp_path)
    before = _delivery_tree_bytes(output)
    changed_originals = dict(originals)
    changed_formatter = dict(formatter_identity)
    changed_implementation = dict(implementation_sha256)
    changed_references = dict(references)
    if identity_change == "formatter":
        changed_formatter["version"] = "2"
    elif identity_change == "source":
        changed_originals["results.json"] = b'{"verdict":"changed source"}'
    elif identity_change == "implementation":
        changed_implementation["research_core/annual_publication.py"] = "b" * 64
    else:
        changed_references["input_version"] = "synthetic-input-v2"

    with pytest.raises(ValueError):
        annual_publication.finalize_json_delivery_set(
            changed_originals,
            output,
            references=changed_references,
            formatter_identity=changed_formatter,
            implementation_sha256=changed_implementation,
            formatter=_format_synthetic_json,
            completed_receipt=completed_receipt,
        )

    assert _delivery_tree_bytes(output) == before
    assert originals["results.json"] == b'{"verdict":"synthetic-only","arms":[{"year":2021,"value":1.0}]}'


def test_finalize_json_delivery_set_rejects_sealed_receipt_byte_mismatch_without_mutation(tmp_path: Path) -> None:
    (
        originals,
        output,
        formatter_identity,
        implementation_sha256,
        references,
        _,
        completed_receipt,
        _,
    ) = _create_synthetic_delivery(tmp_path)
    before = _delivery_tree_bytes(output)

    with pytest.raises(ValueError):
        annual_publication.finalize_json_delivery_set(
            originals,
            output,
            references=references,
            formatter_identity=formatter_identity,
            implementation_sha256=implementation_sha256,
            formatter=_format_synthetic_json,
            completed_receipt=completed_receipt + b" ",
        )

    assert _delivery_tree_bytes(output) == before


def test_finalize_json_delivery_set_formatter_failure_preserves_previous_version_and_source_bytes(tmp_path: Path) -> None:
    (
        originals,
        output_v1,
        formatter_identity,
        implementation_sha256,
        references,
        _,
        completed_receipt,
        _,
    ) = _create_synthetic_delivery(tmp_path)
    source_snapshot = dict(originals)
    previous_delivery = _delivery_tree_bytes(output_v1)
    output_v2 = tmp_path / "delivery-v2"

    def failing_formatter(paths: list[Path]) -> None:
        paths[0].write_bytes(b"synthetic partial formatter output")
        raise RuntimeError("synthetic formatter failure")

    with pytest.raises(RuntimeError, match="synthetic formatter failure"):
        annual_publication.finalize_json_delivery_set(
            originals,
            output_v2,
            references=references,
            formatter_identity=formatter_identity,
            implementation_sha256=implementation_sha256,
            formatter=failing_formatter,
        )

    assert output_v2.exists()
    assert _delivery_tree_bytes(output_v1) == previous_delivery
    assert originals == source_snapshot
    assert completed_receipt == (output_v1 / "receipt.json").read_bytes()


def test_finalize_json_locator_formats_and_repeats_with_identical_bytes_and_receipt(tmp_path: Path) -> None:
    path = tmp_path / "delivery-pin.json"
    entry = {
        "data_id": "synthetic-delivery",
        "version_id": "synthetic-v1",
        "manifest": {"sha256": "c" * 64},
    }
    calls: list[list[str]] = []

    def formatter(paths: list[Path]) -> None:
        calls.append([item.name for item in paths])
        _format_synthetic_json(paths)

    first_receipt = annual_publication.finalize_json_locator(path, entry, formatter=formatter)
    first_bytes = path.read_bytes()
    second_receipt = annual_publication.finalize_json_locator(path, entry, formatter=formatter)
    second_bytes = path.read_bytes()

    assert first_receipt == second_receipt
    assert first_bytes == second_bytes
    assert json.loads(first_bytes) == entry
    assert first_receipt == annual_publication.json_delivery_receipt(canonical(entry), first_bytes)
    assert calls == [[path.name], [path.name]]


def test_finalize_json_locator_rejects_mismatched_existing_entry_before_formatting(tmp_path: Path) -> None:
    path = tmp_path / "delivery-pin.json"
    existing = {"data_id": "synthetic-delivery", "version_id": "old-version"}
    requested = {"data_id": "synthetic-delivery", "version_id": "new-version"}
    path.write_bytes(canonical(existing))
    original_bytes = path.read_bytes()
    calls: list[list[Path]] = []

    def formatter(paths: list[Path]) -> None:
        calls.append(paths)
        _format_synthetic_json(paths)

    with pytest.raises(ValueError):
        annual_publication.finalize_json_locator(path, requested, formatter=formatter)

    assert calls == []
    assert path.read_bytes() == original_bytes
