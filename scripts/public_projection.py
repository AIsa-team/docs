#!/usr/bin/env python3
"""Customer-facing projection of catalog contracts: openapi-public/ (Spec #1285 R1 §2.5).

The formal catalog files under openapi/ keep provenance and upstream binding
fields that the Composer and the formal readiness checks need (source URLs,
converter names, unsalted upstream path/origin hashes, upstream routes). This
script writes a public copy of each reviewed catalog with those fields removed:

    openapi/<id>.json     -> openapi-public/<id>.json
    openapi/zh/<id>.json  -> openapi-public/zh/<id>.json

Paths, schemas, examples, customer prices and status retain their declarations.
Internal price construction and revision references are removed; generated
pricing prose is rebuilt from the public pricing fields. ``info.x-aisa-document.document_hash`` is recomputed over
the projected document; the formal hash it replaces is kept as
``info.x-aisa-document.public_projection.source_document_hash`` so a consumer
can bind the projection to the formal publication.

The reviewed catalog list is scripts/public_projection.json. API reference
pages of those catalogs link their "Complete OpenAPI definition" to the
projection (readable_contract_notes). Formal validation keeps reading
openapi/ and is unchanged.

    python scripts/public_projection.py --write   # regenerate (publication)
    python scripts/public_projection.py --check   # exit 1 if missing or stale

release_gate.py (G3) runs the same check and also blocks when an in-scope
operation lives in a catalog that is not projected.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / 'scripts/public_projection.json'
PUBLIC_DIR = 'openapi-public'
PROJECTION_VERSION = '2'

# Removed at any depth. The first five are the G3 fields of the design; the
# upstream route and selector name the supplier-side endpoint shape.
STRIPPED_KEYS = frozenset({
    'x-aisa-revision',
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


def project(document, language="en"):
    """Projected catalog document (pure function of the formal document)."""
    projected = strip(document)
    from pricing_prose import add_price_summary
    for item in projected.get('paths', {}).values():
        for method, operation in item.items():
            if method in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'} and isinstance(operation, dict) and 'aisa-pricing:start' in operation.get('description', ''):
                add_price_summary(operation, language)
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
    return files


def actual_files(root):
    directory = Path(root) / PUBLIC_DIR
    if not directory.is_dir():
        return {}
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob('*')) if path.is_file()}


def check(root=ROOT, catalogs=None):
    """[(relative path, problem)] with problem in missing | stale | unexpected."""
    expected, actual = expected_files(root, catalogs), actual_files(root)
    problems = [(name, 'missing') for name in sorted(set(expected) - set(actual))]
    problems += [(name, 'stale') for name in sorted(set(expected) & set(actual)) if expected[name] != actual[name]]
    problems += [(name, 'unexpected') for name in sorted(set(actual) - set(expected))]
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
