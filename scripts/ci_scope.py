"""Select conservative CI domains from merge-base diffs and execute explicit plans."""

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("ci_test_domains.json")


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_inventory(root: Path, manifest: dict[str, Any]) -> list[str]:
    return sorted({
        p.relative_to(root).as_posix()
        for folder in manifest["test_roots"]
        for p in (root / folder).rglob("*.py")
        if any(fnmatch.fnmatchcase(p.name, pattern) for pattern in manifest["pytest_file_patterns"])
    })


def consumer_closure(names: set[str], manifest: dict[str, Any]) -> set[str]:
    pending = list(names)
    selected: set[str] = set()
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in manifest["domains"]:
            raise ValueError(f"Unknown consumer domain: {name}")
        selected.add(name)
        pending.extend(manifest["domains"][name].get("consumers", []))
    return selected


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def inventory_domains(root: Path, manifest: dict[str, Any]) -> dict[str, list[str]]:
    return {path: [name for name, domain in manifest["domains"].items() if matches(path, domain["tests"])] for path in test_inventory(root, manifest)}


REFERENCE_ROOTS = (
    "research_core",
    "research_api",
    "scripts",
    "StockProject",
    "tests",
    "tasks",
    "research_web/src",
    "research_web/scripts",
    ".claude/hooks",
    ".codex/hooks",
)
REFERENCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs"}
# Code may name a record through its configuration, so code roots also count config files as readers.
CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}
REFERENCE_SKIP_PARTS = {"node_modules", "__pycache__", ".venv", "dist"}


def domain_owners(path: str, manifest: dict[str, Any]) -> list[str]:
    return [name for name, domain in manifest["domains"].items() if matches(path, domain["paths"]) or matches(path, domain["tests"])]


def reference_key(path: str) -> str | None:
    """Text by which code would reach an unmapped record: its task id, or a docs file name."""
    parts = path.split("/")
    if parts[0] == "tasks" and len(parts) >= 3:
        return parts[1]
    if parts[0] == "docs" and len(parts) >= 2 and not path.endswith(".py"):
        return parts[-1]
    return None


