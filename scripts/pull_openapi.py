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

import api_nav_groups
from compose_openapi import (METHODS, compose, digest, resolve_fragment,
                             effective_parameters, effective_security)
from import_upstream import import_source
from runtime_registry import discover, combine_facts, public_mirror_index, published_documents, previous_for_facts, coverage_rows, disabled_legacy_paths, source_configurations, legacy_coverage_row
from source_json import loads as source_json_loads, load as source_json_load, UnsupportedNumericPrecision
from readable_contract_notes import update_readable_block
from identity_compatibility import published_history, attach_history, localize_identities, validate_document_identities

from contract_page_links import slug, select_pages, project_links

ROOT = Path(__file__).resolve().parents[1]
_AUTO_HISTORY = object()


def read_json(path: Path, default=None):
    return source_json_loads(path.read_text()) if path.exists() else default


def operations(spec):
    for path, item in spec.get("paths", {}).items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation


def assert_identities(previous: dict, current: dict, pending: set = frozenset()) -> None:
    old = {(p, m): op["operationId"] for p, m, op in operations(previous)}
    new = {(p, m): op["operationId"] for p, m, op in operations(current)}
    current_ids = set(new.values())
    for route, operation_id in old.items():
        # Runtime owns the current path/method. An immutable ID may move, and
        # generate_pages rebinds its existing page URLs to the current route.
        if route not in new and operation_id in current_ids:
            continue
        # An exactly approved deferred route is reported as its pending row with
        # the composer's real reason (retain_pending_history keeps the published
        # copy). That is not an identity change; a different ID on the route, or
        # an unapproved pending route, still is. Method 'any' covers the path.
        if route not in new and (route in pending or (route[0], "any") in pending):
            continue
        if new.get(route) != operation_id:
            raise ValueError(f"published identity changed or disappeared: {operation_id} ({route})")


def _retain_history_operation(document: dict, facts: dict, history: dict, path: str, method: str,
                              old: dict, state: str, reason: str) -> dict:
    """Copy one previously published operation into document, never as active."""
    historic = copy.deepcopy(old)
    parameters = effective_parameters(history['paths'][path], old, history)
    if parameters:
        historic['parameters'] = parameters
    historic.setdefault('security', copy.deepcopy(history.get('security', [])))
    # Resolve authentication independently of request-schema references.
    # A historic public "Bearer" alias may bind to the current platform's
    # single HTTP Bearer scheme; unrelated missing schemes stay unresolved.
    security, missing = effective_security({**historic, 'x-aisa-status': 'disabled',
        'x-aisa-contract-state': 'retained_legacy'}, history)
    if 'Bearer' in missing:
        current_security, _ = effective_security({}, facts)
        if len(current_security) == 1:
            scheme = next(iter(current_security.values()))
            if scheme.get('type') == 'http' and str(scheme.get('scheme', '')).lower() == 'bearer':
                security['Bearer'] = copy.deepcopy(scheme)
    if state != 'retained_legacy' and set(missing) - set(security):
        # Only legacy history may carry unresolved historical security debt.
        raise ValueError(f"retained pending operation has unresolved security scheme: {old.get('operationId')}")
    auth = {'components': {'securitySchemes': security}, 'security': historic['security']}
    from runtime_consolidate_openapi import merge_components
    document.setdefault('components', {})
    merge_components(document, auth, 'retained_history.json')
    historic['security'] = auth['security']
    operation = resolve_fragment(historic, history, document, "retained_history.json")
    # Page links are added and hashed by generate_pages after composition.
    # Feeding the previous run's derived link back here creates hash churn.
    operation.pop("x-aisa-docs-url", None)
    operation["x-aisa-status"] = "disabled"
    operation["x-aisa-contract-state"] = state
    operation["x-aisa-contract-pending"] = reason
    document["paths"].setdefault(path, {})[method] = operation
    return operation


def _finish_retention(document: dict, history: dict, retained: list) -> None:
    if retained:
        from source_provenance import merge_provenance, validate_document
        merge_provenance(document, history)
        validate_document(document)
        metadata = document["info"]["x-aisa-document"]
        metadata["document_hash"] = digest({"composed": metadata["document_hash"], "retained": {row["operation_id"]: document["paths"][row["path"]][row["method"].lower()] for row in retained}})


