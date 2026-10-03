#!/usr/bin/env python3
"""Replay frozen inputs through locked Docs code; diagnostic, not an oracle."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Fresh local directory")
    args = parser.parse_args()
    lock = verify.read_json(verify.PACKAGE / "manifest.json")
    docs = args.docs_worktree.resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=docs, text=True).strip()
    verify.require(head == lock["frozen_revisions"]["docs"]["commit"], "Docs revision differs")
    verify.require(not subprocess.check_output(["git", "status", "--porcelain"], cwd=docs, text=True).strip(), "Docs worktree is dirty")
    verify.require(not args.output.exists(), "Use a fresh output directory")
    archive = verify.ROOT / lock["archive"]["path"]
    verify.require(verify.digest(archive.read_bytes()) == lock["archive"]["sha256"], "Archive digest differs")
    verify.verify_archive(archive, lock["archive"]["files"])
    args.output.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            if not member.name.startswith("input/"):
                continue
            path = args.output / member.name.removeprefix("input/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.extractfile(member).read())
    sys.path.insert(0, str(docs / "scripts"))
    from pull_openapi import stage
    baseline = verify.read_json(args.output / "openapi/coverage.json")
    context = {"offline": True, "baseline_coverage": baseline}
    changes, _ = stage(args.output, args.output / "facts", "https://unused.invalid", with_pages=False, readiness_context=context)
    for path, content in changes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    again = {"offline": True, "baseline_coverage": baseline}
    repeat, _ = stage(args.output, args.output / "facts", "https://unused.invalid", with_pages=False, readiness_context=again)
    verify.require(not repeat, "Repeat replay changes frozen outputs")
    compared = 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            if not member.name.startswith("expected/openapi/"):
                continue
            expected = json.loads(source.extractfile(member).read())
            actual = verify.read_json(args.output / member.name.removeprefix("expected/"))
            verify.require(verify.same(actual, expected), f"Replay differs: {member.name}")
            compared += 1
    receipt = {"scope": "Locked offline implementation replay; not independent semantic or release acceptance",
               "docs_commit": head, "compared_files": compared, "repeat_changes": len(repeat),
               "diagnostic_readiness": context["report"]["status"], "baseline_approval": "draft_unapproved",
               "release_status": "not_assessed"}
    (args.output / "replay-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
