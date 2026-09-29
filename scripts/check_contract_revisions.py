#!/usr/bin/env python3
"""Compare public contract revisions. No provider calls or credentials required."""
import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
import yaml


def compare(documents, runtime, website, mcp, router):
    errors = []
    index = {provider['id']: provider.get('facts_hash') for provider in runtime.get('providers', [])}
    web = website.get('x-aisa-document', {}).get('providers', {})
    mcp_hashes = mcp.get('documentHashes', {})
    router_hashes = router.get('provider_document_hashes', {})
    for provider, metadata in documents.items():
        expected = metadata.get('document_hash')
        if not expected:
            continue  # Legacy is explicitly not a verified runtime projection.
        for surface, actual in [('website', web.get(provider, {}).get('document_hash')),
                                ('mcp', mcp_hashes.get(provider)), ('tool-router', router_hashes.get(provider))]:
            if actual != expected:
                errors.append(f'{provider}:{surface}:document_hash_mismatch')
        catalogs = metadata.get('catalogs') or {provider: {'x-aisa-document': {'facts_hash': metadata.get('facts_hash')}}}
        for catalog, info in catalogs.items():
            facts = info.get('x-aisa-document', {}).get('facts_hash')
            if not facts or index.get(catalog) != facts:
                errors.append(f'{provider}:{catalog}:facts_hash_mismatch')
    return sorted(set(errors))


def read_public(url):
    with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=20) as response:
        return json.load(response)


def update_state(errors, previous):
    counts = previous.get('consecutive', {})
    return {'checked_at': int(time.time()), 'consecutive': {error: counts.get(error, 0) + 1 for error in errors}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--state', type=Path, default=Path('.cache/contract-revisions/state.json'))
    args = parser.parse_args()
    spec = yaml.safe_load((args.root / 'openapi.yaml').read_text())
    documents = spec.get('info', {}).get('x-aisa-document', {}).get('providers', {})
    targets = {
        'runtime': 'https://api.aisa.one/info/openapi.json',
        'website': 'https://aisa.one/.well-known/agent-card.json',
        'mcp': 'https://mcp.aisa.one/.well-known/mcp.json',
        'router': 'https://tools.aisa.one/.well-known/catalog.json',
    }
    results, failures = {}, []
    for key, url in targets.items():
        try:
            results[key] = read_public(url)
        except Exception as exc:
            failures.append(f'{key}:unavailable:{type(exc).__name__}')
    if not failures:
        failures = compare(documents, **results)
    previous = json.loads(args.state.read_text()) if args.state.exists() else {}
    state = update_state(failures, previous)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({'verified_providers': sum(bool(p.get('document_hash')) for p in documents.values()),
                      'legacy_providers': sum(not bool(p.get('document_hash')) for p in documents.values()),
                      'mismatches': state['consecutive']}, indent=2))
    return 1 if any(count >= 2 for count in state['consecutive'].values()) else 0

if __name__ == '__main__':
    raise SystemExit(main())
