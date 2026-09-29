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

from compose_openapi import METHODS, compose, digest, resolve_fragment
from import_upstream import import_source
from runtime_registry import discover, combine_facts, public_mirror_index, published_documents, previous_for_facts, coverage_rows

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


def retain_unregistered_history(document: dict, facts: dict, history: dict) -> list:
    """Keep old links visible without presenting unregistered routes as active.

    This only handles paths absent from the complete runtime provider document.
    A failed composition or changed ID on a present path must still fail review.
    """
    prefix = normalize_paths(facts)
    retained = []
    for path, method, old in operations(history):
        if path in prefix.get("paths", {}):
            continue
        operation = resolve_fragment(old, history, document, "retained_history.json")
        # Page links are added and hashed by generate_pages after composition.
        # Feeding the previous run's derived link back here creates hash churn.
        operation.pop("x-aisa-docs-url", None)
        operation["x-aisa-status"] = "disabled"
        operation["x-aisa-contract-state"] = "retained_legacy"
        operation["x-aisa-contract-pending"] = "not_in_runtime_contract"
        document["paths"].setdefault(path, {})[method] = operation
        retained.append({"path": path, "method": method.upper(), "operation_id": operation["operationId"], "reason": "not_in_runtime_contract"})
    if retained:
        metadata = document["info"]["x-aisa-document"]
        metadata["document_hash"] = digest({"composed": metadata["document_hash"], "retained": {row["operation_id"]: document["paths"][row["path"]][row["method"].lower()] for row in retained}})
    return retained


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


