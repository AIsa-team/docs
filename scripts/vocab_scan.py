#!/usr/bin/env python3
"""Scan customer-visible Docs text for supplier vocabulary and internal notes.

Spec #1285 R1 G2. Findings name only a location (``file:line`` for text,
``file#/json/pointer`` for JSON) and a rule id or the 1-based index of the
matched secret term. A matched supplier word is never printed, logged or
written to a report: the secret list stays secret even in public CI logs.

Supplier terms come from the ``SUPPLIER_VOCAB_JSON`` environment variable
(a JSON list of strings, or ``{"terms": [...]}``). Terms equal to a public
brand or a public catalog id are excluded automatically, as are terms shorter
than three characters. Internal-note and hash-field rules are public regular
expressions in ``scripts/public_vocab_rules.json``.

Only text a reader sees is scanned: summary, description, title, notes, tag
names, code sample sources and other ``x-aisa-*`` text. Business values in
request/response examples (``example``, ``examples``, ``default``, ``enum``,
``const``, ``pattern``) are data, not prose, and are skipped. Provenance
objects (``x-aisa-source`` and friends) are checked by the G3 field gate, not
here.
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
RULES = ROOT / 'scripts/public_vocab_rules.json'
SECRET_ENV = 'SUPPLIER_VOCAB_JSON'

# Data positions: values a customer sends or receives, not documentation prose.
DATA_KEYS = frozenset({'example', 'examples', 'default', 'enum', 'const', 'pattern', 'value',
                       'externalValue', 'x-aisa-example'})
# Provenance and binding objects: their presence is a G3 question.
PROVENANCE_KEYS = frozenset({'x-aisa-source', 'x-aisa-source-provenance', 'x-aisa-response-source',
                             'x-aisa-revision', 'x-aisa-document', 'x-aisa-contract-source',
                             'x-aisa-response-upstream-path-sha256', 'x-aisa-response-upstream-origin-sha256',
                             'x-aisa-runtime-operation', 'x-aisa-docs-url', 'x-aisa-plans', '$ref', '$schema',
                             'x-aisa-configured-paths', 'x-aisa-verification'})
TEXT_KEYS = frozenset({'summary', 'description', 'title', 'label', 'source', 'name', 'x-aisa-notes', 'notes',
                       'tags', 'group', 'tab', 'anchor'})
PRICING_BLOCK = re.compile(r'<!-- aisa-pricing:start -->.*?<!-- aisa-pricing:end -->', re.S)
FENCE = re.compile(r'^(`{3,})json[^\n]*\n(.*?)^\1[ \t]*$', re.S | re.M)


class Rules:
    def __init__(self, document, terms=(), public_names=()):
        if document.get('schema_version') != 1:
            raise ValueError('unsupported vocabulary rules version')
        self.internal = [(row['id'], re.compile(row['pattern'])) for row in document.get('internal_note', [])]
        self.hashes = [(row['id'], re.compile(row['pattern'])) for row in document.get('hash_field', [])]
        excluded = {name.lower() for name in [*document.get('public_brands', []), *public_names]}
        self.term_count = len(terms)
        self.terms = []
        for index, term in enumerate(terms, 1):
            if not isinstance(term, str):
                raise ValueError('supplier vocabulary entries must be strings')
            word = term.strip().lower()
            if len(word) < 3 or word in excluded:
                continue
            self.terms.append((index, re.compile(r'(?<![a-z0-9])' + re.escape(word) + r'(?![a-z0-9])', re.I)))
        self.digest = vocab_digest(terms)


def vocab_digest(terms):
    """Digest of the normalized secret list, comparable with the worker's registry digest."""
    normalized = sorted({str(term).strip().lower() for term in terms if str(term).strip()})
    return 'sha256:' + hashlib.sha256('\n'.join(normalized).encode()).hexdigest()


def load_terms(environ=None):
    raw = (environ if environ is not None else os.environ).get(SECRET_ENV, '').strip()
    if not raw:
        return []
    value = json.loads(raw)
    if isinstance(value, dict):
        value = value.get('terms', [])
    if not isinstance(value, list):
        raise ValueError(SECRET_ENV + ' must be a JSON list or {"terms": [...]}')
    return value


def load_rules(path=RULES, terms=(), public_names=()):
    return Rules(json.loads(Path(path).read_text()), terms, public_names)


def scan_text(text, rules, *, generated_pricing=True):
    """Return [(class, rule)] for one text value. Rule is an id or a term index."""
    hits = []
    for index, pattern in rules.terms:
        if pattern.search(text):
            hits.append(('supplier', index))
    prose = PRICING_BLOCK.sub(' ', text) if generated_pricing else text
    for rule, pattern in rules.internal:
        if pattern.search(prose):
            hits.append(('internal_note', rule))
    for rule, pattern in rules.hashes:
        if pattern.search(text):
            hits.append(('hash_field', rule))
    return hits