def retain_unregistered_history(document: dict, facts: dict, history: dict) -> list:
    """Keep old links visible without presenting unregistered routes as active.

    This only handles paths absent from the complete runtime provider document.
    A changed ID on a present path must still fail review; a present path whose
    composition is pending is handled by retain_pending_history.
    """
    prefix = normalize_paths(facts)
    current_ids = {op['operationId'] for _, _, op in operations(document)}
    retained = []
    for path, method, old in operations(history):
        if path in prefix.get("paths", {}):
            continue
        if old['operationId'] in current_ids:
            continue
        operation = _retain_history_operation(document, facts, history, path, method, old,
                                              "retained_legacy", "not_in_runtime_contract")
        retained.append({"path": path, "method": method.upper(), "operation_id": operation["operationId"], "reason": "not_in_runtime_contract"})
    _finish_retention(document, history, retained)
    return retained


def retain_pending_history(document: dict, facts: dict, history: dict, unresolved: list,
                           routes: set | None = None) -> list:
    """Keep a published operation whose current runtime route the composer left pending.

    The route is still in runtime facts, so this is not legacy history: the
    composer could not produce a complete contract for it in this run (for
    example, runtime does not forward a caller credential header the source
    requires). Dropping the operation would silently remove its published
    identity and page; presenting the previous definition as active would claim
    a contract runtime does not currently honor. The previous definition is
    retained as disabled, ``x-aisa-contract-state: retained_pending``, with the
    composer's exact pending reason. Coverage keeps the composer's pending row,
    so readiness classifies the debt instead of publishing it as complete.

    Only the published identity of that exact pending route is retained; a
    composed route whose identity changed still fails ``assert_identities``.
    ``routes`` limits retention to those (path, method) pairs. Returns retained
    rows for diagnostics; the pending rows already exist.
    """
    runtime_paths = normalize_paths(facts).get("paths", {})
    reasons = {}
    for row in unresolved:
        path, method, reason = row.get("path"), str(row.get("method") or "").lower(), row.get("reason")
        if isinstance(path, str) and path in runtime_paths and method and isinstance(reason, str) and reason:
            reasons.setdefault((path, method), reason)
    current_ids = {op['operationId'] for _, _, op in operations(document)}
    retained = []
    for path, method, old in operations(history):
        reason = reasons.get((path, method), reasons.get((path, "any")))
        if reason is None or old.get('operationId') in current_ids:
            continue
        if routes is not None and (path, method) not in routes:
            continue
        if method in document.get("paths", {}).get(path, {}):
            continue
        operation = _retain_history_operation(document, facts, history, path, method, old,
                                              "retained_pending", reason)
        current_ids.add(operation["operationId"])
        retained.append({"path": path, "method": method.upper(), "operation_id": operation["operationId"], "reason": reason})
    _finish_retention(document, history, retained)
    return retained


def deferred_pending_routes(provider: str, facts: dict, document: dict, history: dict, unresolved: list,
                            deferred, rows_for) -> set:
    """Pending routes whose retained published copy is an exactly approved deferral.

    Without an exact approval the provider keeps today's behavior: a published
    identity the composer could not produce blocks the provider and leaves its
    published files untouched. ``rows_for(document)`` returns the provider's
    enriched coverage rows; readiness recomputes and checks the same key.
    """
    if deferred is None:
        return set()
    trial = copy.deepcopy(document)
    retained = retain_pending_history(trial, facts, history, unresolved)
    if not retained:
        return set()
    from contract_readiness import _pending_key
    candidates = {(row["path"], row["method"].lower()) for row in retained}
    return {(row["path"], row["method"].lower()) for row in rows_for(trial)
            if row.get("status") == "pending" and (row["path"], row["method"].lower()) in candidates
            and deferred.matches(provider, "request", _pending_key(row))}


