#!/usr/bin/env python3
"""Refresh a fixed reviewed payment scope using public Runtime 402 challenges.

No credentials, payments, enablement, redirects, or upstream execution. The
offline generator remains network-free. Any acquisition failure leaves the
committed evidence and catalogue untouched. Unchanged terms/contracts retain
their original publication identity; fresh observations go to a run artifact.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from export_contract_publication import acquired_input, RUNTIME_KEYS
from fetch_runtime_release import PublicReader, NoRedirect, decode, require, validate_current, failure_diagnostic
from payment_catalog import (build_publication, canonical_json, contract_binding,
                             digest, key, local_file)
from probe_payment_discovery import parse_challenge

ORIGIN = 'https://api.aisa.one'


class ChallengeReader:
    def __init__(self, deadline):
        self.deadline = deadline
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def __call__(self, spec):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'Payment observation deadline exceeded')
        path = re.sub(r'\{[^{}]+\}', 'discovery', spec['path'])
        require(re.fullmatch(r'/apis/v1/[A-Za-z0-9_./-]+', path) is not None
                and not any(part in ('.', '..', '') for part in path.split('/')[3:]),
                'Unsupported payment route')
        method = spec['method']
        require(method in ('GET', 'POST'), 'Only reviewed read-only GET/POST is supported')
        request = Request(ORIGIN + path, method=method,
                          headers={'X-MPP-Discovery': 'true', 'Accept': 'application/json'},
                          data=b'{}' if method == 'POST' else None)
        observed = datetime.now(timezone.utc).isoformat()
        try:
            with self.opener.open(request, timeout=min(10, remaining)) as response:
                status, headers = response.status, response.headers
        except HTTPError as response:
            status, headers = response.code, response.headers
            response.close()
        require(status == 402, 'Expected unauthenticated HTTP 402; received HTTP ' + str(status)
                + f' (method={method}, path={path})')
        require(time.monotonic() <= self.deadline, 'Payment observation deadline exceeded')
        require('110' not in headers.get('Warning', ''), 'Stale payment challenge rejected')
        return {'status': status, 'observed_at': observed, **parse_challenge(headers.get('WWW-Authenticate'))}


def runtime_binding(facts, spec):
    document = decode((facts / (spec['provider'] + '.json')).read_bytes())
    item = document['paths'][spec['path']]
    op = item.get(spec['method'].lower(), item.get('x-aisa-any'))
    require(isinstance(op, dict), 'Reviewed method missing from current Runtime')
    caps = op.get('x-aisa-capabilities', {})
    require(op.get('x-aisa-status') == 'enabled' and caps.get('mpp') is True
            and isinstance(caps.get('mpp_methods'), list)
            and spec['method'] in caps.get('mpp_methods', [])
            and op.get('x-aisa-pricing', {}).get('cost_contract') == 'fixed_success',
            'Runtime no longer enables the reviewed fixed payment method')
    require(op.get('x-aisa-upstream-path') == spec['target'], 'Reviewed upstream target changed')
    return {'target': spec['target'], 'revision': op['x-aisa-revision'],
            'pricing': op['x-aisa-pricing'], 'capabilities': caps, 'status': op['x-aisa-status']}


def semantics(bundle):
    value = copy.deepcopy(bundle)
    evidence = value['challenge_evidence']
    evidence.pop('runtime_snapshot', None)
    for row in evidence['operations']:
        for name in ('observed_at', 'expires', 'source_sha256'):
            row.pop(name, None)
    return canonical_json(value)


def collect(root, facts, scope, current_reader, challenge_reader, *, review_provenance=None):
    receipt, _ = acquired_input(facts)
    expected = decode((facts / 'current-before.json').read_bytes())
    before = decode(current_reader('/public/api-contract/current')[0])
    validate_current(before, receipt['artifact_revision'], receipt['compiler_revision'])
    require(canonical_json(before) == canonical_json(expected), 'Runtime changed before payment observations')
    require(bool(scope) and len({key(op) for op in scope}) == len(scope), 'Invalid reviewed payment scope')
    # Validate the entire scope before making even the first challenge request.
    sources, bindings = {}, {}
    for op in scope:
        require(set(op) == {'provider', 'method', 'path', 'target', 'source'}
                and re.fullmatch('[a-z0-9][a-z0-9_.-]*', op['provider'])
                and op['source'] == 'openapi/' + op['provider'] + '.json'
                and op['method'] in ('GET', 'POST') and op['provider'] != 'tikhub',
                'Invalid reviewed scope entry')
        bindings[key(op)] = runtime_binding(facts, op)
        if op['source'] not in sources:
            raw = local_file(root, op['source']).read_bytes()
            sources[op['source']] = (raw, decode(raw))
    contracts = {name: contract_binding(source, [op for op in scope if op['source'] == name])
                 for name, (_, source) in sources.items()}
    observations = []
    for op in scope:
        row = {name: op[name] for name in ('provider', 'method', 'path')}
        row.update(challenge_reader(op))
        row['source_sha256'] = digest(sources[op['source']][0])
        row['runtime_binding'] = bindings[key(op)]
        observations.append(row)
    after = decode(current_reader('/public/api-contract/current')[0])
    validate_current(after, receipt['artifact_revision'], receipt['compiler_revision'])
    require(canonical_json(before) == canonical_json(after), 'Runtime changed during payment observations')
    for name, (raw, _) in sources.items():
        require(local_file(root, name).read_bytes() == raw, 'Staged source changed during payment observations')
    bundle = {'version': 3, 'kind': 'reviewed-mpp-publication', 'allowlist': scope,
              'review_provenance': review_provenance or {},
              'challenge_evidence': {'version': 3, 'quote_source': 'runtime-unauthenticated-402',
                  'environment': 'production', 'server': ORIGIN,
                  'runtime_snapshot': {name: receipt[name] for name in RUNTIME_KEYS},
                  'fresh_before_and_after': True, 'operations': observations, 'source_contracts': contracts},
              'verification': 'Historical unauthenticated Runtime 402 observations; no plan-arithmetic, paid-execution or settlement claim. Obtain a fresh challenge before payment; its terms and expiry are authoritative.'}
    build_publication(root, bundle)
    return bundle


def refresh(root, facts, current_reader, challenge_reader, *, scope=None, review_provenance=None):
    evidence_path = root / 'discovery/payment-evidence.json'
    previous = decode(evidence_path.read_bytes())
    if scope is None:
        require(previous.get('version') == 3 and previous.get('kind') == 'reviewed-mpp-publication',
                'Initialize a reviewed Runtime payment scope first')
        scope = previous['allowlist']
        review_provenance = previous.get('review_provenance', {})
    bundle = collect(root, facts, scope, current_reader, challenge_reader, review_provenance=review_provenance)
    unchanged = previous.get('version') == 3 and semantics(previous) == semantics(bundle)
    if not unchanged:
        temporary = evidence_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(bundle, indent=2, ensure_ascii=True) + '\n')
        temporary.replace(evidence_path)
    return {'status': 'passed', 'publication_changed': not unchanged, 'observation': bundle}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--facts-dir', type=Path, required=True)
    parser.add_argument('--observation-report', type=Path, required=True)
    parser.add_argument('--scope', type=Path, help='Explicit reviewed bootstrap scope; the publisher never supplies this')
    parser.add_argument('--review-provenance', type=Path)
    args = parser.parse_args()
    deadline = time.monotonic() + 180
    try:
        result = refresh(args.root, args.facts_dir, PublicReader(ORIGIN, deadline), ChallengeReader(deadline),
                         scope=decode(args.scope.read_bytes()) if args.scope else None,
                         review_provenance=decode(args.review_provenance.read_bytes()) if args.review_provenance else None)
    except Exception as exc:
        # Do not persist an untrusted HTTP body, URL or arbitrary exception text.
        reason = failure_diagnostic(exc)
        args.observation_report.write_text(json.dumps({'status': 'failed', 'error_type': type(exc).__name__, 'reason': reason}) + '\n')
        parser.exit(1, 'Payment evidence refresh failed; published evidence preserved (' + reason + ')\n')
    args.observation_report.write_text(json.dumps(result, indent=2, ensure_ascii=True) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'observation'}))


if __name__ == '__main__':
    main()