def generate_pages(root: Path, provider: str, document: dict, changes: dict, previous: dict | None = None, decorate_links: bool = True) -> None:
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
        match = re.search(r"^openapi:\s*['\"]?(openapi/[^\s'\"]+\.json)\s+(\w+)\s+([^\s'\"]+)", text, re.M)
        if match:
            old_spec = read_json(root / match[1], {})
            old_prefix = urlsplit((old_spec.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
            if match[1] == f"openapi/{provider}.json":
                old_prefix = previous_prefix
            known[(old_prefix + match[3], match[2].lower())] = mdx.relative_to(root).with_suffix("").as_posix()
    current_prefix = urlsplit((document.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    paths = []
    for path, method, operation in operations(document):
        page = known.get((current_prefix + path, method), f"api-reference/{provider}/{slug(operation['operationId'])}")
        paths.append(page)
        if decorate_links:
            operation["x-aisa-docs-url"] = "https://aisa.one/docs/" + page
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
    if decorate_links:
        meta = document["info"]["x-aisa-document"]
        meta["document_hash"] = digest({"composer_hash": meta["document_hash"], "page_links": {op["operationId"]: op.get("x-aisa-docs-url") for _, _, op in operations(document)}})
    # Use the existing deterministic translation catalog. Untranslated strings
    # retain English; no paid/model translation is invoked by scheduled pulls.
    localized = localization.localize_tree(document, catalog, allow_untranslated=True)
    changes[root / f"openapi/zh/{provider}.json"] = json.dumps(localized, indent=2, ensure_ascii=False) + "\n"


def stage(root: Path, facts_dir: Path | None, base_url: str, with_pages: bool = True) -> tuple[dict, dict]:
    registry_path = root / "openapi/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text())
    if not isinstance(registry.get("providers"), dict):
        raise ValueError("registry providers must be a mapping")
    changes = {}
    if registry.get("auto_register"):
        category = read_json(facts_dir / "category.json") if facts_dir else fetch_json(f"{base_url.rstrip('/')}/info/apis/category")
        discover(registry, category)
        # The public marketing catalog intentionally omits asynchronous and
        # disabled integrations. Contract discovery also follows the actual
        # runtime index, including providers whose projection is pending.
        try:
            index = read_json(facts_dir / "index.json", {}) if facts_dir else fetch_json(f"{base_url.rstrip('/')}/info/openapi.json")
        except HTTPError as exc:
            if exc.code != 404:
                raise
            index = {}  # Compatibility before runtime contract deployment.
        indexed = (index or {}).get("providers", []) + (index or {}).get("pending_providers", [])
        discover(registry, {"apis": [{"id": key} for key in sorted({row["id"] for row in indexed})]})
    else:
        # Group overlap and invalid catalog names are still rejected when
        # discovery is disabled for an offline or pinned rollout.
        discover(registry, {"apis": []})
    original_documents = published_documents(root)
    public_mirrors = public_mirror_index(root)
    coverage = {"providers": {}, "legacy_operations": []}
    moved = set()
    ready = {}
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
            catalogs = entry.get("group", [provider])
            collected = {}
            unavailable = []
            for catalog in catalogs:
                facts_path = root / f".cache/runtime-contracts/{catalog}.json"
                cached = read_json(facts_path)
                etag = cached.get("info", {}).get("x-aisa-document", {}).get("facts_hash") if cached else None
                failure = None
                try:
                    facts = read_json(facts_dir / f"{catalog}.json") if facts_dir else fetch_json(f"{base_url.rstrip('/')}/info/openapi/{catalog}.json", f'"{etag}"' if etag else None)
                    if facts is None:
                        facts = cached
                    if not facts or not facts.get("info", {}).get("x-aisa-document", {}).get("facts_hash"):
                        failure = "runtime_contract_unavailable"
                except (HTTPError, URLError, TimeoutError) as exc:
                    if not registry.get("auto_register"):
                        raise
                    failure = f"runtime_contract_unavailable: {type(exc).__name__}"
                if failure:
                    if not registry.get("auto_register"):
                        raise ValueError(f"{catalog}: runtime facts unavailable; no files written")
                    try:
                        detail = read_json(facts_dir / "inventory" / f"{catalog}.json", {}) if facts_dir else fetch_json(f"{base_url.rstrip('/')}/info/apis/{catalog}")
                    except (HTTPError, URLError, TimeoutError):
                        detail = {}
                    endpoints = [endpoint for group in (detail or {}).get("api", {}).get("endpoint_groups", []) for endpoint in group.get("endpoints", [])]
                    for endpoint in endpoints or [{"path": None, "method": None}]:
                        unavailable.append({"catalog": catalog, "path": endpoint.get("path"), "method": endpoint.get("method"), "operation_id": endpoint.get("operation_id"), "status": "pending", "reason": failure, "validation": None, "schema_source": None})
                    continue
                collected[catalog] = facts
                changes[facts_path] = json.dumps(facts, indent=2, ensure_ascii=False) + "\n"
            if unavailable:
                for catalog, available in collected.items():
                    for path, item in available.get("paths", {}).items():
                        for method, op in item.items():
                            if method in METHODS or method == "x-aisa-any":
                                unavailable.append({"catalog": catalog, "path": path, "method": method.upper(), "operation_id": op.get("operationId"), "status": "pending", "reason": "group_member_unavailable", "validation": op.get("x-aisa-validation"), "schema_source": None})
                coverage["providers"][provider] = unavailable
                pending["providers"][provider] = unavailable
                summary[provider] = {"changed": False, "operations": sum(1 for _ in operations(previous)), "pending": len(unavailable), "blocked": "runtime_contract_unavailable"}
                continue
            facts = combine_facts(collected, provider)
            entry["display_name"] = facts.get("info", {}).get("title", provider)
            entry["description"] = facts.get("info", {}).get("description", "")
            registry["providers"][provider] = entry
            upstream = None
            overlay_path = root / f"openapi/overlays/{provider}.yaml"
            overlay = yaml.safe_load(overlay_path.read_text()) if overlay_path.exists() else {}
            unresolved = []
            try:
                configured = entry.get("upstream")
                configurations = configured if isinstance(configured, list) else [configured]
                upstream_documents = []
                for configuration in configurations:
                    source_url = configuration.get("url") if isinstance(configuration, dict) else configuration
                    if configuration and (not isinstance(source_url, str) or not source_url.startswith("https://")):
                        raise ValueError("upstream requires an HTTPS source URL")
                    upstream_file = configuration.get("file", provider + ".json") if isinstance(configuration, dict) else provider + ".json"
                    if not isinstance(upstream_file, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*\.json", upstream_file):
                        raise ValueError("upstream file must name a JSON mirror within openapi/upstream")
                    upstream_path = root / "openapi/upstream" / upstream_file
                    document = read_json(upstream_path)
                    current_source = (document or {}).get("info", {}).get("x-aisa-source", {})
                    if source_url and (current_source.get("kind") != "provider_openapi" or current_source.get("url") != source_url):
                        document = import_source(provider, source_url)
                        changes[upstream_path] = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
                    if document and document.get("info", {}).get("x-aisa-source", {}).get("path_space") != "public":
                        upstream_documents.append(document)
                upstream = upstream_documents if isinstance(configured, list) else (upstream_documents[0] if upstream_documents else None)
                history = previous_for_facts(facts, original_documents, provider)
                document, unresolved = compose(facts, upstream, overlay, history, public_mirrors)
                coverage["providers"][provider] = coverage_rows(facts, document, unresolved, catalogs)
                active_history = copy.deepcopy(history)
                runtime_paths = normalize_paths(facts)["paths"]
                active_history["paths"] = {p: item for p, item in history["paths"].items() if p in runtime_paths}
                assert_identities(active_history, normalize_paths(document))
            except (ValueError, HTTPError, URLError, TimeoutError) as exc:
                if not registry.get("auto_register"):
                    raise
                # Keep published pages/specs intact while reporting the exact
                # blocked cutover; another catalog can still make progress.
                coverage["providers"].setdefault(provider, coverage_rows(facts, {"paths": {}}, [], catalogs))
                for row in coverage["providers"][provider]:
                    row["status"] = "pending"
                    row["reason"] = str(exc) if row["reason"] in (None, "operation_not_composed") else row["reason"]
                pending["providers"][provider] = unresolved + [{"reason": str(exc)}]
                summary[provider] = {"changed": False, "operations": sum(1 for _ in operations(previous)), "pending": len(coverage["providers"][provider]), "blocked": str(exc)}
                continue
            for path, method, op in operations(normalize_paths(document)):
                moved.add((path, method, op["operationId"], provider))
            ready[provider] = (document, facts, history, previous, unresolved)
            continue
        if with_pages:
            generate_pages(root, provider, document, changes, previous, decorate_links=not entry.get("pin"))
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
                if with_pages:
                    generate_pages(root, provider, document, changes, previous, decorate_links=False)
        pending["providers"][provider] = unresolved
        summary[provider] = {"changed": changed, "operations": sum(1 for _ in operations(document)), "pending": len(unresolved), "document_hash": new_hash}
    # Resolve ownership across all successfully composed providers before
    # retaining history. A provider can lose one lifecycle while keeping its
    # other active routes; its disabled historical copy must not duplicate the
    # new canonical owner's immutable operation ID.
    for provider, (document, facts, history, previous, unresolved) in ready.items():
        history = copy.deepcopy(history)
        for path, method, op in list(operations(history)):
            targets = {dest for p, m, oid, dest in moved if (p, m, oid) == (path, method, op.get("operationId"))}
            if targets and provider not in targets:
                del history["paths"][path][method]
                if not (set(history["paths"][path]) & METHODS):
                    del history["paths"][path]
        unresolved.extend(retain_unregistered_history(document, facts, history))
        assert_identities(history, normalize_paths(document))
        if with_pages:
            generate_pages(root, provider, document, changes, previous)
        old_hash = previous.get("info", {}).get("x-aisa-document", {}).get("document_hash")
        new_hash = document.get("info", {}).get("x-aisa-document", {}).get("document_hash")
        if not new_hash:
            raise ValueError(f"{provider}: generated document has no document_hash")
        changed = old_hash != new_hash
        if changed:
            changes[root / f"openapi/{provider}.json"] = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        elif with_pages:
            generate_pages(root, provider, previous, changes, previous, decorate_links=False)
        pending["providers"][provider] = unresolved
        summary[provider] = {"changed": changed, "operations": sum(1 for _ in operations(document)), "pending": len(unresolved), "document_hash": new_hash}
    # Retire only operations successfully moved to another output. Keeping
    # unmatched legacy operations avoids deleting docs outside runtime scope.
    from urllib.parse import urlsplit
    for name, original in original_documents.items():
        output_path = root / f"openapi/{name}.json"
        staged = json.loads(changes[output_path]) if output_path in changes else original
        retained = copy.deepcopy(staged)
        prefix = urlsplit((original.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
        for path, method, op in list(operations(original)):
            targets = [dest for p, m, oid, dest in moved if (p, m, oid) == (prefix + path, method, op.get("operationId"))]
            if targets and name not in targets:
                for destination in targets:
                    entry = registry["providers"][destination] or {}
                    entry["legacy_sources"] = sorted(set(entry.get("legacy_sources", [])) | {name})
                    registry["providers"][destination] = entry
                retained_prefix = urlsplit((retained.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
                retained_path = (prefix + path).removeprefix(retained_prefix)
                if method in retained.get("paths", {}).get(retained_path, {}):
                    del retained["paths"][retained_path][method]
                    if not (set(retained["paths"][retained_path]) & METHODS):
                        del retained["paths"][retained_path]
            elif not targets:
                coverage["legacy_operations"].append({"source": f"openapi/{name}.json", "path": prefix + path, "method": method.upper(), "operation_id": op.get("operationId"), "status": "retained_legacy", "reason": "not_in_composed_runtime_contract"})
        if retained != staged:
            changes[output_path] = json.dumps(retained, indent=2, ensure_ascii=False) + "\n"
    if registry.get("auto_register"):
        changes[registry_path] = yaml.safe_dump(registry, sort_keys=False, allow_unicode=True)
        changes[root / "openapi/coverage.json"] = json.dumps(coverage, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
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
