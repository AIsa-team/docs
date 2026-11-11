#!/usr/bin/env python3
"""Inventory ambiguous unit-price prose in one consolidated public contract.

Counts describe documentation, not incorrect charges. Read the consolidated
contract once: scanning it together with provider shards doubles the counts.
No network, database access, or contract mutation is performed.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}


def audit(document):
    rows = []
    total = 0
    named_rates = 0
    for path, item in sorted(document.get('paths', {}).items()):
        for method, operation in sorted(item.items()):
            if method not in METHODS or not isinstance(operation, dict):
                continue
            total += 1
            pricing = operation.get('x-aisa-pricing', {})
            if pricing.get('unit') != 'provider_credit':
                named_rates += int('unit_rate_usd' in pricing)
                continue
            description = operation.get('description', '')
            old_label = ('Declared unit rate:' in description or '声明的单位费率：' in description)
            rows.append({'method': method.upper(), 'path': path, 'operation_id': operation.get('operationId'),
                         'catalog': operation.get('x-aisa-catalog-id'), 'status': operation.get('x-aisa-status'),
                         'unit_rate_usd': pricing.get('unit_rate_usd'),
                         'evidence_source': pricing.get('evidence_source'),
                         'customer_pricing': pricing.get('customer_pricing'),
                         'legacy_unit_price_prose': old_label,
                         'docs_url': operation.get('x-aisa-docs-url')})
    legacy = [row for row in rows if row['legacy_unit_price_prose']]
    micro = [row for row in legacy if row['unit_rate_usd'] == .000001]
    counts = lambda group, key: dict(sorted(Counter(str(row[key]) for row in group).items()))
    return {'operations': total, 'generic_cost_unit_operations': len(rows),
            'named_unit_rate_operations': named_rates,
            'legacy_generic_unit_price_operations': len(legacy),
            'legacy_micro_unit_price_operations': len(micro),
            'legacy_micro_catalogs': len({row['catalog'] for row in micro}),
            'legacy_micro_by_evidence': counts(micro, 'evidence_source'),
            'legacy_micro_by_catalog': counts(micro, 'catalog'),
            'generic_by_rate': counts(rows, 'unit_rate_usd')}, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('openapi/openapi.json'))
    parser.add_argument('--inventory', type=Path, help='Write the complete generic-unit operation inventory as JSON')
    args = parser.parse_args()
    raw = args.input.read_bytes()
    report, rows = audit(json.loads(raw))
    report['input_sha256'] = hashlib.sha256(raw).hexdigest()
    if args.inventory:
        args.inventory.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
