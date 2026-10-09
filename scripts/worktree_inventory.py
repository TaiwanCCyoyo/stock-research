"""Read-only Git worktree inventory; observations never authorize removal."""

import argparse
import json
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOGGER = logging.getLogger("worktree_inventory")
COMMAND_TIMEOUT = 30
PR_LIMIT = 1000


def run_command(args: list[str], cwd: Path) -> bytes:
    """Run bounded read-only queries without Git's optional index writes."""
    LOGGER.debug("Query %s in %s", args, cwd)
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.warning("Query failed: %s", exc)
        raise RuntimeError(str(exc)) from exc
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        LOGGER.warning("%s failed (%s): %s", args[0], result.returncode, error)
        raise RuntimeError(f"{args[0]} exited {result.returncode}: {error}")
    return result.stdout


def git(repo: Path, *args: str) -> bytes:
    return run_command(["git", *args], repo)


def parse_worktrees(output: bytes) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for field in output.split(b"\0"):
        if not field:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = field.partition(b" ")
        if key == b"worktree":
            current["path"] = os.fsdecode(value)
        elif key == b"HEAD":
            current["head"] = value.decode("ascii")
        elif key == b"branch":
            current["branch"] = os.fsdecode(value).removeprefix("refs/heads/")
        elif key in (b"detached", b"bare"):
            current[key.decode("ascii")] = True
        elif key in (b"locked", b"prunable"):
            current[key.decode("ascii")] = os.fsdecode(value) or True
    if current:
        entries.append(current)
    return entries


def status_counts(output: bytes) -> dict[str, int]:
    tracked = untracked = 0
    fields = iter(output.split(b"\0"))
    for field in fields:
        if not field:
            continue
        code = field[:2]
        if code == b"??":
            untracked += 1
        elif code != b"!!":
            tracked += 1
        if b"R" in code or b"C" in code:
            next(fields, None)  # Rename/copy records have a second NUL-delimited path.
    return {"tracked_dirty": tracked, "untracked": untracked}


def lexical_path(path: Path) -> Path:
    """Normalize absolute spelling without resolving filesystem links."""
    return Path(os.path.normcase(os.path.abspath(path)))


def ignored_size(repo: Path, output: bytes, excluded_worktrees: list[Path] | None = None) -> dict[str, Any]:
    """Count bytes without links or other registered worktrees' contents."""
    measured = 0
    errors: list[str] = []
    excluded = {lexical_path(path) for path in excluded_worktrees or []}
    excluded_paths: set[str] = set()
    seen: set[Path] = set()
    pending = [repo / os.fsdecode(item) for item in output.split(b"\0") if item]
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        normalized = lexical_path(path)
        boundary = next((root for root in excluded if normalized == root or root in normalized.parents), None)
        if boundary is not None:
            excluded_paths.add(str(boundary))
            LOGGER.debug("Ignored scan excludes registered worktree %s", boundary)
            continue
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
                errors.append(f"Not followed (symlink or reparse point): {path}")
            elif stat.S_ISDIR(info.st_mode):
                with os.scandir(path) as children:
                    pending.extend(Path(child.path) for child in children)
            elif stat.S_ISREG(info.st_mode):
                measured += info.st_size
            else:
                errors.append(f"Unknown file type: {path}")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        LOGGER.warning("Ignored size incomplete in %s: %s", repo, errors)
    return {
        "bytes": None if errors else measured,
        "measured_bytes": measured,
        "errors": errors,
        "excluded_paths": sorted(excluded_paths),
    }


def classify_prs(prs: list[dict[str, Any]], head: str) -> dict[str, Any]:
    if not prs:
        return {"classification": "no_pr", "prs": []}
    matches = [pr for pr in prs if pr.get("headRefOid") == head]
    selected = matches[0] if len(matches) == 1 else (prs[0] if len(prs) == 1 else None)
    if selected is None:
        return {"classification": "ambiguous", "prs": prs, "reason": "Multiple PRs without a unique worktree HEAD match"}
    state = selected.get("state")
    if not isinstance(state, str):
        return {"classification": "unknown", "prs": prs, "reason": "Unrecognized PR state"}
    classification = {"OPEN": "open_pr", "MERGED": "merged_pr", "CLOSED": "closed_unmerged_pr"}.get(state)
    if classification is None or not isinstance(selected.get("number"), int):
        return {"classification": "unknown", "prs": prs, "reason": "Unrecognized PR response"}
    return {
        "classification": classification,
        "number": selected["number"],
        "state": state,
        "matches_head": selected.get("headRefOid") == head,
        "selected": selected,
        "prs": prs,
    }


def repository_identity(url: str) -> str:
    if "://" not in url and ":" in url:
        host, path = url.split(":", 1)
        host = host.rsplit("@", 1)[-1]
    else:
        parsed = urlsplit(url)
        host, path = parsed.hostname or "", parsed.path
    parts = path.strip("/").removesuffix(".git").split("/")
    if not host or len(parts) != 2 or any(not part for part in parts):
        raise ValueError("Cannot establish repository identity")
    return f"{host}/{'/'.join(parts)}".lower()


