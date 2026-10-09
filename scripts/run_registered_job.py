"""Preflight, explicitly execute, or verify reuse of ONE reviewed local research job."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_core.evidence import EvidenceError, read_json  # noqa: E402
from research_core.jobs import digest, run_job, runtime_identity, verify_reuse  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--approved-sha256")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--execute", action="store_true")
    modes.add_argument("--verify-reuse", action="store_true")
    modes.add_argument("--identity", action="store_true", help="Read-only packet digest and current runtime; not approval")
    args = parser.parse_args()
    try:
        packet = read_json(args.packet) if args.packet else None
        if args.identity:
            result = {"packet_sha256": digest(packet) if packet else None, "runtime": runtime_identity()}
        elif packet is None:
            parser.error("--packet required")
        elif args.verify_reuse:
            if not args.approved_sha256 or digest(packet) != args.approved_sha256:
                parser.error("--approved-sha256 must match the packet, including for reuse")
            result = verify_reuse(args.root, packet)
        else:
            if not args.approved_sha256:
                parser.error("--approved-sha256 required; a digest is not permission to run research")
            result = run_job(args.root, packet, expected_digest=args.approved_sha256, execute=args.execute)
    except subprocess.SubprocessError:
        parser.exit(2, "job process interrupted or timed out; inspect its retained state.json and process.log\n")
    except (EvidenceError, OSError) as error:
        parser.exit(2, f"{error}\n")
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
