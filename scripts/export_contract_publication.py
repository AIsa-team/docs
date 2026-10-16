#!/usr/bin/env python3
"""Export the existing formal PASS and its exact graph as a same-commit C pointer."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import os
import subprocess

from fetch_runtime_release import acquire, decode, require, sha, HEX64, HEX40
from publication_surface import publication_hashes
from deferred_definitions import validate_report_deferrals
from source_governance import FAILED, SCOPE_METHOD, source_report
from sales_catalog_projection import SALES_CATALOG_PATH
from formal_assessment import CANONICAL, COMPOSED, validate_formal_assessment

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
    require(canonical(receipt.get('canonical_validation')) == canonical(rebuilt.get('canonical_validation')),
            'Canonical acquisition validation differs')
    for key in (*RUNTIME_KEYS, 'manifest_files', 'inventory_endpoint_count', 'selected_endpoint_count',
                'provider_count', 'category_sha256', 'category_content_sha256', 'category_ignored_volatile_fields'):
        require(receipt.get(key) == rebuilt[key], 'Saved acquisition receipt mismatch')
    for key in ('started_at', 'completed_at'):
        require(datetime.fromisoformat(receipt[key]).tzinfo is not None, 'Acquisition timestamp lacks timezone')
    require(HEX64.fullmatch(str(receipt.get('category_after_sha256', ''))), 'Invalid category observation hash')
    return receipt, raw


def source_scope_owners(report):
    """Validated provider attribution; an absent scope means every source is global."""
    governance = report.get('source_governance', {})
    scope = governance.get('source_scope')
    if scope is None:
        require('scoped_failures' not in governance, 'Scoped failures without source scope')
        return None
    providers = report.get('providers', {})
    require(isinstance(scope, dict) and scope.get('schema_version') == 1 and scope.get('method') == SCOPE_METHOD
            and isinstance(scope.get('sources'), dict) and set(scope['sources']) <= set(governance['sources'])
            and isinstance(providers, dict), 'Invalid source scope')
    for owners in scope['sources'].values():
        require(isinstance(owners, list) and all(isinstance(p, str) and p in providers for p in owners)
                and owners == sorted(set(owners)), 'Invalid source scope')
    return {name: owners for name, owners in scope['sources'].items() if owners}


def source_expiry(report, now):
    """Return (global expiry, provider expiries or None for the legacy shape).

    Global sources must be fresh and unexpired. A provider-scoped source may be
    overdue/fetch_failed or already due; it only shortens its providers' expiry
    to its own existing due time, never extended and never past the global one.
    """
    governance = report.get('source_governance', {})
    require(governance.get('status') == 'passed' and governance.get('sources'), 'Source maintenance is not passed')
    checked = datetime.fromisoformat(governance['checked_at'])
    require(checked.tzinfo is not None and checked <= now, 'Source assessment time is invalid')
    owners = source_scope_owners(report)
    due, scoped_due, failures = [], {}, {}
    for name, source in governance['sources'].items():
        scoped = (owners or {}).get(name)
        require(not source.get('policy_errors'), 'Source is not fresh')
        if scoped:
            require(source.get('freshness') in {'fresh', *FAILED}, 'Source is not fresh')
            if source['freshness'] != 'fresh':
                for provider in scoped:
                    failures.setdefault(provider, []).append(name)
        else:
            require(source.get('freshness') == 'fresh', 'Source is not fresh')
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
                require(value.tzinfo is not None, 'Source authorization expiry lacks timezone')
                if scoped:
                    for provider in scoped:
                        scoped_due.setdefault(provider, []).append(value)
                else:
                    require(value > now, 'Source authorization expired')
                    due.append(value)
    require(due, 'No global source authorization')
    expiry = min(due)
    if owners is None:
        return expiry.isoformat(), None
    require(governance.get('scoped_failures') == {p: sorted(names) for p, names in failures.items()},
            'Scoped source failures differ')
    return expiry.isoformat(), {provider: min([expiry, *scoped_due.get(provider, [])]).isoformat()
                                for provider in sorted(report.get('providers', {}))}


def prepare(root, facts, report_raw, now=None, source_receipts=None):
    now = now or datetime.now(timezone.utc)
    report = decode(report_raw)
    require(report.get('status') == 'passed', 'Formal readiness did not pass')
    require(report.get('evaluation') in {COMPOSED, CANONICAL},
            'Unsupported formal assessment scope')
    mode = report['evaluation']
    for key in (('composed_candidate' if mode == COMPOSED else 'canonical_runtime_import'),
                'publication_surfaces', 'payment_discovery'):
        require(report.get(key, {}).get('status') == 'passed', 'Formal subgate did not pass')
    validate_formal_assessment(report)
    if mode == CANONICAL:
        from canonical_formal import replay_formal_canonical
        replay_formal_canonical(root, facts, report, source_receipts=source_receipts)
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
    validate_formal_assessment(report, receipt)
    require(report.get('runtime_acquisition_sha256') == sha(receipt_raw), 'Formal assessment used different Runtime inputs')
    runtime = {key: receipt[key] for key in RUNTIME_KEYS}
    require(report.get('runtime') == runtime, 'Formal Runtime identity mismatch')
    sales_raw = (root / SALES_CATALOG_PATH).read_bytes()
    sales = decode(sales_raw)
    require(type(sales.get('schema_version')) is int and sales['schema_version'] == 1 and sales.get('openapi_sha256') == hashes.get('openapi.yaml') and
            hashes.get(SALES_CATALOG_PATH) == sha(sales_raw), 'Sales projection is outside the assessed graph')
    core = {'schema_version': 1, 'runtime': runtime, 'files_sha256': hashes}
    expiry, provider_expiry = source_expiry(report, now)
    current = {**core, 'status': 'passed', 'contract_release': sha(canonical(core)),
               'openapi': {'path': 'openapi.yaml', 'sha256': hashes['openapi.yaml']},
               'sales_catalog': {'path': SALES_CATALOG_PATH, 'sha256': hashes[SALES_CATALOG_PATH]},
               'formal_readiness': {'path': PUBLICATION + 'formal-contract-readiness.json', 'sha256': sha(report_raw)},
               'runtime_acquisition': {'path': PUBLICATION + 'runtime-acquisition.json', 'sha256': sha(receipt_raw)},
               'source_authorization_expires_at': expiry}
    if provider_expiry is not None:
        current['provider_authorization_expires_at'] = provider_expiry
    return {'formal-contract-readiness.json': report_raw, 'runtime-acquisition.json': receipt_raw,
            'current.json': json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False).encode() + b'\n'}


def retained_publication(root, destination, files, now):
    """Keep an equivalent authorized receipt, never reuse it instead of prepare.

    Observations belong in the current workflow artifact. Updating their clocks
    alone must not invalidate consumers' exact-main adoption guards. Unknown
    fields are compared too; only these explicit observation fields may differ.
    """
    try:
        paths = {name: destination / name for name in files}
        if any(not path.is_file() or path.is_symlink() for path in paths.values()):
            return None
        previous = {name: path.read_bytes() for name, path in paths.items()}
        old_current, new_current = (decode(packet['current.json']) for packet in (previous, files))
        old_report, new_report = (decode(packet['formal-contract-readiness.json']) for packet in (previous, files))
        old_receipt, new_receipt = (decode(packet['runtime-acquisition.json']) for packet in (previous, files))
        # Reconstruct every pointer field with old receipt bytes. The new pointer
        # is already fully validated; this also proves C, inventory and expiry.
        expected = decode(files['current.json'])
        expected['formal_readiness']['sha256'] = sha(previous['formal-contract-readiness.json'])
        expected['runtime_acquisition']['sha256'] = sha(previous['runtime-acquisition.json'])
        require(canonical(old_current) == canonical(expected), 'Existing publication pointer differs')
        require(source_expiry(old_report, now) == (new_current['source_authorization_expires_at'],
                                                   new_current.get('provider_authorization_expires_at')),
                'Existing source authorization differs or expired')
        require(old_report['runtime_acquisition_sha256'] == sha(previous['runtime-acquisition.json']),
                'Existing report acquisition binding differs')

        old_base = old_report['publication_artifact'].get('published_ref')
        new_base = new_report['publication_artifact'].get('published_ref')
        if old_base is not None or new_base is not None:
            require(HEX40.fullmatch(str(old_base)) and HEX40.fullmatch(str(new_base)),
                    'Invalid published assessment base')
            ancestry = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', old_base, new_base],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            require(ancestry.returncode == 0, 'Previous assessment base is not in current Git lineage')

        def report_semantics(report):
            value = decode(canonical(report))
            value.pop('runtime_acquisition_sha256')
            governance = value['source_governance']
            governance.pop('checked_at')
            for source in governance['sources'].values():
                source.pop('checked_at')
            # The previous assessed base naturally differs after publishing its
            # generated commit. This is Git provenance, not source authorization.
            artifact = value['publication_artifact']
            if 'published_ref' in artifact:
                require(HEX40.fullmatch(str(artifact['published_ref'])), 'Invalid published assessment base')
                artifact['published_ref'] = '<verified-git-ancestor>'
            return value

        require(canonical(report_semantics(old_report)) == canonical(report_semantics(new_report)),
                'Existing assessment authority differs')

        def acquisition_semantics(receipt):
            value = decode(canonical(receipt))
            start, end = (datetime.fromisoformat(value.pop(key)) for key in ('started_at', 'completed_at'))
            require(start.tzinfo is not None and end.tzinfo is not None and start <= end <= now,
                    'Invalid acquisition observation chronology')
            for key in ('category_sha256', 'category_after_sha256'):
                require(HEX64.fullmatch(str(value.pop(key))), 'Invalid category observation hash')
            return value

        # Full immutable files, Runtime identity, coverage and semantic category
        # digest must be identical; only cache-construction raw bytes may differ.
        require(canonical(acquisition_semantics(old_receipt)) == canonical(acquisition_semantics(new_receipt)),
                'Existing acquisition semantics differ')
        return old_current
    except (ValueError, KeyError, TypeError, OSError, AttributeError, subprocess.TimeoutExpired):
        # A damaged/missing/expired old bundle cannot authorize reuse. The caller
        # may publish the newly validated bundle, never relabel old bytes passed.
        return None


def export(root, facts, report, source_receipts=None, *, now=None):
    # Finish every validation before touching or reusing last-good metadata.
    now = now or datetime.now(timezone.utc)
    files = prepare(root, facts, report.read_bytes(), now, source_receipts)
    destination = root / PUBLICATION
    retained = retained_publication(root, destination, files, now)
    if retained is not None:
        return retained
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
