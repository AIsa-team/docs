#!/usr/bin/env python3
"""Export AIsa-team/agent-skills platform/aisa into the Mintlify root skill.md.

Mintlify overrides the auto-generated Docs skill with a repo-root skill.md.
The one documented transform rewrites the relative LICENSE link to the pinned
raw GitHub URL so the license stays at the official source. Merge the Skill
commit before this pin.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

SOURCE_SHA = "e7809490a186af77c4b96a5c1cfeea1ee39ce4f9"
SOURCE_SKILL = "platform/aisa/SKILL.md"
EXPORTED = "skill.md"
EXPORTED_SHA256 = "8ccb3903800b3b97a093d36e1c90bee4d70ca705ada6d2a2dc59ef132d0b636f"
LICENSE_RELATIVE = "MIT — see [LICENSE](LICENSE)."
LICENSE_CANONICAL_URL = (
    f"https://raw.githubusercontent.com/AIsa-team/agent-skills/"
    f"{SOURCE_SHA}/platform/aisa/LICENSE"
)
LICENSE_ABSOLUTE = f"MIT — see [LICENSE]({LICENSE_CANONICAL_URL})."


def export_text(skill: str) -> str:
    if LICENSE_RELATIVE not in skill:
        raise SystemExit(f"{SOURCE_SKILL} is missing the relative LICENSE link")
    return skill.replace(LICENSE_RELATIVE, LICENSE_ABSOLUTE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-dir", type=Path, help="platform/aisa directory at the pinned SHA")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    source_dir = args.source_dir.resolve() if args.source_dir else None
    exported = root / EXPORTED

    if args.check:
        errors: list[str] = []
        if not exported.is_file():
            errors.append(f"missing {EXPORTED}")
        else:
            actual = exported.read_text(encoding="utf-8")
            digest = hashlib.sha256(actual.encode()).hexdigest()
            if digest != EXPORTED_SHA256:
                errors.append(f"{EXPORTED} sha256 {digest} != pinned {EXPORTED_SHA256}")
            if LICENSE_RELATIVE in actual:
                errors.append(f"{EXPORTED} still has a relative LICENSE link")
            if LICENSE_CANONICAL_URL not in actual:
                errors.append(f"{EXPORTED} is missing the pinned LICENSE URL")
            if source_dir is not None:
                expected = export_text((source_dir / "SKILL.md").read_text(encoding="utf-8"))
                if actual != expected:
                    errors.append(f"{EXPORTED} drifted from source-dir at {SOURCE_SHA}")
        if errors:
            print("canonical aisa skill check failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(f"{EXPORTED} matches {SOURCE_SHA}")
        return 0

    if source_dir is None:
        raise SystemExit("--source-dir is required to write the export")
    text = export_text((source_dir / "SKILL.md").read_text(encoding="utf-8"))
    exported.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    print(f"wrote {exported.relative_to(root)} from {SOURCE_SHA} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
