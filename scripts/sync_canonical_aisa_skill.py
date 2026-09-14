#!/usr/bin/env python3
"""Export AIsa-team/agent-skills platform/aisa into the Mintlify root skill.md.

Mintlify overrides the auto-generated Docs skill with a repo-root skill.md.
This copies a pinned canonical SKILL.md and inlines LICENSE so the published
file has no missing relative targets. Merge the Skill commit before this pin.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

SOURCE_SHA = "e7809490a186af77c4b96a5c1cfeea1ee39ce4f9"
SOURCE_SKILL = "platform/aisa/SKILL.md"
SOURCE_LICENSE = "platform/aisa/LICENSE"
EXPORTED = "skill.md"
EXPORTED_SHA256 = "5d46448dee7901c1a687d4b1f49716d3d87555bbfb87ed022823e5afa9e4f15a"
LICENSE_LINK = "MIT — see [LICENSE](LICENSE)."

STALE_GUIDANCE = (
    ("agent-quickstart.mdx", "whoami` is local only"),
    ("zh/agent-quickstart.mdx", "whoami` 只检查本地"),
    ("agent-quickstart-fallbacks.mdx", "~/.aisa/key"),
    ("zh/agent-quickstart-fallbacks.mdx", "~/.aisa/key"),
)


def export_text(skill: str, license_text: str) -> str:
    if LICENSE_LINK not in skill:
        raise SystemExit(f"{SOURCE_SKILL} is missing the LICENSE relative link")
    inlined = "MIT. Full license text:\n\n" + license_text.strip() + "\n"
    return skill.replace(LICENSE_LINK, inlined)


def write_export(root: Path, text: str) -> Path:
    path = root / EXPORTED
    path.write_text(text, encoding="utf-8")
    return path


def check_guidance(root: Path) -> list[str]:
    errors: list[str] = []
    for rel, stale in STALE_GUIDANCE:
        text = (root / rel).read_text(encoding="utf-8")
        if stale in text:
            errors.append(f"{rel}: still contains {stale!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-dir", type=Path, help="platform/aisa directory at the pinned SHA")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    source_dir = args.source_dir.resolve() if args.source_dir else None

    errors = check_guidance(root)
    exported = root / EXPORTED

    if args.check:
        if not exported.is_file():
            errors.append(f"missing {EXPORTED}")
        else:
            actual = exported.read_text(encoding="utf-8")
            digest = hashlib.sha256(actual.encode()).hexdigest()
            if digest != EXPORTED_SHA256:
                errors.append(f"{EXPORTED} sha256 {digest} != pinned {EXPORTED_SHA256}")
            if LICENSE_LINK in actual:
                errors.append(f"{EXPORTED} still has a relative LICENSE link")
            if source_dir is not None:
                expected = export_text(
                    (source_dir / "SKILL.md").read_text(encoding="utf-8"),
                    (source_dir / "LICENSE").read_text(encoding="utf-8"),
                )
                if actual != expected:
                    errors.append(f"{EXPORTED} drifted from source-dir at {SOURCE_SHA}")
        if errors:
            print("canonical aisa skill check failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(f"{EXPORTED} matches {SOURCE_SHA}; guidance stale strings absent")
        return 0

    if source_dir is None:
        raise SystemExit("--source-dir is required to write the export")
    text = export_text(
        (source_dir / "SKILL.md").read_text(encoding="utf-8"),
        (source_dir / "LICENSE").read_text(encoding="utf-8"),
    )
    path = write_export(root, text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    print(f"wrote {path.relative_to(root)} from {SOURCE_SHA} sha256={digest}")
    if errors:
        print("guidance still has stale strings:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
