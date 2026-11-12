"""Inventory all published tool prose; produce review candidates, never mutate contracts."""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess

METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}
SKIP = {'openapi', 'pending', 'coverage', 'coverage-sources', 'nav-groups'}
PRICE = re.compile(r'<!-- aisa-pricing:start -->.*?<!-- aisa-pricing:end -->', re.S)

def operations(document):
    for path, item in document.get('paths', {}).items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation

def inventory(root):
    rows, identities = [], set()
    for source in sorted((root / 'openapi').glob('*.json')):
        if source.stem in SKIP:
            continue
        raw = source.read_bytes()
        document = json.loads(raw)
        for path, method, operation in operations(document):
            identity = (source.stem, path, method)
            if identity in identities:
                raise ValueError(f'Duplicate operation: {identity}')
            identities.add(identity)
            summary = operation.get('summary', '')
            description = operation.get('description', '')
            prose = PRICE.sub('', description).strip()
            binding = operation.get('x-aisa-runtime-operation') or {}
            resource = source.stem in {'aisa-social', 'aisa-commerce'}
            flags = []
            if not summary.strip(): flags.append('missing_summary')
            if '_' in summary: flags.append('machine_style_summary')
            if not prose: flags.append('missing_nonpricing_description')
            if len(description) > 4000: flags.append('long_description_review_truncation')
            if re.search(r'\bdeprecated\b', prose, re.I) and not operation.get('deprecated'):
                flags.append('deprecation_text_review_only')
            # An existing Purpose is evidence for a draft title, not semantic approval.
            purpose = re.search(r'###\s*Purpose\s*:\s*\n\s*-\s*([^\n]+)', prose)
            candidate, evidence = '', ''
            if 'machine_style_summary' in flags and purpose:
                lead = prose.splitlines()[0].strip().rstrip('.')
                purpose_text = purpose.group(1).strip()
                if len(lead) <= 65 and len(purpose_text) <= 140:
                    candidate = f'{lead}: {purpose_text}'
                    evidence = purpose.group(0).strip()
            rows.append({
                'provider': source.stem, 'operation_id': operation.get('operationId', ''),
                'method': method.upper(), 'path': path,
                'source_file': str(source.relative_to(root)),
                'source_sha256': hashlib.sha256(raw).hexdigest(),
                'runtime_operation_id': binding.get('operation_id', ''),
                'runtime_method': binding.get('method', ''), 'runtime_path': binding.get('path', ''),
                'contract_state': operation.get('x-aisa-contract-state', ''),
                'summary_owner_family': ('AIsaServices code: verify definition' if resource else
                    'AIsaServices Runtime metadata: verify endpoint' if binding else 'unresolved'),
                'description_owner_family': ('AIsaServices code: verify definition' if resource else
                    'Runtime description or Docs mirror: raw facts required' if binding else 'unresolved'),
                'summary_before': summary, 'description_before': description,
                'quality_flags': '|'.join(flags),
                'summary_candidate': candidate, 'candidate_evidence': evidence,
                'review_status': 'candidate_needs_review' if candidate else 'not_reviewed',
                'changed': False,
            })
    return rows

def write_report(root, output):
    rows = inventory(root)
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'all-tools.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    providers = {}
    for row in rows:
        counts = providers.setdefault(row['provider'], collections.Counter())
        counts['tools'] += 1
        for flag in filter(None, row['quality_flags'].split('|')): counts[flag] += 1
        counts['summary_candidates'] += bool(row['summary_candidate'])
    report = {
        'scope': 'checked-out published provider contracts; not live Router availability',
        'docs_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        'tools': len(rows), 'unique_operation_ids': len({r['operation_id'] for r in rows}),
        'providers': len(providers), 'runtime_bound': sum(bool(r['runtime_operation_id']) for r in rows),
        'semantically_reviewed': 0, 'modified_contracts': 0,
        'summary_candidates': sum(bool(r['summary_candidate']) for r in rows),
        'quality_flags': dict(sum((collections.Counter(filter(None, r['quality_flags'].split('|'))) for r in rows), collections.Counter())),
        'by_provider': providers,
    }
    (output / 'scope.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return {k: v for k, v in report.items() if k != 'by_provider'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(write_report(args.root, args.output), ensure_ascii=False, indent=2))