def escape_pointer(token):
    return str(token).replace('~', '~0').replace('/', '~1')


def text_values(node, pointer='', key=None):
    """Yield (pointer, text) for prose positions of a JSON document."""
    if isinstance(node, dict):
        for name, value in node.items():
            if name in DATA_KEYS or name in PROVENANCE_KEYS:
                continue
            yield from text_values(value, pointer + '/' + escape_pointer(name), name)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from text_values(value, pointer + '/' + str(index), key)
    elif isinstance(node, str):
        if key in TEXT_KEYS or (isinstance(key, str) and key.startswith('x-aisa-')):
            yield pointer, node


def scan_json(document, rules, location, pointer=''):
    findings = []
    for path, text in text_values(document, pointer):
        for kind, rule in scan_text(text, rules):
            findings.append(finding(location + '#' + path, kind, rule))
    return findings


def scan_mdx(text, rules, location):
    """Scan page prose line by line; fenced JSON blocks use the JSON rules."""
    findings, consumed = [], []
    for match in FENCE.finditer(text):
        start_line = text.count('\n', 0, match.start(2)) + 1
        try:
            document = json.loads(match.group(2))
        except ValueError:
            continue
        consumed.append((match.start(), match.end()))
        for row in scan_json(document, rules, f'{location}:{start_line}'):
            findings.append(row)
    offset = 0
    for number, line in enumerate(text.split('\n'), 1):
        start_of_line, offset = offset, offset + len(line) + 1
        if any(start <= start_of_line < end for start, end in consumed):
            continue
        if line.startswith('openapi:'):
            continue  # Page binding to a public catalog document path.
        for kind, rule in scan_text(line, rules):
            findings.append(finding(f'{location}:{number}', kind, rule))
    return findings


def scan_plain(text, rules, location):
    findings = []
    for number, line in enumerate(text.split('\n'), 1):
        for kind, rule in scan_text(line, rules):
            findings.append(finding(f'{location}:{number}', kind, rule))
    return findings


def finding(location, kind, rule):
    row = {'location': location, 'class': kind}
    if kind == 'supplier':
        row['term_index'] = rule
    else:
        row['rule'] = rule
    return row


def scan_file(path, rules, root=ROOT):
    path = Path(path)
    location = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
    raw = path.read_text(encoding='utf-8')
    if path.suffix == '.json':
        return scan_json(json.loads(raw), rules, location)
    if path.suffix in {'.mdx', '.md'}:
        return scan_mdx(raw, rules, location)
    return scan_plain(raw, rules, location)


def public_catalog_ids(root=ROOT):
    """Public catalog ids are customer-visible names and never supplier terms."""
    return sorted(p.stem for p in (Path(root) / 'openapi').glob('*.json') if p.stem != 'openapi')


DEFAULT_GLOBS = ('openapi/*.json', 'openapi/zh/*.json', 'api-reference/**/*.mdx',
                 'zh/api-reference/**/*.mdx', 'llms.txt', 'docs.json')


def customer_files(root=ROOT, globs=DEFAULT_GLOBS):
    root = Path(root)
    seen = []
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path.name != 'openapi.json' and path not in seen:
                seen.append(path)
    return seen


def summarize(findings, rules):
    counts = {}
    for row in findings:
        counts[row['class']] = counts.get(row['class'], 0) + 1
    return {'status': 'failed' if findings else 'passed', 'counts': counts,
            'supplier_terms': len(rules.terms), 'supplier_terms_configured': rules.term_count,
            'vocab_digest': rules.digest, 'findings': findings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--rules', type=Path, default=RULES)
    parser.add_argument('--report', type=Path)
    parser.add_argument('paths', nargs='*', type=Path, help='Files to scan (default: all customer-visible Docs files)')
    args = parser.parse_args(argv)
    rules = load_rules(args.rules, load_terms(), public_catalog_ids(args.root))
    files = [p if p.is_absolute() else args.root / p for p in args.paths] or customer_files(args.root)
    findings = []
    for path in files:
        findings += scan_file(path, rules, args.root)
    report = summarize(findings, rules)
    rendered = json.dumps(report, indent=2) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered)
    for row in findings[:200]:
        print(f"{row['location']}: {row['class']} {row.get('rule', row.get('term_index'))}", file=sys.stderr)
    print(json.dumps({key: report[key] for key in ('status', 'counts', 'supplier_terms', 'vocab_digest')}))
    return 0 if not findings else 1


if __name__ == '__main__':
    raise SystemExit(main())
