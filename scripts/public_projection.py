#!/usr/bin/env python3
"""Customer-facing projection of catalog contracts: openapi-public/ (Spec #1285 R1 §2.5).

The formal catalog files under openapi/ keep provenance and upstream binding
fields that the Composer and the formal readiness checks need (source URLs,
converter names, unsalted upstream path/origin hashes, upstream routes). This
script writes a public copy of each reviewed catalog with those fields removed:

    openapi/<id>.json     -> openapi-public/<id>.json
    openapi/zh/<id>.json  -> openapi-public/zh/<id>.json

The same projection also writes openapi-public/openapi.json and openapi.yaml
from the formal aggregate. Publication file hashes bind both; active website
receivers copy those exact bytes. Formal aggregate hashes remain the publication
authority and are not substituted with customer projection hashes.

Paths, schemas, customer prices and status retain their declarations. In-scope
request examples remain available as static documentation. Runtime evidence marks
whether a scenario has been verified; only generated Reference samples require
that verification. Public descriptions and response schemas stay available.
Internal price construction and revision references are removed; legacy
pricing summaries are removed in favor of the current pricing section. ``info.x-aisa-document.document_hash`` is recomputed over
the projected document; the formal hash it replaces is kept as
``info.x-aisa-document.public_projection.source_document_hash`` so a consumer
can bind the projection to the formal publication.

The reviewed catalog list is scripts/public_projection.json. API reference
pages of those catalogs use the projection for both their Mintlify schema
reference and their "Complete OpenAPI definition" link. Original formal files
are excluded from the deployed site. Formal validation keeps reading openapi/.

    python scripts/public_projection.py --write   # regenerate (publication)
    python scripts/public_projection.py --check   # exit 1 if missing or stale

release_gate.py (G3) runs the same check and also blocks when an in-scope
operation lives in a catalog that is not projected.
"""
from __future__ import annotations

import argparse
import copy
from functools import lru_cache
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / 'scripts/public_projection.json'
PUBLIC_DIR = 'openapi-public'
PROJECTION_VERSION = '4'

# Removed at any depth. The first five are the G3 fields of the design; the
# upstream route and selector name the supplier-side endpoint shape.
STRIPPED_KEYS = frozenset({
    'x-aisa-revision',
    'upstream_origin_sha256',
    'upstream_path_sha256',
    'x-aisa-source',
    'x-aisa-source-provenance',
    'x-aisa-response-source',
    'x-aisa-response-upstream-path-sha256',
    'x-aisa-response-upstream-origin-sha256',
    'x-aisa-upstream-path',
    'x-aisa-upstream-selector',
})
# Never descend into data positions: a customer value that happens to use one
# of these key names is data, not provenance.
DATA_KEYS = frozenset({'example', 'examples', 'default', 'enum', 'const'})


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                                 ensure_ascii=False).encode()).hexdigest()


def load_catalogs(path=CATALOGS):
    document = json.loads(Path(path).read_text())
    if document.get('schema_version') != 1:
        raise ValueError('unsupported public projection list version')
    catalogs = document.get('catalogs')
    if not isinstance(catalogs, list) or catalogs != sorted(set(catalogs)):
        raise ValueError('public projection catalogs must be a sorted list of unique ids')
    for name in catalogs:
        if not isinstance(name, str) or not name or '/' in name or name.startswith('.') or name == 'openapi':
            raise ValueError('invalid public projection catalog id: ' + repr(name))
    return catalogs


def customer_pricing(pricing):
    """Keep customer prices, excluding the supplier cost used to derive them."""
    public = copy.deepcopy(pricing)
    cost_kind = public.get('cost_contract')
    if cost_kind and 'customer_pricing' not in public:
        public['customer_pricing'] = 'fixed_success' if cost_kind == 'fixed_success' else 'usage_based'
    private = ['customer_multiplier', 'cost_contract', 'evidence_source', 'minimum_cost_usd']
    if cost_kind or public.get('customer_pricing') == 'provider_cost_multiplier':
        private.append('unit_rate_usd')
    for key in private:
        public.pop(key, None)
    if public.get('customer_pricing') == 'provider_cost_multiplier':
        public['customer_pricing'] = 'usage_based'
    if public.get('unit') == 'provider_credit':
        public.pop('unit')
    return public