class ReferenceIndex:
    """Lazily read source files once to find which code or tests mention a record."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._texts: dict[str, str] | None = None

    def texts(self) -> dict[str, str]:
        if self._texts is None:
            self._texts = {}
            for folder in REFERENCE_ROOTS:
                suffixes = REFERENCE_SUFFIXES if folder == "tasks" else REFERENCE_SUFFIXES | CONFIG_SUFFIXES
                for file in (self.root / folder).rglob("*"):
                    if file.suffix in suffixes and file.is_file() and not REFERENCE_SKIP_PARTS & set(file.parts):
                        self._texts[file.relative_to(self.root).as_posix()] = file.read_text(encoding="utf-8", errors="replace")
        return self._texts

    def referencing(self, key: str) -> list[str]:
        return sorted(path for path, text in self.texts().items() if key in text)


def route_by_reference(path: str, manifest: dict[str, Any], references: ReferenceIndex) -> tuple[list[str], set[str], bool] | None:
    """Route an unmapped task/docs record to the tests and owned code that mention it.

    Returns None (full validation) when unmapped or shared code reads it. Files in the same
    task directory are that study's own material, not readers of it.
    """
    key = reference_key(path)
    assert key is not None
    task_dir = f"tasks/{key}/" if path.startswith("tasks/") else None
    inventory = set(manifest["reviewed_tests"])
    owners = {"task_records" if task_dir else "prose"}
    tests: set[str] = set()
    for reference in references.referencing(key):
        if task_dir and reference.startswith(task_dir):
            continue
        if reference in inventory:
            tests.add(reference)
            continue
        code_owners = domain_owners(reference, manifest)
        if not code_owners or matches(reference, manifest["full_paths"]):
            return None
        owners.update(code_owners)
    return sorted(owners), tests, "/web-report/" in path


def make_plan(changes: list[tuple[str, str]], *, root: Path = ROOT, force_full: bool = False) -> dict[str, Any]:
    manifest = load_manifest()
    inventory = test_inventory(root, manifest)
    selected_domains: set[str] = set()
    changed_tests: set[str] = set()
    reasons: list[str] = []
    full = force_full
    frontend = force_full
    if set(inventory) != set(manifest["reviewed_tests"]):
        full = True
        reasons.append("Test inventory differs from reviewed domain manifest; full safety fallback")
    if force_full:
        reasons.append("Explicit full validation (manual request or initial history)")
    references = ReferenceIndex(root)
    for status, raw_path in changes:
        path = raw_path.replace("\\", "/")
        if path in inventory:
            changed_tests.add(path)
        if matches(path, manifest["full_paths"]) and not matches(path, manifest.get("full_path_exceptions", [])):
            full = True
            reasons.append(f"{status} {path}: shared/configuration safety fallback")
            continue
        # New and modified files route alike: no unchanged code can import a file that did not exist,
        # so a new file's impact is the domain that owns its location plus the changed tests that use it.
        owners = domain_owners(path, manifest)
        if path.startswith("research_web/"):
            frontend = True
            reasons.append(f"{status} {path}: frontend lint/build/tests")
            if not owners:
                owners = ["web"]
        if not owners and path in inventory:
            reasons.append(f"{status} {path}: unmapped test file runs itself")
            continue
        if not owners and reference_key(path) is not None:
            routed = route_by_reference(path, manifest, references)
            if routed is None:
                full = True
                reasons.append(f"{status} {path}: referenced by unmapped code; full validation")
                continue
            owners, referencing_tests, needs_frontend = routed
            changed_tests.update(referencing_tests)
            frontend = frontend or needs_frontend
            reasons.append(f"{status} {path}: unmapped record; {len(referencing_tests)} referencing test file(s)")
        if not owners:
            full = True
            reasons.append(f"{status} {path}: no reviewed impact mapping; full validation")
        for name in owners:
            selected_domains.add(name)
            reasons.append(f"{status} {path}: {name} and declared downstream consumers")
    if not changes and not force_full:
        selected_domains.add("hooks")
        reasons.append("Empty diff: repository and selector contracts remain checked")
    selected_domains = consumer_closure(selected_domains, manifest)
    patterns = [pattern for name in selected_domains for pattern in manifest["domains"][name]["tests"]]
    selected = inventory if full else [path for path in inventory if matches(path, patterns) or path in changed_tests]
    frontend = full or frontend or any(manifest["domains"][name].get("frontend", False) for name in selected_domains)
    if not selected and not frontend:
        full = True
        frontend = True
        selected = inventory
        reasons.append("Empty selected validation set: full safety fallback")
    if not inventory:
        raise ValueError("No Python test inventory available; refusing an empty green result")
    return {
        "version": 1,
        "full": full,
        "frontend": frontend,
        "python_tests": selected,
        "domains": sorted(selected_domains),
        "reasons": reasons,
        "inventory_count": len(inventory),
    }


def git_output(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True, timeout=60).stdout


def resolve_commit(ref: str) -> str:
    return git_output("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode("ascii").strip()


def parse_changes(data: bytes) -> list[tuple[str, str]]:
    fields = data.split(b"\0")
    if not fields or fields[-1] != b"":
        raise ValueError("Truncated NUL-delimited Git diff")
    fields.pop()
    changes: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        status = fields[index].decode("ascii")
        index += 1
        if not status or status[0] not in "ACDMRTUXB":
            raise ValueError(f"Unrecognized Git status: {status}")
        count = 2 if status[0] in "RC" else 1
        if index + count > len(fields):
            raise ValueError("Incomplete rename/delete diff")
        for field in fields[index : index + count]:
            changes.append((status[0], os.fsdecode(field)))
        index += count
    return changes


def select_plan(base: str, head: str, *, force_full: bool = False) -> dict[str, Any]:
    head_sha = resolve_commit(head)
    if base == "0" * 40:
        return make_plan([], force_full=True)
    base_sha = resolve_commit(base)
    merge_base = git_output("merge-base", base_sha, head_sha).decode("ascii").strip()
    changes = parse_changes(git_output("diff", "--name-status", "--find-renames", "-z", merge_base, head_sha, "--"))
    plan = make_plan(changes, force_full=force_full)
    plan["merge_base"] = merge_base
    plan["head"] = head_sha
    return plan


def execute_plan(plan: dict[str, Any], *, root: Path = ROOT) -> int:
    inventory = set(test_inventory(root, load_manifest()))
    tests = plan["python_tests"]
    if not isinstance(tests, list) or any(not isinstance(path, str) or path not in inventory for path in tests):
        raise ValueError("Plan contains unrecognized or unsafe Python test paths")
    if not tests:
        if not plan.get("frontend"):
            raise ValueError("Refusing empty validation plan")
        return 0
    return subprocess.run([sys.executable, "-m", "pytest", "--durations=20", *tests], cwd=root, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", type=Path, default=Path(".tmp/ci-plan.json"))
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    try:
        if args.inventory:
            sys.stdout.write(json.dumps(inventory_domains(ROOT, load_manifest()), indent=2) + "\n")
            return 0
        if args.execute:
            return execute_plan(json.loads(args.plan.read_text(encoding="utf-8")))
        if args.base is None:
            if not args.full:
                parser.error("--base or explicit --full is required")
            plan = make_plan([], force_full=True)
        else:
            plan = select_plan(args.base, args.head, force_full=args.full)
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        args.plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        sys.stdout.write(json.dumps(plan, indent=2) + "\n")
        if args.output:
            with args.output.open("a", encoding="utf-8") as output:
                output.write(f"run_tests={str(bool(plan['python_tests'])).lower()}\n")
                output.write(f"frontend={str(plan['frontend']).lower()}\n")
                output.write(f"full={str(plan['full']).lower()}\n")
        return 0
    except (subprocess.SubprocessError, OSError, ValueError, KeyError) as exc:
        sys.stderr.write(f"Cannot validate CI scope; refusing to skip: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
