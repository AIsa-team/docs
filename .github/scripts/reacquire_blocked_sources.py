"""Compare overdue official inputs without modifying mirrors or activating receipts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--diagnostic', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / 'scripts'))
    from import_upstream import import_source
    from source_governance import POLICY_FIELDS, acquisition_receipt, policy_errors, receipt_key
    from upstream_semantics import compare_contracts

    diagnostic = json.loads(args.diagnostic.read_text())
    rows = [row for row in diagnostic['sources']
            if row['policy'] == 'automatic' and row['freshness'] == 'overdue']

    def observe(row):
        name = row['name']
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*\.json', name):
            raise ValueError('Invalid diagnostic source member')
        mirror = args.repo / 'openapi/upstream' / name
        previous = json.loads(mirror.read_text())
        source = previous['info']['x-aisa-source']
        if policy_errors(source) or source['content_hash'] != row['source_hash']:
            raise ValueError('Diagnostic source binding changed')
        result = {'name': name, 'expected_source_hash': source['content_hash']}
        try:
            fetched = import_source(Path(name).stem, source['url'])
            actual = fetched['info']['x-aisa-source']['content_hash']
            checked_at = datetime.now(timezone.utc)
            result.update(observed_source_hash=actual, checked_at=checked_at.isoformat(),
                          status='source_unchanged' if actual == source['content_hash'] else 'content_changed')
            if actual == source['content_hash']:
                # This is a real acquisition observation, kept only in the
                # diagnostic artifact. No committed receipt or clock changes.
                result['receipt_key'] = receipt_key(source)
                result['observed_receipt'] = acquisition_receipt(source, checked_at)
            else:
                # Keep each source's reviewed maintenance policy. Acquisition
                # does not imply compatibility or approval for activation.
                acquired = fetched['info']['x-aisa-source']
                for key in (*POLICY_FIELDS, 'policy_revision'):
                    if key in source:
                        acquired[key] = source[key]
                result['receipt_key'] = receipt_key(acquired)
                result['observed_receipt'] = acquisition_receipt(acquired, checked_at)
                output = args.output.parent / 'reacquired-public-sources'
                output.mkdir(exist_ok=True)
                raw = (json.dumps(fetched, indent=2, ensure_ascii=False) + '\n').encode()
                (output / name).write_bytes(raw)
                import hashlib
                result['mirror_bytes_sha256'] = hashlib.sha256(raw).hexdigest()
                try:
                    comparison = compare_contracts(previous, fetched)
                    result['declaration_comparison'] = {
                        'status': comparison['status'], 'compatibility': comparison['compatibility'],
                        'counts': {key: len(comparison[key]) for key in ('added', 'removed', 'changed', 'uncertain')},
                        'added': [row['operation'] for row in comparison['added'][:100]],
                        'removed': [row['operation'] for row in comparison['removed'][:100]],
                        'changed': [{'operation': row['operation'],
                                     'fields': [{key: change[key] for key in ('field', 'change')}
                                                for change in row['changes'][:30]]}
                                    for row in comparison['changed'][:100]],
                        'uncertain_count': len(comparison['uncertain'])}
                except Exception as error:
                    result['declaration_comparison'] = {'status': 'comparison_failed',
                                                       'exception_type': type(error).__name__}
        except Exception as error:
            result.update(status='fetch_failed', exception_type=type(error).__name__)
        print(name + ': ' + result['status'], flush=True)
        if 'declaration_comparison' in result:
            print(name + ' declaration comparison: ' + json.dumps(result['declaration_comparison'], sort_keys=True), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=4) as executor:
        observations = list(executor.map(observe, rows))
    report = {'scope': 'official_reacquisition_diagnostic_only', 'mirrors_modified': False,
              'receipts_activated': False, 'sources': observations,
              'counts': {status: sum(row['status'] == status for row in observations)
                         for status in ('source_unchanged', 'content_changed', 'fetch_failed')}}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report['counts'], sort_keys=True))


if __name__ == '__main__':
    main()
