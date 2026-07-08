#!/usr/bin/env python3
"""Validate API reference endpoint page filenames.

Canonical endpoint page slug:
    api-reference/{category}/{method}_{api-path-slug}.mdx

`api-path-slug` is derived from the OpenAPI path by removing braces from
path params, normalizing underscores/colon separators to hyphens, and replacing
slashes with hyphens.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

METHODS = {"get", "post", "put", "patch", "delete"}
ALLOWLIST = {
    # Two manual pages document POST /chat/completions. The main OpenAI Chat
    # page owns the canonical slug; this page documents image generation routed
    # through the chat-completions surface.
    "api-reference/chat/post_chat-completions-image-generation.mdx": "post_chat-completions",
}

OPENAPI_RE = re.compile(r"^openapi:\s*[\"']([^\"']+)[\"']", re.MULTILINE)


def slugify_path(path: str) -> str:
    slug = path.strip("/").replace("{", "").replace("}", "")
    slug = slug.replace("_", "-").replace(":", "-")
    slug = re.sub(r"[^A-Za-z0-9/.-]+", "-", slug)
    slug = slug.replace("/", "-")
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug


def extract_openapi_ref(text: str) -> tuple[str, str] | None:
    match = OPENAPI_RE.search(text)
    if not match:
        return None
    parts = match.group(1).split()
    if len(parts) < 3:
        return None
    method, path = parts[-2].lower(), parts[-1]
    if method not in METHODS:
        return None
    return method, path


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    canonical_to_files: dict[str, list[str]] = {}
    for mdx in sorted((root / "api-reference").rglob("*.mdx")):
        ref = extract_openapi_ref(mdx.read_text(encoding="utf-8"))
        if ref is None:
            continue
        method, path = ref
        expected_stem = f"{method}_{slugify_path(path)}"
        rel = mdx.relative_to(root).as_posix()
        expected_rel = mdx.with_name(expected_stem + ".mdx").relative_to(root).as_posix()
        canonical_key = mdx.with_name(expected_stem + ".mdx").relative_to(root).with_suffix("").as_posix()
        canonical_to_files.setdefault(canonical_key, []).append(rel)
        if rel != expected_rel and ALLOWLIST.get(rel) != expected_stem:
            errors.append(f"{rel}: expected {expected_rel} from {method.upper()} {path}")
    for canonical, files in canonical_to_files.items():
        if len(files) <= 1:
            continue
        bad = [f for f in files if f not in ALLOWLIST and f != canonical + ".mdx"]
        if bad:
            errors.append(f"duplicate canonical slug {canonical}: {files}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        print("API reference slug validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("API reference slugs are canonical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
