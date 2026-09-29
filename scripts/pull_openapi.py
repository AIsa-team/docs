#!/usr/bin/env python3
"""Stage runtime contracts without writing by default; --write publishes locally.

Every provider is fetched and composed before writes. A unavailable runtime fails
without touching checked-in specs. --facts-dir supports deterministic offline QA.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

from compose_openapi import METHODS, compose

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def operations(spec):
    for path, item in spec.get("paths", {}).items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation


def assert_identities(previous: dict, current: dict) -> None:
    old = {(p, m): op["operationId"] for p, m, op in operations(previous)}
    new = {(p, m): op["operationId"] for p, m, op in operations(current)}
    for route, operation_id in old.items():
        if new.get(route) != operation_id:
            raise ValueError(f"published identity changed or disappeared: {operation_id} ({route})")


def fetch_json(url: str, etag: str | None = None):
    headers = {"Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 304:
            return None
        raise


def slug(value):
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)


def generate_pages(root: Path, provider: str, document: dict, changes: dict, previous: dict | None = None) -> None:
    """Append pages/navigation, reusing existing method/path references and prose."""
    docs_path = root / "docs.json"
    if not docs_path.exists():
        return
    docs = json.loads(changes.get(docs_path, docs_path.read_text()))
    import localize_openapi_zh as localization
    catalog = read_json(root / "translations/openapi-zh.json", {"entries": {}})
    known = {}
    from urllib.parse import urlsplit
    previous_prefix = urlsplit(((previous or {}).get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    for mdx in (root / "api-reference").rglob("*.mdx"):
        text = mdx.read_text()
        match = re.search(r"^openapi:\s*['\"]?openapi/" + re.escape(provider) + r"\.json\s+(\w+)\s+([^\s'\"]+)", text, re.M)
        if match:
            known[(previous_prefix + match[2], match[1].lower())] = mdx.relative_to(root).with_suffix("").as_posix()
    current_prefix = urlsplit((document.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    paths = []
    for path, method, operation in operations(document):
        page = known.get((current_prefix + path, method), f"api-reference/{provider}/{slug(operation['operationId'])}")
        paths.append(page)
        for language, prefix in (("en", ""), ("zh", "zh/")):
            destination = root / f"{prefix}{page}.mdx"
            spec_path = f"openapi/{'zh/' if language == 'zh' else ''}{provider}.json"
            source_title = operation.get("summary") or operation["operationId"]
            localized_title = source_title
            if language == "zh":
                try:
                    localized_title = localization.translation(catalog, source_title)
                except KeyError:
                    pass  # Current English title is safer than a stale translation.
            title = json.dumps(localized_title, ensure_ascii=False)
            reference = json.dumps(f"{spec_path} {method.upper()} {path}")
            identity = f"x-aisa-operation-id: {json.dumps(operation['operationId'])}"
            if destination.exists():
                text = destination.read_text()
                frontmatter, prose = localization.split_frontmatter(text)
                frontmatter = localization.replace_frontmatter_value(frontmatter, "title", localized_title)
                text = "---\n" + frontmatter + "\n---\n" + prose
                text = re.sub(r"^openapi:.*$", lambda _: f"openapi: {reference}", text, count=1, flags=re.M)
                if "x-aisa-operation-id:" not in text:
                    text = text.replace("---\n", "---\n" + identity + "\n", 1)
            else:
                text = f"---\ntitle: {title}\nopenapi: {reference}\n{identity}\n---\n"
            # A small managed notice can change with status while all user prose
            # remains intact, including on pre-existing pages.
            begin, end = "{/* aisa-contract-status:start */}", "{/* aisa-contract-status:end */}"
            text = re.sub(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", "", text, flags=re.S)
            if operation.get("x-aisa-status") == "disabled":
                notice = "当前未启用。" if language == "zh" else "Currently disabled."
                text += f"{begin}\n{notice}\n{end}\n"
            if not destination.exists() or text != destination.read_text():
                changes[destination] = text
    for language in docs.get("navigation", {}).get("languages", []):
        prefix = "zh/" if language.get("language") == "zh" else ""
        for tab in language.get("tabs", []):
            if tab.get("tab") not in {"API Reference", "API 参考"}:
                continue
            existing = set()
            def collect(node):
                if isinstance(node, list):
                    for item in node:
                        collect(item)
                elif isinstance(node, dict):
                    for value in node.values():
                        collect(value)
                elif isinstance(node, str):
                    existing.add(node)
            collect(tab)
            additions = [prefix + p for p in paths if prefix + p not in existing]
            if additions:
                group_name = document["info"].get("title", provider)
                groups = tab.setdefault("groups", [])
                group = next((g for g in groups if g.get("group") == group_name), None)
                if group is None:
                    group = {"group": group_name, "pages": []}
                    groups.append(group)
                group["pages"].extend(additions)
    content = json.dumps(docs, indent=2, ensure_ascii=False) + "\n"
    if content != docs_path.read_text():
        changes[docs_path] = content
    # Use the existing deterministic translation catalog. Untranslated strings
    # retain English; no paid/model translation is invoked by scheduled pulls.
    localized = localization.localize_tree(document, catalog, allow_untranslated=True)
    changes[root / f"openapi/zh/{provider}.json"] = json.dumps(localized, indent=2, ensure_ascii=False) + "\n"


def stage(root: Path, facts_dir: Path | None, base_url: str, with_pages: bool = True) -> tuple[dict, dict]:
    registry_path = root / "openapi/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text())
    if not isinstance(registry.get("providers"), dict):
        raise ValueError("registry providers must be a mapping")
    if registry.get("auto_register"):
        raise ValueError("auto_register remains disabled until staged rollout validation completes")
    changes = {}
    pending = copy.deepcopy(read_json(root / "openapi/pending.json", {"providers": {}}))
    pending.setdefault("providers", {})
    summary = {}
    for provider, entry in sorted(registry["providers"].items()):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", provider):
            raise ValueError(f"invalid provider key: {provider}")
        entry = entry or {}
        output_path = root / f"openapi/{provider}.json"
        previous = read_json(output_path, {})
        if entry.get("pin"):
            pin = str(entry["pin"])
            if not re.fullmatch(r"[a-fA-F0-9]{7,40}", pin):
                raise ValueError("pin must be a git commit SHA")
            result = subprocess.run(["git", "show", f"{pin}:openapi/{provider}.json"], cwd=root, check=True, text=True, capture_output=True)
            document = json.loads(result.stdout)
            if previous:
                assert_identities(normalize_paths(previous), normalize_paths(document))
            unresolved = pending["providers"].get(provider, [])
        else:
            if entry.get("group"):
                raise ValueError("group composition is not enabled in the initial rollout")
            facts_path = root / f".cache/runtime-contracts/{provider}.json"
            cached = read_json(facts_path)
            etag = cached.get("info", {}).get("x-aisa-document", {}).get("facts_hash") if cached else None
            facts = read_json(facts_dir / f"{provider}.json") if facts_dir else fetch_json(f"{base_url.rstrip('/')}/info/openapi/{provider}.json", f'"{etag}"' if etag else None)
            if facts is None:
                facts = cached
            if not facts:
                raise ValueError(f"{provider}: runtime facts unavailable; no files written")
            upstream = read_json(root / f"openapi/upstream/{provider}.json")
            overlay_path = root / f"openapi/overlays/{provider}.yaml"
            overlay = yaml.safe_load(overlay_path.read_text()) if overlay_path.exists() else {}
            document, unresolved = compose(facts, upstream, overlay, previous)
            # The initial hand-written -> generated cutover must retain IDs too.
            # Relative legacy paths are compared as absolute effective routes.
            if previous:
                assert_identities(normalize_paths(previous), normalize_paths(document))
            changes[facts_path] = json.dumps(facts, indent=2, ensure_ascii=False) + "\n"
        old_hash = previous.get("info", {}).get("x-aisa-document", {}).get("document_hash")
        new_hash = document.get("info", {}).get("x-aisa-document", {}).get("document_hash")
        if entry.get("pin"):
            # Historic handwritten documents predate runtime hashes. Restore
            # their committed bytes without inventing generated provenance.
            changed = not output_path.exists() or output_path.read_text() != result.stdout
            if changed:
                changes[output_path] = result.stdout
        else:
            if not new_hash:
                raise ValueError(f"{provider}: generated document has no document_hash")
            changed = old_hash != new_hash
            if changed:
                changes[output_path] = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
            else:
                # generated_at is observational, and cannot create commit churn.
                document = previous
        pending["providers"][provider] = unresolved
        if with_pages:
            generate_pages(root, provider, document, changes, previous)
        summary[provider] = {"changed": changed, "operations": sum(1 for _ in operations(document)), "pending": len(unresolved), "document_hash": new_hash}
    changes[root / "openapi/pending.json"] = json.dumps(pending, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return {p: content for p, content in changes.items() if not p.exists() or p.read_text() != content}, summary


def normalize_paths(document):
    from urllib.parse import urlsplit
    result = copy.deepcopy(document)
    prefix = urlsplit((document.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    result["paths"] = {prefix + path: item for path, item in document.get("paths", {}).items()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--facts-dir", type=Path)
    parser.add_argument("--base-url", default="https://api.aisa.one")
    parser.add_argument("--write", action="store_true", help="write staged files; default is dry-run")
    parser.add_argument("--skip-pages", action="store_true")
    args = parser.parse_args()
    try:
        changes, summary = stage(args.root, args.facts_dir, args.base_url, not args.skip_pages)
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"Runtime unavailable; no files written: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Contract pull aborted; no files written: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"dry_run": not args.write, "providers": summary, "files": [str(p.relative_to(args.root)) for p in sorted(changes)]}, indent=2))
    if args.write:
        for path, content in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