def fetch_json(url: str, etag: str | None = None):
    headers = {"Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            reject_stale_runtime_response(getattr(response, 'headers', {}))
            return source_json_load(response)
    except HTTPError as exc:
        if exc.code == 304:
            reject_stale_runtime_response(exc.headers or {})
            return None
        raise


def reject_stale_runtime_response(headers):
    # Last-good HTTP responses are useful to readers, but cannot attest that
    # current runtime bindings were checked for a new publication candidate.
    if re.search(r'(?:^|,)\s*110\s', headers.get('Warning', '')):
        raise URLError('runtime_contract_unavailable: stale runtime response')


def existing_page_references(root: Path):
    """Read each referenced spec once, preserving the existing page selection."""
    from urllib.parse import urlsplit
    prefixes, references = {}, []
    for mdx in (root / 'api-reference').rglob('*.mdx'):
        match = re.search(r"^openapi:\s*['\"]?(openapi/[^\s'\"]+\.json)\s+(\w+)\s+([^\s'\"]+)", mdx.read_text(), re.M)
        if not match:
            continue
        spec = match[1]
        if spec not in prefixes:
            document = read_json(root / spec, {})
            prefixes[spec] = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        references.append((spec, prefixes[spec], match[3], match[2].lower(), mdx.relative_to(root).with_suffix('').as_posix()))
    return references


def generate_pages(root: Path, provider: str, document: dict, changes: dict, previous: dict | None = None, decorate_links: bool = True, page_references=None, require_existing_links: bool = False) -> None:
    """Append pages/navigation, reusing existing method/path references and prose."""
    docs_path = root / "docs.json"
    if not docs_path.exists():
        return
    docs = json.loads(changes.get(docs_path, docs_path.read_text()))
    import runtime_localize_openapi_zh as localization
    catalog = read_json(root / "translations/openapi-zh.json", {"entries": {}})
    known = {}
    from urllib.parse import urlsplit
    previous_prefix = urlsplit(((previous or {}).get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
    references = existing_page_references(root) if page_references is None else page_references
    for spec, old_prefix, path, method, page in references:
        if spec == f'openapi/{provider}.json':
            old_prefix = previous_prefix
        known[(old_prefix + path, method)] = page
    # Stable published IDs preserve old URLs when a provider path is normalized
    # or moves between output documents. Never infer an ID from a filename.
    previous_ids = {(previous_prefix + path, method): op.get('operationId')
                    for path, method, op in operations(previous or {})}
    known_ids = {}
    page_documents = {}
    for spec, old_prefix, path, method, page in references:
        header, _ = localization.split_frontmatter((root / (page + '.mdx')).read_text())
        identity = (yaml.safe_load(header) or {}).get('x-aisa-operation-id')
        if not identity and spec == f'openapi/{provider}.json':
            identity = previous_ids.get((old_prefix + path, method))
        if not identity:
            # A stable endpoint can move to another provider output as well as
            # another path. Legacy pages may not yet carry the managed ID.
            if spec not in page_documents:
                page_documents[spec] = read_json(root / spec, {})
            identity = page_documents[spec].get('paths', {}).get(path, {}).get(method, {}).get('operationId')
        if identity:
            known_ids.setdefault(identity, set()).add(page)
    selected_pages = select_pages(provider, document, known_ids, known)
    if require_existing_links:
        from contract_page_links import DOCS_PREFIX
        for _, _, operation in operations(document):
            if operation.get('x-aisa-docs-url') != DOCS_PREFIX + selected_pages[operation['operationId']][-1]:
                raise ValueError('Canonical page binding differs from existing presentation selection')
    for path, method, operation in operations(document):
        page_names = selected_pages[operation['operationId']]
        for page in page_names:
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
                machine_id = operation['operationId']
                if language == 'zh' and operation.get('x-aisa-identity'):
                    machine_id = operation['x-aisa-identity']['historical_aliases'][0]['operation_id']
                identity = f"x-aisa-operation-id: {json.dumps(machine_id)}"
                if destination.exists():
                    text = destination.read_text()
                    frontmatter, prose = localization.split_frontmatter(text)
                    frontmatter = localization.replace_frontmatter_value(frontmatter, "title", localized_title)
                    text = "---\n" + frontmatter + "\n---\n" + prose
                    text = re.sub(r"^openapi:.*$", lambda _: f"openapi: {reference}", text, count=1, flags=re.M)
                    if "x-aisa-operation-id:" not in text:
                        text = text.replace("---\n", "---\n" + identity + "\n", 1)
                    else:
                        text = re.sub(r"^x-aisa-operation-id:.*$", lambda _: identity, text, count=1, flags=re.M)
                else:
                    text = f"---\ntitle: {title}\nopenapi: {reference}\n{identity}\n---\n"
                # A small managed notice can change with status while all user prose
                # remains intact, including on pre-existing pages.
                begin, end = "{/* aisa-contract-status:start */}", "{/* aisa-contract-status:end */}"
                pattern = re.escape(begin) + r".*?" + re.escape(end) + r"\n?"
                if operation.get("x-aisa-status") == "disabled":
                    notice = "当前未启用。" if language == "zh" else "Currently disabled."
                    block = f"{begin}\n{notice}\n{end}\n"
                    text = re.sub(pattern, lambda _: block, text, flags=re.S) if re.search(pattern, text, re.S) else text + block
                else:
                    text = re.sub(pattern, "", text, flags=re.S)
                def translated_note(note):
                    try:
                        return localization.translation(catalog, note)
                    except KeyError:
                        return note
                from pricing_prose import clean_page
                text = clean_page(text, language)
                text = update_readable_block(text, operation, language, translated_note,
                    document=document, method=method, path=path, spec_path=spec_path)
                if not destination.exists() or text != destination.read_text():
                    changes[destination] = text
    nav_config = api_nav_groups.load(root)
    nav_labels = read_json(root / "translations/openapi-nav-zh.json", {})
    visible_aliases = set()
    for language in docs.get("navigation", {}).get("languages", []):
        if language.get('language') not in ('en', 'zh'):
            continue
        for tab in language.get('tabs', []):
            if tab.get('tab') in {'API Reference', 'API 参考'}:
                visible_aliases.update(page.removeprefix('zh/') for page in api_nav_groups.nav_pages(tab))
    # Mirror the union of already visible historical aliases in both locales.
    # A new canonical URL stays hidden when an existing alias is visible.
    navigation_pages = {identity: [page for page in pages if page in visible_aliases] or [pages[-1]]
                        for identity, pages in selected_pages.items()}
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
            additions = [prefix + page for pages in navigation_pages.values()
                         for page in pages if prefix + page not in existing]
            if additions:
                group_name = document["info"].get("title", provider)
                groups = tab.setdefault("groups", [])
                # Mapped providers land in their category -> vendor group; only
                # unmapped titles fall back to a top-level group of their own.
                for page in additions:
                    english_page = page.removeprefix('zh/')
                    target = (api_nav_groups.page_target(nav_config, english_page) if nav_config else None)
                    target = target or api_nav_groups.target_for(nav_config, group_name)
                    if target:
                        label = (lambda name: nav_labels.get(name) or name) if prefix else (lambda name: name)
                        api_nav_groups.locate(groups, nav_config, target, label).append(page)
                        continue
                    group = next((g for g in groups if g.get("group") == group_name), None)
                    if group is None:
                        group = {"group": group_name, "pages": []}
                        groups.append(group)
                    group["pages"].append(page)
    content = json.dumps(docs, indent=2, ensure_ascii=False) + "\n"
    if content != docs_path.read_text():
        changes[docs_path] = content
    if decorate_links:
        project_links(document, selected_pages)
    # Use the existing deterministic translation catalog. Untranslated strings
    # retain English; no paid/model translation is invoked by scheduled pulls.
    localized = localization.localize_tree(document, catalog, allow_untranslated=True)
    localized = localize_identities(localized)
    changes[root / f"openapi/zh/{provider}.json"] = json.dumps(localized, indent=2, ensure_ascii=False) + "\n"


def refresh_legacy_page_blocks(root, documents, changes, catalog):
    """Update only already bound pages; never create pages or navigation."""
    import runtime_localize_openapi_zh as localization
    def translated_note(note):
        try:
            return localization.translation(catalog, note)
        except KeyError:
            return note
    for language, directory in (("en", "api-reference"), ("zh", "zh/api-reference")):
        for page in (root / directory).rglob("*.mdx"):
            text = changes.get(page, page.read_text())
            if not text.startswith("---\n"):
                continue
            header, _ = localization.split_frontmatter(text)
            reference = (yaml.safe_load(header) or {}).get("openapi", "")
            match = re.fullmatch(r"openapi/(zh/)?([A-Za-z0-9_.-]+)\.json ([A-Z]+) (\S+)", reference)
            if not match or match[2] not in documents:
                continue
            document = documents[match[2]]
            if document.get("info", {}).get("x-aisa-document", {}).get("document_hash"):
                continue  # Runtime page generation owns these pages.
            method, path = match[3].lower(), match[4]
            operation = document.get("paths", {}).get(path, {}).get(method)
            if method not in METHODS or not isinstance(operation, dict):
                raise ValueError("legacy page references missing operation: " + str(page))
            if bool(match[1]) != (language == "zh"):
                raise ValueError("legacy page references wrong language: " + str(page))
            if language == "zh":
                localized_path = root / reference.split()[0]
                if not localized_path.exists() and localized_path not in changes:
                    localized = localize_identities(localization.localize_tree(document, catalog, allow_untranslated=True))
                    changes[localized_path] = json.dumps(localized, indent=2, ensure_ascii=False) + "\n"
            changes[page] = update_readable_block(text, operation, language, translated_note,
                document=document, method=method, path=path, spec_path=reference.split()[0])


def refresh_localized_documents(root, documents, changes, catalog, identity_history=None):
    """Project existing locale aliases, preserving complete canonical declarations."""
    import runtime_localize_openapi_zh as localization
    for name, document in documents.items():
        target = root / f"openapi/zh/{name}.json"
        if target.exists() and target not in changes:
            source = copy.deepcopy(document)
            if identity_history is not None:
                attach_history(source, identity_history)
            if source != document:
                changes[root / f"openapi/{name}.json"] = json.dumps(source, indent=2, ensure_ascii=False) + "\n"
                documents[name] = source
            localized = localize_identities(localization.localize_tree(source, catalog, allow_untranslated=True))
            changes[target] = json.dumps(localized, indent=2, ensure_ascii=False) + "\n"


def stage(root: Path, facts_dir: Path | None, base_url: str, with_pages: bool = True,
          readiness_context: dict | None = None, *, identity_history=_AUTO_HISTORY,
          page_link_index=None, reuse_unchanged_documents=True) -> tuple[dict, dict]:
    registry_path = root / "openapi/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text())
    if not isinstance(registry.get("providers"), dict):
        raise ValueError("registry providers must be a mapping")
    from deferred_definitions import load_deferred_definitions
    deferred = load_deferred_definitions(root)
    response_identity_v2 = bool(deferred and deferred.response_v2_keys)
    changes = {}
    if identity_history is _AUTO_HISTORY:
        identity_history = published_history(root, (readiness_context or {}).get('published_ref'))
    if with_pages and page_link_index is not None:
        raise ValueError('Page generation and explicit native link projection are mutually exclusive')
    index = read_json(facts_dir / 'index.json', {}) if facts_dir else {}
    if registry.get("auto_register"):
        category = read_json(facts_dir / "category.json") if facts_dir else fetch_json(f"{base_url.rstrip('/')}/info/apis/category")
        changes[root / '.cache/runtime-contracts/category.json'] = json.dumps(category, indent=2, sort_keys=True) + '\n'
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
    if index:
        changes[root / '.cache/runtime-contracts/index.json'] = json.dumps(index, indent=2, sort_keys=True) + '\n'
    else:
        # Group overlap and invalid catalog names are still rejected when
        # discovery is disabled for an offline or pinned rollout.
        discover(registry, {"apis": []})
    original_documents = published_documents(root)
    page_references = existing_page_references(root) if with_pages else []
    public_source_overrides = {}
    public_mirrors = public_mirror_index(root)
    coverage = {"schema_version": 2, "providers": {}, "response_gaps": {}, "legacy_operations": []}
    moved = set()
    ready = {}
    recomposed_documents = {}
    facts_by_provider = {}
    indexed_hashes = {row['id']: row.get('facts_hash') for row in index.get('providers', [])}
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
            document = source_json_loads(result.stdout)
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
                    elif indexed_hashes.get(catalog) and facts['info']['x-aisa-document']['facts_hash'] != indexed_hashes[catalog]:
                        failure = 'runtime_contract_unavailable: facts_hash_mismatch'
                except (HTTPError, URLError, TimeoutError, UnsupportedNumericPrecision) as exc:
                    if not registry.get("auto_register"):
                        raise
                    failure = str(exc) if isinstance(exc, UnsupportedNumericPrecision) else f"runtime_contract_unavailable: {type(exc).__name__}"
                if failure:
                    if not registry.get("auto_register"):
                        raise ValueError(f"{catalog}: runtime facts unavailable; no files written")
                    try:
                        detail = read_json(facts_dir / "inventory" / f"{catalog}.json", {}) if facts_dir else fetch_json(f"{base_url.rstrip('/')}/info/apis/{catalog}")
                    except (HTTPError, URLError, TimeoutError):
                        detail = {}
                    indexed_endpoints = index.get('pending_endpoints', []) + index.get('coverage', {}).get('projected_endpoints', [])
                    endpoints = [row for row in indexed_endpoints if row.get('provider') == catalog]
                    if not endpoints:
                        endpoints = [endpoint for group in (detail or {}).get("api", {}).get("endpoint_groups", []) for endpoint in group.get("endpoints", [])]
                    for endpoint in endpoints:
                        unavailable.append({"catalog": catalog, "path": endpoint.get("path"), "method": endpoint.get("method") or 'ANY', "operation_id": endpoint.get("operation_id"), "status": "pending", "reason": failure, "validation": None, "schema_source": None})
                    if not endpoints:
                        # Unknown inventory is an input gap, not a fictitious
                        # operation with a missing path. The checker records it.
                        unavailable.append({'catalog': catalog, 'status': 'pending',
                                            'reason': failure, 'inventory_unavailable': True,
                                            'publication_state': 'retained'})
                    continue
                collected[catalog] = facts
                changes[facts_path] = json.dumps(facts, indent=2, ensure_ascii=False) + "\n"
            if unavailable:
                for catalog, available in collected.items():
                    for path, item in available.get("paths", {}).items():
                        for method, op in item.items():
                            if method in METHODS or method == "x-aisa-any":
                                unavailable.append({"catalog": catalog, "path": path, "method": method.upper(), "operation_id": op.get("operationId"), "status": "pending", "reason": "group_member_unavailable", "validation": op.get("x-aisa-validation"), "schema_source": None})
                for row in unavailable:
                    row['publication_state'] = 'retained'
                coverage["providers"][provider] = [row for row in unavailable if not row.get('inventory_unavailable')]
                pending["providers"][provider] = unavailable
                summary[provider] = {"changed": False, "operations": sum(1 for _ in operations(previous)), "pending": len(unavailable), "blocked": "runtime_contract_unavailable"}
                continue
            facts = combine_facts(collected, provider)
            facts_by_provider[provider] = facts
            entry["display_name"] = facts.get("info", {}).get("title", provider)
            entry["description"] = facts.get("info", {}).get("description", "")
            registry["providers"][provider] = entry
            upstream = None
            overlay_path = root / f"openapi/overlays/{provider}.yaml"
            overlay = yaml.safe_load(overlay_path.read_text()) if overlay_path.exists() else {}
            unresolved = []
            try:
                configured = entry.get("upstream")
                configurations, source_bindings = source_configurations(provider, entry)
                upstream_documents = []
                for source_url, upstream_file in configurations:
                    upstream_path = root / "openapi/upstream" / upstream_file
                    document = read_json(upstream_path)
                    imported_source = False
                    current_source = (document or {}).get("info", {}).get("x-aisa-source", {})
                    trusted_kind = current_source.get("kind") in {"provider_openapi", "manual"}
                    if source_url and (not trusted_kind or current_source.get("url") != source_url):
                        if readiness_context and readiness_context.get('offline'):
                            raise ValueError('upstream source mirror unavailable for offline candidate evaluation')
                        document = import_source(provider, source_url)
                        imported_source = True
                        changes[upstream_path] = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
                        # This is an actual acquisition, unlike reading a saved
                        # mirror. Preserve its receipt outside published schemas
                        # so a new automatic source can pass its first review.
                        from datetime import datetime, timezone
                        from source_governance import acquisition_receipt, policy_errors, receipt_key
                        acquired = document.get('info', {}).get('x-aisa-source', {})
                        if acquired.get('refresh_policy') == 'automatic' and not policy_errors(acquired):
                            receipt_path = root / '.cache/source-reviews.json'
                            saved = json.loads(changes[receipt_path]) if receipt_path in changes else read_json(receipt_path, {})
                            now = datetime.now(timezone.utc)
                            key = receipt_key(acquired)
                            saved.setdefault('receipts', {})[key] = acquisition_receipt(acquired, now)
                            saved.setdefault('attempts', {})[key] = {'checked_at': now.isoformat(), 'status': 'confirmed'}
                            saved['schema_version'] = 1
                            changes[receipt_path] = json.dumps(saved, indent=2, sort_keys=True) + '\n'
                    if document:
                        if document.get("info", {}).get("x-aisa-source", {}).get("path_space") == "public":
                            if imported_source:
                                public_source_overrides[upstream_file] = document
                                public_mirrors = public_mirror_index(root, public_source_overrides)
                        else:
                            upstream_documents.append(document)
                upstream = upstream_documents if isinstance(configured, list) else (upstream_documents[0] if upstream_documents else None)
                history = previous_for_facts(facts, original_documents, provider)
                document, unresolved = compose(facts, upstream, overlay, history, public_mirrors, source_bindings)
                from gap_evidence import enrich_coverage
                def rows_for(candidate):
                    return enrich_coverage(coverage_rows(facts, candidate, unresolved, catalogs), facts, upstream,
                                           public_mirrors, source_bindings, response_identity_v2=response_identity_v2)
                deferred_routes = deferred_pending_routes(provider, facts, document, history, unresolved, deferred, rows_for)
                if deferred_routes:
                    retain_pending_history(document, facts, history, unresolved, deferred_routes)
                coverage["providers"][provider] = rows_for(document)
                active_history = copy.deepcopy(history)
                runtime_paths = normalize_paths(facts)["paths"]
                active_history["paths"] = {p: item for p, item in history["paths"].items() if p in runtime_paths}
                assert_identities(active_history, normalize_paths(document), deferred_routes)
            except (ValueError, HTTPError, URLError, TimeoutError) as exc:
                if not registry.get("auto_register"):
                    raise
                # Keep published pages/specs intact while reporting the exact
                # blocked cutover; another catalog can still make progress.
                coverage["providers"].setdefault(provider, coverage_rows(facts, {"paths": {}}, [], catalogs))
                for row in coverage["providers"][provider]:
                    row["status"] = "pending"
                    row["reason"] = str(exc) if row["reason"] in (None, "operation_not_composed") else row["reason"]
                    from contract_readiness import reason_code
                    row['reason_code'] = reason_code(row['reason'])
                    row['publication_state'] = 'retained'
                pending["providers"][provider] = unresolved + [{"reason": str(exc)}]
                summary[provider] = {"changed": False, "operations": sum(1 for _ in operations(previous)), "pending": len(coverage["providers"][provider]), "blocked": str(exc)}
                continue
            for path, method, op in operations(normalize_paths(document)):
                moved.add((path, method, op["operationId"], provider))
            ready[provider] = (document, facts, history, previous, unresolved)
            # Capture independent composition before prior document_hash can
            # cause old bytes to be reused as the publication candidate.
            if readiness_context is not None:
                recomposed_documents[provider] = copy.deepcopy(document)
            continue
        attach_history(document, identity_history)
        if with_pages:
            generate_pages(root, provider, document, changes, previous, decorate_links=not entry.get("pin"), page_references=page_references)
        elif page_link_index is not None:
            project_links(document, select_pages(provider, document, *page_link_index))
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
            if changed or not reuse_unchanged_documents:
                changes[output_path] = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
            else:
                # generated_at is observational, and cannot create commit churn.
                document = previous
                if with_pages:
                    generate_pages(root, provider, document, changes, previous, decorate_links=False, page_references=page_references)
        pending["providers"][provider] = unresolved
        summary[provider] = {"changed": changed, "operations": sum(1 for _ in operations(document)), "pending": len(unresolved), "document_hash": new_hash}
    # Resolve ownership across all successfully composed providers before
    # retaining history. A provider can lose one lifecycle while keeping its
    # other active routes; its disabled historical copy must not duplicate the
    # new canonical owner's immutable operation ID.
    for provider, (document, facts, history, previous, unresolved) in ready.items():
        history = copy.deepcopy(history)
        for path, method, op in list(operations(history)):
            targets = {dest for p, m, oid, dest in moved if oid == op.get("operationId")}
            if targets and provider not in targets:
                del history["paths"][path][method]
                if not (set(history["paths"][path]) & METHODS):
                    del history["paths"][path]
        unresolved.extend(retain_unregistered_history(document, facts, history))
        assert_identities(history, normalize_paths(document))
        attach_history(document, identity_history)
        if provider in recomposed_documents:
            attach_history(recomposed_documents[provider], identity_history)
        if with_pages:
            generate_pages(root, provider, document, changes, previous, page_references=page_references)
        elif page_link_index is not None:
            project_links(document, select_pages(provider, document, *page_link_index))
        old_hash = previous.get("info", {}).get("x-aisa-document", {}).get("document_hash")
        new_hash = document.get("info", {}).get("x-aisa-document", {}).get("document_hash")
        if not new_hash:
            raise ValueError(f"{provider}: generated document has no document_hash")
        changed = old_hash != new_hash
        if changed or not reuse_unchanged_documents:
            changes[root / f"openapi/{provider}.json"] = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        elif with_pages:
            generate_pages(root, provider, previous, changes, previous, decorate_links=False, page_references=page_references)
        pending["providers"][provider] = unresolved
        summary[provider] = {"changed": changed, "operations": sum(1 for _ in operations(document)), "pending": len(unresolved), "document_hash": new_hash}
    # Retire only operations successfully moved to another output. Keeping
    # unmatched legacy operations avoids deleting docs outside runtime scope.
    from urllib.parse import urlsplit
    disabled_paths = disabled_legacy_paths(registry, index, facts_by_provider)
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
                reason = "not_in_composed_runtime_contract"
                if prefix + path in disabled_paths.get(name, set()):
                    retained_prefix = urlsplit((retained.get("servers") or [{"url": ""}])[0]["url"]).path.rstrip("/")
                    retained_path = (prefix + path).removeprefix(retained_prefix)
                    operation = retained.get("paths", {}).get(retained_path, {}).get(method)
                    if operation is not None:
                        operation["x-aisa-status"] = "disabled"
                        reason = "runtime_explicitly_disabled"
                coverage["legacy_operations"].append(legacy_coverage_row(name, prefix + path, method, op.get("operationId"), reason == "runtime_explicitly_disabled"))
        if retained != staged:
            changes[output_path] = json.dumps(retained, indent=2, ensure_ascii=False) + "\n"
    documents = dict(original_documents)
    from runtime_consolidate_openapi import SKIP_FILES
    for path, content in changes.items():
        if path.parent == root / 'openapi' and path.suffix == '.json' and path.name not in SKIP_FILES:
            documents[path.stem] = json.loads(content)
    if with_pages:
        catalog = read_json(root / "translations/openapi-zh.json", {"entries": {}})
        # A blocked recomposition can retain a previously published managed
        # document while old pages still reference its retired legacy owner.
        # Rebind presentation to that unchanged document by stable identity;
        # coverage remains pending/retained and grants no freshness evidence.
        for provider, result in summary.items():
            retained = documents.get(provider, {})
            if result.get('blocked') and retained.get('info', {}).get('x-aisa-document', {}).get('document_hash'):
                generate_pages(root, provider, retained, changes, retained,
                               decorate_links=False, page_references=page_references)
        refresh_localized_documents(root, documents, changes, catalog, identity_history)
    if with_pages:
        refresh_legacy_page_blocks(root, documents, changes, catalog)
    from gap_evidence import response_gap_rows
    validate_document_identities(documents, identity_history)
    coverage['response_gaps'] = {provider: response_gap_rows(documents.get(provider, {}), facts_by_provider.get(provider, {}), rows,
                                                         response_identity_v2=response_identity_v2)
        for provider, rows in coverage['providers'].items()}
    if registry.get("auto_register"):
        changes[registry_path] = yaml.safe_dump(registry, sort_keys=False, allow_unicode=True)
        changes[root / "openapi/coverage.json"] = json.dumps(coverage, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    changes[root / "openapi/pending.json"] = json.dumps(pending, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if readiness_context is not None:
        from contract_readiness import check_readiness
        documents = dict(original_documents)
        from runtime_consolidate_openapi import SKIP_FILES
        for path, content in changes.items():
            if path.parent == root / 'openapi' and path.suffix == '.json' and path.name not in SKIP_FILES:
                documents[path.stem] = json.loads(content)
        readiness_context['documents'] = documents
        readiness_context['facts_by_provider'] = facts_by_provider
        readiness_context['coverage'] = coverage
        readiness_context['runtime_index'] = index
        readiness_context['recomposed_documents'] = recomposed_documents
        readiness_context['report'] = check_readiness(
            facts_by_provider, documents, coverage,
            baseline_coverage=readiness_context.get('baseline_coverage'),
            runtime_index=index, deferred_definitions=deferred)
        from check_contract_candidate import assess_fresh_contracts
        assess_fresh_contracts(readiness_context['report'], documents, recomposed_documents, coverage)
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
    parser.add_argument('--baseline-ref', help='Full reviewed Git revision containing accepted coverage; never inferred from current generated files')
    parser.add_argument('--readiness-mode', choices=('publication', 'pr'), default='publication')
    parser.add_argument('--readiness-report', type=Path, help='Write the readiness report, including failures, outside published contract inputs')
    args = parser.parse_args()
    try:
        from check_contract_candidate import load_baseline
        context = {'baseline_coverage': load_baseline(args.root, args.baseline_ref)}
        changes, summary = stage(args.root, args.facts_dir, args.base_url, not args.skip_pages, context)
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"Runtime unavailable; no files written: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Contract pull aborted; no files written: {exc}", file=sys.stderr)
        return 1
    report = context['report']
    if args.readiness_report:
        args.readiness_report.parent.mkdir(parents=True, exist_ok=True)
        args.readiness_report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({"dry_run": not args.write, "providers": summary, "readiness": report, "files": [str(p.relative_to(args.root)) for p in sorted(changes)]}, indent=2))
    # Actual automatic-source acquisition remains evidence even when an
    # unrelated candidate issue blocks publication. Only this non-public cache
    # may be saved before the gate; no contract or source mirror is written.
    receipt_path = args.root / '.cache/source-reviews.json'
    if args.write and receipt_path in changes:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(changes[receipt_path])
    if report.get('global_errors') or report.get('missing_inputs') or report['status'] == 'not_assessed':
        return 3
    if any(provider.get('errors') for provider in report.get('providers', {}).values()):
        return 1
    if args.readiness_mode == 'pr' and report['status'] != 'passed':
        return 1
    if args.write:
        for path, content in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
