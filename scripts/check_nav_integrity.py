#!/usr/bin/env python3
"""Validate docs.json navigation and redirects against the MDX tree.

Checks:
1. Every page listed in navigation has an MDX file.
2. Every MDX page outside snippets/ and api-reference/ is reachable: it is in
   navigation, is a redirect source, or is listed in UNLISTED_PAGES.
3. Every internal redirect destination resolves to a page (or a page anchor),
   and no redirect points at another redirect source (no chains or loops).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Pages that are intentionally published without a sidebar entry. Each entry
# needs a reason, because anything here is invisible in navigation.
UNLISTED_PAGES: dict[str, str] = {
    # Read as Markdown by the QuickInstall prompts in the home and console apps.
    "agents/aisa-cio/INSTALL-hermes": "linked from home/console QuickInstall",
    "agents/aisa-cio/INSTALL-openclaw": "linked from home/console QuickInstall",
}

EXCLUDED_PREFIX_RE = re.compile(r"^(zh/)?(snippets|api-reference)/")
WILDCARD_RE = re.compile(r"[:*()]")


def nav_pages(node: object) -> list[str]:
    """Collect every page path listed under a "pages" array in navigation."""
    pages: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "pages" and isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        pages.append(item)
                    else:
                        pages.extend(nav_pages(item))
            elif isinstance(value, (dict, list)):
                pages.extend(nav_pages(value))
    elif isinstance(node, list):
        for item in node:
            pages.extend(nav_pages(item))
    return pages


def normalize(path: str) -> str:
    return path.split("#", 1)[0].split("?", 1)[0].strip("/")


def page_exists(root: Path, page: str) -> bool:
    page = normalize(page)
    if not page:
        return (root / "index.mdx").exists() or (root / "index.md").exists()
    return any((root / f"{page}{suffix}").exists() for suffix in (".mdx", ".md")) or (
        root / page / "index.mdx"
    ).exists()


def validate(root: Path) -> list[str]:
    config = json.loads((root / "docs.json").read_text(encoding="utf-8"))
    errors: list[str] = []

    listed = nav_pages(config.get("navigation", {}))
    listed_set = {normalize(page) for page in listed}
    for page in sorted(set(listed)):
        if not page_exists(root, page):
            errors.append(f"navigation page has no file: {page}")

    redirects = config.get("redirects", [])
    sources = {normalize(r["source"]) for r in redirects}

    for mdx in sorted(root.rglob("*.mdx")):
        rel = mdx.relative_to(root).as_posix()
        if rel.startswith((".", "node_modules/")) or EXCLUDED_PREFIX_RE.match(rel):
            continue
        page = rel[: -len(".mdx")]
        if page in listed_set or page in sources or page in UNLISTED_PAGES:
            continue
        errors.append(f"page is not in navigation or a redirect source: {rel}")

    for page in sorted(UNLISTED_PAGES):
        if not page_exists(root, page):
            errors.append(f"UNLISTED_PAGES entry has no file: {page}")
        elif page in listed_set:
            errors.append(f"UNLISTED_PAGES entry is already in navigation: {page}")

    for redirect in redirects:
        source, destination = redirect["source"], redirect["destination"]
        if destination.startswith(("http://", "https://")) or WILDCARD_RE.search(destination):
            continue
        target = normalize(destination)
        if target in sources:
            errors.append(f"redirect chain: {source} -> {destination} is itself redirected")
        elif not page_exists(root, target):
            errors.append(f"redirect destination has no page: {source} -> {destination}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        print("Navigation integrity check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Navigation, pages, and redirects are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
