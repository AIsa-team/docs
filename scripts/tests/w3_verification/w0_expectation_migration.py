"""One reviewed conservative diagnostic change to the immutable W0 oracle.

This is test-only expected behavior for old facts without forwarding hints.
It cannot approve current source debt, waive production gates, or rewrite W0.
"""
import hashlib
import gzip
import json
from pathlib import Path

ARCHIVE_SHA256 = 'f2b35c81df49b3a31053f3b4e8978778e52556d2d36536c23f4d7f28f8e0f02f'
FIXTURE_SHA256 = '93e414582b7f99df0997e6a72b64c4ca6b27c3076c55b3e746a509b640e56b2e'
FIXTURE = Path(__file__).with_name('strict-forwarding-expectation-migration.json')
SCOPE = 'closed_frozen_W0_stricter_forwarding_diagnostic_expectation_migration_only_not_production_debt_approval'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def coverage_rows(value):
    result = {}
    for provider, entries in value['providers'].items():
        for row in entries:
            key = (provider, row.get('path'), row.get('method'), row.get('operation_id'), row['status'])
            if key in result:
                raise ValueError('Duplicate W0 coverage identity')
            result[key] = row
    return result


def load_migration():
    raw = FIXTURE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError('Reviewed W0 diagnostic migration hash differs')
    value = json.loads(raw)
    if (set(value) != {'schema_version', 'scope', 'archive_sha256', 'previous_coverage_sha256',
                       'input_sha256', 'provider_pending', 'removed_coverage', 'added_coverage',
                       'candidate_coverage_canonical_sha256', 'candidate_pending_canonical_sha256',
                       'policy_fixture_sha256', 'diagnostic_evidence_sha256'} or
            value['schema_version'] != 1 or value['scope'] != SCOPE or
            value['archive_sha256'] != ARCHIVE_SHA256):
        raise ValueError('Invalid closed W0 diagnostic migration')
    return value


def load_diagnostic_evidence(migration):
    raw = FIXTURE.with_name('strict-forwarding-diagnostic-evidence.json.gz').read_bytes()
    if hashlib.sha256(raw).hexdigest() != migration['diagnostic_evidence_sha256']:
        raise ValueError('Frozen stricter diagnostic evidence differs')
    return json.loads(gzip.decompress(raw))


def verify_transition(previous, current, pending, migration):
    """Match every old/new row, its source proof, and all nine root failures."""
    before, after = coverage_rows(previous), coverage_rows(current)
    removed = [{'provider': key[0], 'row': before[key]} for key in sorted(before.keys() - after.keys())]
    added = [{'provider': key[0], 'row': after[key]} for key in sorted(after.keys() - before.keys())]
    if (canonical(removed) != canonical(migration['removed_coverage']) or
            canonical(added) != canonical(migration['added_coverage'])):
        raise ValueError('Unreviewed W0 coverage transition')
    # No reason/source-binding drift is allowed in any changed row, including
    # provider-wide retained rows whose own operation was otherwise composable.
    for selected in migration['added_coverage']:
        row = selected['row']
        key = (selected['provider'], row.get('path'), row.get('method'), row.get('operation_id'), row['status'])
        if canonical(after[key]) != canonical(row) or row['status'] != 'pending':
            raise ValueError('W0 conservative pending proof differs')
    for provider, expected in migration['provider_pending'].items():
        if canonical(pending['providers'].get(provider)) != canonical(expected):
            raise ValueError('W0 root forwarding failure or retention differs')
    actual_retained = {provider for provider, entries in pending['providers'].items()
                       if any(str(row.get('reason')).startswith('published identity changed or disappeared:')
                              for row in entries)}
    if actual_retained != set(migration['provider_pending']):
        raise ValueError('Unreviewed W0 retained provider')
    # The original harness compared identity/status tuples. Also close the
    # entire current coverage and pending graphs, including unchanged tuples'
    # new binding proofs and all non-retained providers' previous debt.
    if (hashlib.sha256(canonical(current).encode()).hexdigest() != migration['candidate_coverage_canonical_sha256'] or
            hashlib.sha256(canonical(pending).encode()).hexdigest() != migration['candidate_pending_canonical_sha256']):
        raise ValueError('Unreviewed complete W0 coverage or pending graph')
    return {'scope': SCOPE, 'fixture_sha256': FIXTURE_SHA256, 'status': 'passed',
            'removed_rows': len(removed), 'added_rows': len(added),
            'retained_providers': sorted(actual_retained)}


def verify_migration(expected, candidate, coverage, input_root, policy_fixture=None):
    migration = load_migration()
    previous_raw = (expected / 'openapi/coverage.json').read_bytes()
    if hashlib.sha256(previous_raw).hexdigest() != migration['previous_coverage_sha256']:
        raise ValueError('Original immutable W0 oracle differs')
    actual = {str(path.relative_to(input_root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for directory in ('facts', 'openapi/upstream')
              for path in sorted((input_root / directory).glob('*.json'))}
    if actual != migration['input_sha256']:
        raise ValueError('Immutable W0 source/facts bindings differ')
    policy_fixture = policy_fixture or FIXTURE.with_name('source-policy.fixture.json')
    if hashlib.sha256(policy_fixture.read_bytes()).hexdigest() != migration['policy_fixture_sha256']:
        raise ValueError('W0 diagnostic policy fixture differs')
    pending = json.loads((candidate / 'openapi/pending.json').read_text())
    return verify_transition(json.loads(previous_raw), coverage, pending, migration)