def strip(node):
    """Strip declarations, preserving schema property names and JSON instances."""
    from compose_openapi import NAMED_CONTRACT_MAPS
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in STRIPPED_KEYS:
                continue
            if key in DATA_KEYS:
                result[key] = copy.deepcopy(value)
            elif key == 'x-aisa-pricing' and isinstance(value, dict):
                result[key] = customer_pricing(value)
            elif key in NAMED_CONTRACT_MAPS and isinstance(value, dict):
                result[key] = {name: strip(declaration) for name, declaration in value.items()}
            else:
                result[key] = strip(value)
        return result
    if isinstance(node, list):
        return [strip(value) for value in node]
    return node


@lru_cache(maxsize=1)
def evidence_scope():
    # The same reviewed inventory used by the release gate, including older
    # Runtime releases which predate the x-aisa-example marker.
    source = ROOT / 'scripts/release_gate_scope.json'
    return frozenset(json.loads(source.read_text())['operations'])


def mark_example_verification(operation, language="en"):
    from playground_examples import apply_example_verification, verification_state
    state = verification_state(operation)
    if state is not None and state[0] == 'verified':
        return
    if state is None:
        operation['x-aisa-example'] = {'state': 'pending', 'reason': 'no_evidence'}
    elif operation['x-aisa-example'].get('state') == 'verified':
        operation['x-aisa-example'] = {'state': 'pending', 'reason': state[1]}
    previous = operation.get('x-aisa-verification', {})
    apply_example_verification(operation)
    from playground_examples import PENDING_REASONS
    if state and state[1] == 'no_evidence' and previous.get('reason') in PENDING_REASONS:
        operation['x-aisa-verification']['reason'] = previous['reason']

    # Mintlify renders the operation description, not arbitrary extensions.
    # Keep the evidence label visible beside the retained static examples.
    from readable_contract_notes import PENDING_NOTICE_EN, PENDING_NOTICE_ZH
    notice = PENDING_NOTICE_ZH if language == 'zh' else PENDING_NOTICE_EN
    description = operation.get('description', '')
    if notice not in description:
        operation['description'] = (description.rstrip() + '\n\n' + notice).lstrip()


def project(document, language="en"):
    """Projected catalog document (pure function of the formal document)."""
    projected = strip(document)
    from pricing_prose import remove_price_summary
    for route, item in projected.get('paths', {}).items():
        for method, operation in item.items():
            if method in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'} and isinstance(operation, dict) and 'aisa-pricing:start' in operation.get('description', ''):
                remove_price_summary(operation)
            if method in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'} and isinstance(operation, dict):
                if 'x-aisa-example' in operation or method.upper() + ' ' + route in evidence_scope():
                    mark_example_verification(operation, language)
    info = projected.get('info')
    meta = info.get('x-aisa-document') if isinstance(info, dict) else None
    if isinstance(meta, dict):
        meta = dict(meta)
        source_hash = meta.pop('document_hash', None)
        meta['public_projection'] = {'version': PROJECTION_VERSION, 'source_document_hash': source_hash}
        info['x-aisa-document'] = meta
        meta['document_hash'] = digest(projected)
    return projected


def render(document):
    return (json.dumps(document, indent=2, ensure_ascii=False) + '\n').encode()


def public_path(spec_path, catalogs):
    """Map openapi[/zh]/<id>.json to its projection when <id> is projected."""
    parts = spec_path.split('/')
    if parts[0] != 'openapi' or not parts[-1].endswith('.json'):
        return spec_path
    if parts[-1][:-len('.json')] in catalogs and (len(parts) == 2 or (len(parts) == 3 and parts[1] == 'zh')):
        return '/'.join([PUBLIC_DIR, *parts[1:]])
    return spec_path


_LINK_CATALOGS = None


def link_catalogs():
    """Projected catalog ids of this checkout (cached; empty without a list)."""
    global _LINK_CATALOGS
    if _LINK_CATALOGS is None:
        _LINK_CATALOGS = frozenset(load_catalogs()) if CATALOGS.is_file() else frozenset()
    return _LINK_CATALOGS