def verify_source_repository(repo: Path, branch: str) -> str:
    remote = git(repo, "for-each-ref", "--format=%(upstream:remotename)", f"refs/heads/{branch}").decode().strip() or "origin"
    source = repository_identity(git(repo, "remote", "get-url", remote).decode().strip())
    target = json.loads(run_command(["gh", "repo", "view", "--json", "url"], repo))
    if not isinstance(target, dict) or not isinstance(target.get("url"), str):
        raise ValueError("Cannot establish PR destination repository")
    if source != repository_identity(target["url"]):
        raise ValueError("Branch source remote differs from PR destination; association unknown")
    return source


def query_pr(repo: Path, branch: str, head: str) -> dict[str, Any]:
    try:
        source = verify_source_repository(repo, branch)
        output = run_command(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--head",
                branch,
                "--limit",
                str(PR_LIMIT),
                "--json",
                "number,state,mergedAt,headRefOid,baseRefName,url,isCrossRepository",
            ],
            repo,
        )
        prs = json.loads(output)
        if not isinstance(prs, list) or any(not isinstance(pr, dict) for pr in prs):
            raise ValueError("Expected a list of PR objects")
        if len(prs) >= PR_LIMIT:
            raise ValueError("PR query reached its limit; results may be incomplete")
        same_repository = [pr for pr in prs if pr.get("isCrossRepository") is False]
        if prs and not same_repository:
            raise ValueError("PR head repository differs or is unknown; association unknown")
        result = classify_prs(same_repository, head)
        result["source_repository"] = source
        LOGGER.debug("Branch %s PR classification: %s", branch, result["classification"])
        return result
    except (RuntimeError, ValueError) as exc:
        LOGGER.warning("PR query unknown for %s: %s", branch, exc)
        return {"classification": "unknown", "reason": str(exc)}


def inventory(repo: Path, no_pr: bool = False) -> dict[str, Any]:
    entries = parse_worktrees(git(repo, "worktree", "list", "--porcelain", "-z"))
    registered_paths = [Path(entry["path"]) for entry in entries]
    LOGGER.info("Inspecting %s worktrees", len(entries))
    for entry in entries:
        path = Path(entry["path"])
        other_worktrees = [registered for registered in registered_paths if lexical_path(path) in lexical_path(registered).parents]
        entry["errors"] = []
        entry["status"] = None
        entry["ignored"] = {"bytes": None, "measured_bytes": None, "errors": [], "excluded_paths": []}
        entry["last_commit_date"] = None
        if entry.get("bare"):
            entry["pr"] = {"classification": "unknown", "reason": "Bare repository"}
            continue
        for name, action in (
            ("status", lambda: status_counts(git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all"))),
            ("ignored", lambda: ignored_size(path, git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"), other_worktrees)),
            ("last_commit_date", lambda: git(path, "log", "-1", "--format=%cI", "HEAD").decode("utf-8").strip()),
        ):
            try:
                entry[name] = action()
            except RuntimeError as exc:
                entry["errors"].append(f"{name}: {exc}")
        if entry.get("detached"):
            entry["probe_candidate"] = True
            entry["pr"] = {"classification": "unknown", "reason": "Detached HEAD; probe candidate only, ownership unknown"}
        elif no_pr:
            entry["pr"] = {"classification": "unknown", "reason": "PR lookup disabled (--no-pr)"}
        else:
            entry["pr"] = query_pr(path, entry.get("branch", ""), entry.get("head", ""))
    return {"repository": str(repo), "worktrees": entries}


def emit_line(value: str) -> None:
    sys.stdout.write(value + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", help="Emit structured JSON")
    parser.add_argument("--no-pr", action="store_true", help="Skip PR lookup (reported as unknown)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        result = inventory(args.repo.resolve(), args.no_pr)
    except RuntimeError as exc:
        LOGGER.error("Inventory unavailable: %s", exc)
        return 1
    if args.json:
        emit_line(json.dumps(result, indent=2, ensure_ascii=True))
    else:
        for entry in result["worktrees"]:
            emit_line(entry["path"])
            branch = entry.get("branch", "detached" if entry.get("detached") else "bare")
            emit_line(f"  branch={branch} HEAD={entry.get('head', 'unknown')} last_commit={entry['last_commit_date']}")
            emit_line(f"  PR={entry['pr']['classification']} number={entry['pr'].get('number')} state={entry['pr'].get('state')}")
            if "selected" in entry["pr"]:
                selected = entry["pr"]["selected"]
                emit_line(
                    f"  PR base={selected.get('baseRefName', 'unknown')} "
                    f"final_head={selected.get('headRefOid', 'unknown')} matches_head={entry['pr']['matches_head']}"
                )
                if not entry["pr"]["matches_head"]:
                    emit_line("  WARNING: Current HEAD differs from PR final head; do not clean up based on this PR state.")
            emit_line(f"  status={entry['status']} ignored_bytes={entry['ignored']['bytes']}")
            for excluded_path in entry["ignored"].get("excluded_paths", []):
                emit_line(f"  measured separately: {excluded_path}")
            for message in entry["errors"] + entry["ignored"]["errors"]:
                emit_line(f"  unknown: {message}")
            if entry["pr"].get("reason"):
                emit_line(f"  PR detail: {entry['pr']['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
