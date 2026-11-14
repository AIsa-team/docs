#!/usr/bin/env python3
"""Spec #1285 R1 release gate: block a Docs publication on global contract faults.

Runs after formal readiness and before export in pull-openapi.yml, and in the
same mode on pull requests (test-runtime-contracts.yml). Any failing gate
exits 1 and the publication is neither exported nor pushed:

* G1 aggregate consistency: openapi.yaml and openapi/openapi.json parse to the
  same document; llms.txt declares sha256(openapi.yaml); the integration
  operation set {(method, path, operationId)} under /apis/v1/ equals the
  Runtime release aggregate, minus reviewed scripts/aggregate_exclusions.json.
* G2 vocabulary: customer-visible text of in-scope public projections, their pages,
  llms.txt and docs.json contain no supplier term, internal note or upstream
  hash text (vocab_scan.py).
* G3 forbidden content: no placeholder values in verified request examples or
  Reference examples; no provenance field names in rendered pages or llms.txt;
  the public projection openapi-public/ (public_projection.py) exists for
  every in-scope catalog, equals a fresh projection of openapi/, and holds no
  provenance field.
* G4 example evidence: every in-scope public Reference example joins a Runtime
  `x-aisa-example` record with state `verified` and the same example SHA256.

A missing example is not a fault: such operations are listed as pending with
a reason and still published. Static request examples do not need production
evidence; only generated Reference examples are withheld while pending.

In scope are the operations Runtime marks with `x-aisa-example` plus the
reviewed inventory in scripts/release_gate_scope.json.

RELEASE_GATE_ENFORCE=false is a rollback switch only: the report still says
`failed`, but the exit code is 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from playground_examples import REFERENCE_LABEL, example_scenario, example_sha256  # noqa: E402
from upstream_semantics import BLOCKING_DRIFT  # noqa: E402
import public_projection  # noqa: E402
from release_gate_pagination import check_g6
import vocab_scan  # noqa: E402

METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')
SCOPE = ROOT / 'scripts/release_gate_scope.json'
EXCLUSIONS = ROOT / 'scripts/aggregate_exclusions.json'
DRIFT = ROOT / 'docs/publication/upstream-drift.json'
PROJECTION = public_projection.CATALOGS
REPORT = ROOT / 'docs/publication/release-gate.json'
AGGREGATE = 'contracts/openapi.json'
INTEGRATION_PREFIX = '/apis/v1/'
DECLARED = re.compile(r'Declared API contract \(OpenAPI YAML SHA-256\): ([0-9a-f]{64})')
FINDINGS_LIMIT = 500

# G3 placeholder values (design §2.2). The Reference example's first line is
# our own fixed header comment and is not a request value.
PLACEHOLDERS = [
    ('PH01', re.compile(r'(?<![\w.@/-])example(?![\w-])', re.I)),
    ('PH02', re.compile(r'\bexample\.com\b', re.I)),
    ('PH03', re.compile(r'\b(?:hello|person)@example\.com\b', re.I)),
    ('PH04', re.compile(r'linkedin\.com/in/example\b', re.I)),
    ('PH05', re.compile(r'\bJane Doe\b')),
    ('PH06', re.compile(r'\bYOUR_[A-Z_]+')),
]
PROVENANCE_FIELDS = ('x-aisa-source', 'x-aisa-source-provenance', 'x-aisa-response-source',
                     'x-aisa-response-upstream-path-sha256', 'x-aisa-response-upstream-origin-sha256')
PROVENANCE_TEXT = re.compile(r'x-aisa-(?:source|source-provenance|response-source|response-upstream-(?:path|origin)-sha256)\b')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load_yaml(path):
    import yaml
    loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
    with open(path, 'rb') as handle:
        return yaml.load(handle, Loader=loader)


def integration_operations(document):
    result = set()
    for path, item in (document.get('paths') or {}).items():
        if not path.startswith(INTEGRATION_PREFIX) or not isinstance(item, dict):
            continue
        for method in METHODS:
            operation = item.get(method)
            if isinstance(operation, dict):
                result.add((method.upper(), path, operation.get('operationId')))
    return result


def gate_g1(root, facts_dir, exclusions, *, yaml_loader=load_yaml):
    checks, errors = {}, []
    aggregate_json = json.loads((root / 'openapi/openapi.json').read_text())
    yaml_path = root / 'openapi.yaml'
    if yaml_loader(yaml_path) != aggregate_json:
        errors.append('openapi.yaml and openapi/openapi.json differ')
    checks['yaml_json_equal'] = not errors
    actual = sha256_file(yaml_path)
    declared = DECLARED.findall((root / 'llms.txt').read_text())
    checks['llms_declared_sha256'] = declared
    checks['openapi_yaml_sha256'] = actual
    if declared != [actual]:
        errors.append('llms.txt does not declare exactly sha256(openapi.yaml)')
    if facts_dir is None:
        errors.append('Runtime release aggregate not provided')
        checks['operation_set'] = 'not_assessed'
    else:
        release = json.loads((Path(facts_dir) / AGGREGATE).read_text())
        docs_ops, release_ops = integration_operations(aggregate_json), integration_operations(release)
        excluded_docs = {tuple(row['operation']) for row in exclusions.get('docs_only', [])}
        excluded_release = {tuple(row['operation']) for row in exclusions.get('release_only', [])}
        docs_only = sorted(docs_ops - release_ops - excluded_docs)
        release_only = sorted(release_ops - docs_ops - excluded_release)
        checks['operation_set'] = {'docs': len(docs_ops), 'release': len(release_ops),
                                   'docs_only': [list(row) for row in docs_only[:50]],
                                   'release_only': [list(row) for row in release_only[:50]]}
        if docs_only or release_only:
            errors.append(f'integration operation sets differ: {len(docs_only)} docs-only, {len(release_only)} release-only')
    return {'status': 'failed' if errors else 'passed', 'errors': errors, 'checks': checks}


def load_scope(path):
    document = json.loads(Path(path).read_text())
    if document.get('schema_version') != 1:
        raise ValueError('unsupported scope version')
    return {tuple(row.split(' ', 1)) for row in document['operations']}


def in_scope_operations(root, scope, catalogs=None):
    """Yield (catalog file, path, method, operation) for in-scope operations."""
    for path in sorted((root / 'openapi').glob('*.json')):
        if path.name == 'openapi.json' or (catalogs is not None and path.stem not in catalogs):
            continue
        document = json.loads(path.read_text())
        for route, item in (document.get('paths') or {}).items():
            if not isinstance(item, dict):
                continue
            for method in METHODS:
                operation = item.get(method)
                if not isinstance(operation, dict):
                    continue
                if 'x-aisa-example' in operation or (method.upper(), route) in scope:
                    yield path, document, route, method, operation


def page_paths(root, operation):
    url = operation.get('x-aisa-docs-url') or ''
    prefix = 'https://aisa.one/docs/'
    if not url.startswith(prefix):
        return []
    slug = url[len(prefix):]
    return [p for p in (root / (slug + '.mdx'), root / 'zh' / (slug + '.mdx')) if p.is_file()]


def reference_sources(operation):
    return [sample.get('source', '') for sample in operation.get('x-codeSamples') or []
            if isinstance(sample, dict) and sample.get('label') == REFERENCE_LABEL]


def example_values(operation):
    """(JSON pointer suffix, value) of named examples a playground prefills."""
    escape = vocab_scan.escape_pointer
    values = []
    for index, parameter in enumerate(operation.get('parameters') or []):
        examples = parameter.get('examples') if isinstance(parameter.get('examples'), dict) else {}
        for name, example in examples.items():
            if isinstance(example, dict) and 'value' in example:
                values.append((f'parameters/{index}/examples/{escape(name)}/value', example['value']))
        if 'example' in parameter:
            values.append((f'parameters/{index}/example', parameter['example']))
    for media_type, media in ((operation.get('requestBody') or {}).get('content') or {}).items():
        examples = media.get('examples') if isinstance(media.get('examples'), dict) else {}
        for name, example in examples.items():
            if isinstance(example, dict) and 'value' in example:
                values.append((f'requestBody/content/{escape(media_type)}/examples/{escape(name)}/value', example['value']))
        if 'example' in media:
            values.append((f'requestBody/content/{escape(media_type)}/example', media['example']))
    return values


def placeholder_hits(text):
    return [rule for rule, pattern in PLACEHOLDERS if pattern.search(text)]


def strip_reference_header(source):
    lines = source.split('\n')
    return '\n'.join(lines[1:]) if lines and lines[0].startswith('#') else source


def operation_pointer(route, method):
    return '/paths/' + vocab_scan.escape_pointer(route) + '/' + method


def run(root=ROOT, *, facts_dir=None, scope_path=SCOPE, exclusions_path=EXCLUSIONS, rules_path=vocab_scan.RULES,
        drift_path=DRIFT, environ=None, yaml_loader=load_yaml, catalogs=None, projection_path=PROJECTION):
    root = Path(root)
    environ = os.environ if environ is None else environ
    scope = load_scope(scope_path)
    exclusions = json.loads(Path(exclusions_path).read_text())
    drift = json.loads(Path(drift_path).read_text()) if Path(drift_path).exists() else {'operations': []}
    drifted = {row['operation_id']: row['kind'] for row in drift.get('operations', []) if row.get('kind') in BLOCKING_DRIFT}
    rules = vocab_scan.load_rules(rules_path, vocab_scan.load_terms(environ), vocab_scan.public_catalog_ids(root))

    report = {'schema_version': 1, 'gates': {}}
    report['gates']['G1'] = gate_g1(root, facts_dir, exclusions, yaml_loader=yaml_loader)

    projected = public_projection.load_catalogs(projection_path)
    vocab, placeholders, provenance, evidence, pending = [], [], [], [], []
    pages_seen, scoped, unprojected = set(), 0, set()
    pagination_findings, pagination_documents = [], set()
    public_documents = {}
    for path, document, route, method, operation in in_scope_operations(root, scope, catalogs):
        scoped += 1
        if path not in pagination_documents:
            pagination_documents.add(path)
            pagination_findings.extend(check_g6(document))
        location = path.relative_to(root).as_posix()
        pointer = operation_pointer(route, method)
        if path.stem not in projected:
            unprojected.add(path.stem)
        # Inspect the bytes referenced by the deployed pages. The formal
        # source retains compilation/replay annotations and unverified inputs.
        public_path = root / public_projection.PUBLIC_DIR / path.name
        if public_path.is_file():
            if public_path not in public_documents:
                public_documents[public_path] = json.loads(public_path.read_text())
            operation = public_documents[public_path].get('paths', {}).get(route, {}).get(method, {})
            location = public_path.relative_to(root).as_posix()
        vocab += vocab_scan.scan_json(operation, rules, location, pointer)
        zh = root / public_projection.PUBLIC_DIR / 'zh' / path.name
        if zh.is_file():
            zh_document = json.loads(zh.read_text())
            zh_operation = (zh_document.get('paths', {}).get(route) or {}).get(method)
            if isinstance(zh_operation, dict):
                vocab += vocab_scan.scan_json(zh_operation, rules, zh.relative_to(root).as_posix(), pointer)
        for page in page_paths(root, operation):
            if page in pages_seen:
                continue
            pages_seen.add(page)
            text = page.read_text(encoding='utf-8')
            page_location = page.relative_to(root).as_posix()
            vocab += vocab_scan.scan_mdx(text, rules, page_location)
            for number, line in enumerate(text.split('\n'), 1):
                if PROVENANCE_TEXT.search(line):
                    provenance.append({'location': f'{page_location}:{number}', 'rule': 'PV01'})
        sources = reference_sources(operation)
        for index, source in enumerate(sources):
            for rule in placeholder_hits(strip_reference_header(source)):
                placeholders.append({'location': f'{location}#{pointer}/x-codeSamples/{index}', 'rule': rule})
        marker = operation.get('x-aisa-example') if isinstance(operation.get('x-aisa-example'), dict) else None
        operation_id = operation.get('operationId')
        verified = (marker is not None and marker.get('state') == 'verified'
                    and marker.get('sha256') == example_sha256(example_scenario(operation)))
        # Static request examples may use illustrative values. A claim of
        # production verification still requires real, matching evidence.
        if marker and marker.get('state') == 'verified':
            for where, value in example_values(operation):
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                for rule in placeholder_hits(text):
                    placeholders.append({'location': f'{location}#{pointer}/{where}', 'rule': rule})
        if sources and not verified:
            evidence.append({'location': f'{location}#{pointer}', 'operation_id': operation_id,
                             'reason': 'reference_example_without_verified_evidence' if marker is None or marker.get('state') != 'verified'
                             else 'example_sha256_mismatch'})
        if not verified or operation_id in drifted:
            if operation_id in drifted:
                reason = 'upstream_drift'
            elif marker is None:
                reason = 'no_evidence'
            else:
                reason = (operation.get('x-aisa-verification') or {}).get('reason') or marker.get('reason') or (
                    'expired' if marker.get('state') == 'expired' else 'no_evidence')
            if reason in {'no_evidence', 'no_fixture'} and not operation.get('parameters') and not operation.get('requestBody'):
                reason = 'inputs_undeclared'
            pending.append({'operation_id': operation_id, 'method': method.upper(), 'path': route, 'reason': reason})

    for name in ('llms.txt', 'docs.json'):
        target = root / name
        if target.is_file():
            vocab += vocab_scan.scan_file(target, rules, root)
            if name == 'llms.txt':
                for number, line in enumerate(target.read_text().split('\n'), 1):
                    if PROVENANCE_TEXT.search(line):
                        provenance.append({'location': f'llms.txt:{number}', 'rule': 'PV01'})
    for name in sorted(unprojected):
        provenance.append({'location': f'openapi/{name}.json', 'rule': 'PV04', 'problem': 'in_scope_catalog_not_projected'})
    for name, problem in public_projection.check(root, projected):
        provenance.append({'location': name, 'rule': 'PV03', 'problem': problem})
    projection = root / public_projection.PUBLIC_DIR
    projection_state = 'absent'
    if projection.is_dir():
        projection_state = 'checked'
        for file in sorted(projection.rglob('*.json')):
            text = file.read_text()
            for field in PROVENANCE_FIELDS:
                if '"' + field + '"' in text:
                    provenance.append({'location': file.relative_to(root).as_posix(), 'rule': 'PV02', 'field': field})

    counts = {}
    for row in vocab:
        counts[row['class']] = counts.get(row['class'], 0) + 1
    report['gates']['G2'] = {'status': 'failed' if vocab else 'passed', 'counts': counts,
                             'findings': vocab[:FINDINGS_LIMIT], 'findings_total': len(vocab),
                             'supplier_terms': len(rules.terms), 'supplier_terms_configured': rules.term_count}
    report['gates']['G3'] = {'status': 'failed' if placeholders or provenance else 'passed',
                             'placeholders': placeholders[:FINDINGS_LIMIT], 'placeholders_total': len(placeholders),
                             'provenance': provenance[:FINDINGS_LIMIT], 'provenance_total': len(provenance),
                             'public_projection': projection_state}
    reasons = {}
    for row in pending:
        reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
    report['gates']['G4'] = {'status': 'failed' if evidence else 'passed', 'scope_operations': scoped,
                             'violations': evidence[:FINDINGS_LIMIT], 'violations_total': len(evidence),
                             'pending_total': len(pending), 'pending_reasons': dict(sorted(reasons.items())),
                             'pending': sorted(pending, key=lambda r: (r['path'], r['method']))}
    report['gates']['G6'] = {'status': 'failed' if pagination_findings else 'passed',
                             'findings': pagination_findings[:FINDINGS_LIMIT], 'findings_total': len(pagination_findings)}
    report['vocab_digest'] = rules.digest
    report['rules_sha256'] = sha256_file(rules_path)
    report['status'] = 'failed' if any(gate['status'] != 'passed' for gate in report['gates'].values()) else 'passed'
    report['enforced'] = (environ.get('RELEASE_GATE_ENFORCE', 'true').strip().lower() != 'false')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--facts-dir', type=Path, help='Acquired Runtime release (contains contracts/openapi.json)')
    parser.add_argument('--scope', type=Path, default=SCOPE)
    parser.add_argument('--exclusions', type=Path, default=EXCLUSIONS)
    parser.add_argument('--rules', type=Path, default=vocab_scan.RULES)
    parser.add_argument('--drift', type=Path, default=DRIFT)
    parser.add_argument('--projection', type=Path, default=PROJECTION, help='Reviewed public projection catalog list')
    parser.add_argument('--report', type=Path, default=REPORT)
    args = parser.parse_args(argv)
    report = run(args.root, facts_dir=args.facts_dir, scope_path=args.scope, exclusions_path=args.exclusions,
                 rules_path=args.rules, drift_path=args.drift, projection_path=args.projection)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    for name, gate in report['gates'].items():
        print(f'{name}: {gate["status"]}', file=sys.stderr)
        for error in gate.get('errors', []):
            print(f'  {error}', file=sys.stderr)
    # Locations and rule ids only; never a matched supplier word.
    for row in report['gates']['G2']['findings'][:100]:
        print(f"  G2 {row['location']}: {row['class']} {row.get('rule', row.get('term_index'))}", file=sys.stderr)
    for key in ('placeholders', 'provenance'):
        for row in report['gates']['G3'][key][:50]:
            print(f"  G3 {row['location']}: {row['rule']}", file=sys.stderr)
    for row in report['gates']['G4']['violations'][:50]:
        print(f"  G4 {row['location']}: {row['reason']}", file=sys.stderr)
    print(json.dumps({'status': report['status'], 'enforced': report['enforced'],
                      'gates': {name: gate['status'] for name, gate in report['gates'].items()},
                      'pending': report['gates']['G4']['pending_total']}))
    if report['status'] == 'passed' or not report['enforced']:
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