def expected_files(root=ROOT, catalogs=None):
    """{relative path: bytes} of the complete projection for this checkout."""
    root = Path(root)
    catalogs = load_catalogs(root / 'scripts/public_projection.json') if catalogs is None else catalogs
    files = {}
    for name in catalogs:
        for language in ('', 'zh/'):
            source = root / 'openapi' / (language + name + '.json')
            if source.is_file():
                files[f'{PUBLIC_DIR}/{language}{name}.json'] = render(project(json.loads(source.read_text()), "zh" if language else "en"))
    # The active website consumes the same projection, bound by publication
    # file hashes. Keep the formal aggregate unchanged for replay/validation.
    aggregate = root / 'openapi/openapi.json'
    if aggregate.is_file():
        from runtime_consolidate_openapi import publication_yaml
        public = project(json.loads(aggregate.read_text()))
        files[f'{PUBLIC_DIR}/openapi.json'] = (json.dumps(public, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
        files[f'{PUBLIC_DIR}/openapi.yaml'] = publication_yaml(public).encode()
    return files


def actual_files(root):
    directory = Path(root) / PUBLIC_DIR
    if not directory.is_dir():
        return {}
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob('*')) if path.is_file()}


def public_surface_changes(root, catalogs):
    """Keep Mintlify's actual schema input on the same customer projection.

    Formal OpenAPI remains available to private build/replay tooling, and is
    excluded from the deployed site. Existing editorial MDX stays byte-identical
    apart from its schema reference.
    """
    root = Path(root)
    changes = {}
    for directory in ('api-reference', 'zh/api-reference'):
        for page in (root / directory).rglob('*.mdx'):
            text = page.read_text()
            projected = re.sub(r'^(openapi:\s*[\"\']?)(openapi/[^\s\"\']+\.json)',
                               lambda match: match[1] + public_path(match[2], catalogs), text, flags=re.M)
            if projected != text:
                changes[page.relative_to(root).as_posix()] = projected.encode()
    ignore = root / '.mintignore'
    if ignore.is_file():
        start, end = '# BEGIN customer contract projection', '# END customer contract projection'
        text = ignore.read_text()
        text = re.sub(re.escape(start) + r'.*?' + re.escape(end) + r'\n?', '', text, flags=re.S).rstrip()
        excluded = [f'/openapi/{prefix}{name}.json' for name in sorted(catalogs) for prefix in ('', 'zh/')]
        updated = text + '\n' + start + '\n' + '\n'.join(excluded) + '\n' + end + '\n'
        if updated != ignore.read_text():
            changes['.mintignore'] = updated.encode()
    return changes


def check(root=ROOT, catalogs=None):
    """[(relative path, problem)] with problem in missing | stale | unexpected."""
    expected, actual = expected_files(root, catalogs), actual_files(root)
    problems = [(name, 'missing') for name in sorted(set(expected) - set(actual))]
    problems += [(name, 'stale') for name in sorted(set(expected) & set(actual)) if expected[name] != actual[name]]
    problems += [(name, 'unexpected') for name in sorted(set(actual) - set(expected))]
    selected = load_catalogs(Path(root) / "scripts/public_projection.json") if catalogs is None else catalogs
    problems += [(name, "private_surface") for name in sorted(public_surface_changes(root, selected))]
    return problems


def write(root=ROOT, catalogs=None):
    root = Path(root)
    expected = expected_files(root, catalogs)
    for name in sorted(set(actual_files(root)) - set(expected)):
        (root / name).unlink()
    for name, raw in expected.items():
        target = root / name
        if target.is_symlink():
            raise ValueError('public projection target is a symlink: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != raw:
            target.write_bytes(raw)
    selected = load_catalogs(root / "scripts/public_projection.json") if catalogs is None else catalogs
    for name, raw in public_surface_changes(root, selected).items():
        (root / name).write_bytes(raw)
    return sorted(expected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if args.write:
        written = write(args.root)
        print(json.dumps({'status': 'written', 'files': len(written)}))
        return 0
    problems = check(args.root)
    for name, problem in problems[:200]:
        print(f'{name}: {problem}', file=sys.stderr)
    print(json.dumps({'status': 'failed' if problems else 'passed', 'problems': len(problems)}))
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
