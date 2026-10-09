#!/usr/bin/env python3
"""Export the existing formal PASS and its exact graph as a same-commit C pointer."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import os

from fetch_runtime_release import acquire, decode, require, sha, HEX64
from publication_surface import publication_hashes
from deferred_definitions import validate_report_deferrals
from source_governance import source_report
from sales_catalog_projection import SALES_CATALOG_PATH

RUNTIME_KEYS = ('artifact_revision', 'source_digest', 'compiler_revision', 'generation')
PUBLICATION = 'docs/publication/'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def acquired_input(facts):
    """Revalidate saved acquisition bytes; flat composer inputs must be identical."""
    raw = (facts / 'acquisition-receipt.json').read_bytes()
    receipt = decode(raw)
    require(receipt.get('fresh_before_and_after') is True, 'Acquisition was not fresh')
    revision, compiler = receipt['artifact_revision'], receipt['compiler_revision']
    currents = iter(((facts / 'current-before.json').read_bytes(), (facts / 'current-after.json').read_bytes()))
    def reader(path):
        if path == '/public/api-contract/current':
            return next(currents), {}
        if path == '/info/apis/category':
            return (facts / 'category.json').read_bytes(), {}
        prefix = '/public/api-contract/releases/' + revision + '/'
        require(path.startswith(prefix), 'Unexpected acquisition path')
        name = path[len(prefix):]
        content = (facts / name).read_bytes()
        if name.startswith('providers/'):
            require((facts / Path(name).name).read_bytes() == content, 'Flat Runtime facts changed')
        return content, {'etag': '"' + sha(content) + '"'}
    rebuilt = acquire(revision, compiler, reader)[-1]
    for key in (*RUNTIME_KEYS, 'manifest_files', 'inventory_endpoint_count', 'selected_endpoint_count',
                'provider_count', 'category_sha256', 'category_content_sha256', 'category_ignored_volatile_fields'):
        require(receipt.get(key) == rebuilt[key], 'Saved acquisition receipt mismatch')
    for key in ('started_at', 'completed_at'):
        require(datetime.fromisoformat(receipt[key]).tzinfo is not None, 'Acquisition timestamp lacks timezone')
    require(HEX64.fullmatch(str(receipt.get('category_after_sha256', ''))), 'Invalid category observation hash')
    return receipt, raw


def source_expiry(report, now):
    governance = report.get('source_governance', {})
    require(governance.get('status') == 'passed' and governance.get('sources'), 'Source maintenance is not passed')
    checked = datetime.fromisoformat(governance['checked_at'])
    require(checked.tzinfo is not None and checked <= now, 'Source assessment time is invalid')
    due = []
    for source in governance['sources'].values():
        require(source.get('freshness') == 'fresh' and not source.get('policy_errors'), 'Source is not fresh')
        require(source.get('review_due_at'), 'Source review expiry missing')
        observed = datetime.fromisoformat(source['checked_at'])
        reviewed = datetime.fromisoformat(source['last_successful_review_at'])
        require(observed.tzinfo is not None and reviewed.tzinfo is not None and
                reviewed <= observed == checked <= now, 'Source review chronology invalid')
        if source.get('policy') == 'automatic':
            require(source.get('next_acquisition_due_at'), 'Automatic acquisition expiry missing')
        for key in ('review_due_at', 'next_acquisition_due_at'):
            if source.get(key):
                value = datetime.fromisoformat(source[key])
                require(value.tzinfo is not None and value > now, 'Source authorization expired')
                due.append(value)
    return min(due).isoformat()


def prepare(root, facts, report_raw, now=None, source_receipts=None):
    now = now or datetime.now(timezone.utc)
    report = decode(report_raw)
    require(report.get('status') == 'passed', 'Formal readiness did not pass')
    require(report.get('evaluation') == 'actual_publication_graph_and_offline_composed_candidate',
            'Unsupported formal assessment scope')
    for key in ('composed_candidate', 'publication_surfaces'):
        require(report.get(key, {}).get('status') == 'passed', 'Formal subgate did not pass')
    for scope in (report, report['composed_candidate']):
        require(not scope.get('global_errors') and not scope.get('missing_inputs') and
                not scope.get('blocked_providers'), 'Formal readiness contains blockers')
    validate_report_deferrals(root, report)
    hashes = publication_hashes(root)
    artifact = report.get('publication_artifact', {})
    require(hashes and artifact.get('files_sha256') == hashes and
            artifact.get('openapi_sha256') == hashes.get('openapi.yaml'), 'Assessed publication graph changed')
    governance = report.get('source_governance', {})
    saved = decode((source_receipts or root / '.cache/source-reviews.json').read_bytes())
    checked = datetime.fromisoformat(governance['checked_at'])
    require(checked.tzinfo is not None and checked <= now, 'Source assessment time is invalid')
    reproduced = source_report(root, saved.get('receipts', {}), checked_at=checked, attempts=saved.get('attempts', {}))
    require(reproduced == governance, 'Formal source governance cannot be reproduced')
    sources = report.get('source_governance', {}).get('sources', {})
    metadata = {}
    for name, source in sources.items():
        require(isinstance(name, str) and '/' not in name and name.endswith('.json'), 'Invalid source filename')
        relative = 'openapi/upstream/' + name
        require(relative in hashes, 'Source is outside publication graph')
        actual = decode((root / relative).read_bytes())['info']['x-aisa-source']
        metadata[name] = {key: actual[key] for key in ('content_hash', 'policy_revision', 'refresh_policy')}
        require(source.get('source_hash') == actual['content_hash'] and
                source.get('policy_revision') == actual['policy_revision'] and
                source.get('policy') == actual['refresh_policy'], 'Source authority metadata changed')
    require(artifact.get('source_metadata') == metadata and
            artifact.get('source_hashes') == {name: row['content_hash'] for name, row in metadata.items()},
            'Formal source metadata mismatch')
    receipt, receipt_raw = acquired_input(facts)
    require(report.get('runtime_acquisition_sha256') == sha(receipt_raw), 'Formal assessment used different Runtime inputs')
    runtime = {key: receipt[key] for key in RUNTIME_KEYS}
    require(report.get('runtime') == runtime, 'Formal Runtime identity mismatch')
    sales_raw = (root / SALES_CATALOG_PATH).read_bytes()
    sales = decode(sales_raw)
    require(type(sales.get('schema_version')) is int and sales['schema_version'] == 1 and sales.get('openapi_sha256') == hashes.get('openapi.yaml') and
            hashes.get(SALES_CATALOG_PATH) == sha(sales_raw), 'Sales projection is outside the assessed graph')
    core = {'schema_version': 1, 'runtime': runtime, 'files_sha256': hashes}
    current = {**core, 'status': 'passed', 'contract_release': sha(canonical(core)),
               'openapi': {'path': 'openapi.yaml', 'sha256': hashes['openapi.yaml']},
               'sales_catalog': {'path': SALES_CATALOG_PATH, 'sha256': hashes[SALES_CATALOG_PATH]},
               'formal_readiness': {'path': PUBLICATION + 'formal-contract-readiness.json', 'sha256': sha(report_raw)},
               'runtime_acquisition': {'path': PUBLICATION + 'runtime-acquisition.json', 'sha256': sha(receipt_raw)},
               'source_authorization_expires_at': source_expiry(report, now)}
    return {'formal-contract-readiness.json': report_raw, 'runtime-acquisition.json': receipt_raw,
            'current.json': json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False).encode() + b'\n'}


def export(root, facts, report, source_receipts=None):
    # Finish every validation before touching last-good publication metadata.
    files = prepare(root, facts, report.read_bytes(), source_receipts=source_receipts)
    destination = root / PUBLICATION
    destination.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temporary:
            temporary.write(raw)
            temporary_path = temporary.name
        os.replace(temporary_path, destination / name)
    # These files are published together by one guarded Git commit, never served
    # out of the mutable workspace. C excludes its own receipt/pointer bytes.
    return decode(files['current.json'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--facts-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-receipts', type=Path, help='Same attributed receipts used by formal assessment; defaults to workflow cache')
    args = parser.parse_args()
    current = export(args.root, args.facts_dir, args.report, args.source_receipts)
    print(json.dumps({'contract_release': current['contract_release'], 'status': current['status']}))


if __name__ == '__main__':
    main()
