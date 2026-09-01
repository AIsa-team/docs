#!/usr/bin/env python3
"""Validate the generated SimilarWeb documentation in a minimal Mintlify site.

The full repository currently contains unrelated historical MDX parse warnings.
This script copies only the generated pricing guides, all SimilarWeb endpoint
pages, and their OpenAPI source into a temporary Mintlify project, then runs the
same strict ``mint validate`` command used in CI. It validates the surfaces this
pricing contract owns without mutating or suppressing diagnostics in the source
repository.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATHS = (
    ROOT / "guides" / "pricing" / "similarweb.mdx",
    ROOT / "zh" / "guides" / "pricing" / "similarweb.mdx",
)
API_REFERENCE_DIR = ROOT / "api-reference" / "similarweb"
OPENAPI_PATH = ROOT / "openapi" / "similarweb.json"


def copy_into_fixture(source: Path, fixture_root: Path) -> None:
    target = fixture_root / source.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def build_fixture(fixture_root: Path) -> int:
    endpoint_pages = sorted(API_REFERENCE_DIR.glob("*.mdx"))
    if not endpoint_pages:
        raise SystemExit("Mintlify fixture has no SimilarWeb endpoint pages")

    for path in (*GUIDE_PATHS, *endpoint_pages, OPENAPI_PATH):
        if not path.exists():
            raise SystemExit(f"Mintlify fixture input is missing: {path.relative_to(ROOT)}")
        copy_into_fixture(path, fixture_root)

    pages = [
        "guides/pricing/similarweb",
        "zh/guides/pricing/similarweb",
        *(path.relative_to(ROOT).with_suffix("").as_posix() for path in endpoint_pages),
    ]
    config = {
        "name": "SimilarWeb pricing validation",
        "theme": "mint",
        "colors": {"primary": "#F76B15"},
        "navigation": {
            "groups": [
                {
                    "group": "SimilarWeb pricing",
                    "pages": pages,
                }
            ]
        },
    }
    (fixture_root / "docs.json").write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(endpoint_pages)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="validate the fixture inputs and configuration without running Mintlify",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="aisa-similarweb-mintlify-") as directory:
        fixture_root = Path(directory)
        endpoint_count = build_fixture(fixture_root)
        if args.prepare_only:
            print(f"Mintlify fixture prepared: {endpoint_count} SimilarWeb endpoint pages")
            return
        subprocess.run(
            ["npx", "--yes", "mint@4.2.854", "validate"],
            cwd=fixture_root,
            check=True,
        )
        print(f"Mintlify validated SimilarWeb fixture: {endpoint_count} endpoint pages")


if __name__ == "__main__":
    main()
