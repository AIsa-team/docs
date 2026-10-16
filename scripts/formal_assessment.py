"""Exact formal report shapes shared by export and historical origin checks.

These checks validate authenticated producer declarations, not live API or Git
authorization. The canonical exporter separately replays the complete input and
projection gate. Historical consumers must never renew source clocks from live
Runtime state.
"""
import re

from fetch_runtime_release import require
from schema_input_bundle import canonical

COMPOSED = 'actual_publication_graph_and_offline_composed_candidate'
CANONICAL = 'actual_publication_graph_and_runtime_canonical'
FORMAL_SCOPE = 'formal_publication_graph_and_runtime_canonical'
IMPORT_SCOPE = 'exact_runtime_native_aggregate_bytes_and_independent_metadata_projection'
INPUT_SCOPE = 'canonical_build_and_schema_inputs_only_not_publication_or_current_source_authorization'
ARTIFACT_SCOPE = 'formal producer artifact declarations and source maintenance; no execution'
INPUT_KEYS = {'protocol_version', 'bundle_manifest_sha256', 'docs_ref',
              'composer_revision', 'source_manifest_sha256'}
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')
PROVIDER = re.compile(r'[a-z0-9][a-z0-9_.-]*')


def same(left, right):
    return canonical(left) == canonical(right)


def passed(value):
    require(isinstance(value, dict) and value.get('status') == 'passed' and
            not any(value.get(key) for key in ('global_errors', 'missing_inputs', 'blocked_providers')),
            'Formal readiness contains blockers')


def digest(value):
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def revision(value):
    return isinstance(value, str) and HEX40.fullmatch(value) is not None


def validate_formal_assessment(report, receipt=None):
    """Return mode; old origin shape remains compatible, new mode is explicit.

Legacy export still separately requires payment_discovery, as it did before.
Legacy origin did not require that later-added subgate, so this helper preserves
its historical acceptance. Canonical mode always requires the payment subgate.
"""
    passed(report)
    mode = report.get('evaluation')
    require(mode in {COMPOSED, CANONICAL}, 'Unsupported formal assessment scope')
    passed(report.get('publication_surfaces'))
    if mode == COMPOSED:
        passed(report.get('composed_candidate'))
        return mode
    require(report.get('scope') == FORMAL_SCOPE and 'candidate_source_authorization' not in report,
            'Canonical candidate is not a formal assessment')
    require('composed_candidate' not in report, 'Canonical assessment cannot claim local composition')
    passed(report.get('payment_discovery'))
    imported = report.get('canonical_runtime_import')
    passed(imported)
    require(imported.get('scope') == IMPORT_SCOPE, 'Canonical import scope differs')
    inputs = imported.get('inputs')
    passed(inputs)
    require(type(inputs.get('schema_version')) is int and inputs['schema_version'] in {1, 2} and
            inputs.get('scope') == INPUT_SCOPE, 'Canonical input assessment scope differs')
    pins = inputs.get('compiler_inputs')
    require(isinstance(pins, dict) and set(pins) == INPUT_KEYS and
            pins.get('protocol_version') == 'aisa-runtime-canonical-v1' and
            all((revision if key in {'docs_ref', 'composer_revision'} else digest)(pins[key])
                for key in INPUT_KEYS - {'protocol_version'}), 'Canonical build pins invalid')
    if inputs['schema_version'] == 1:
        require('source_input_provenance' not in inputs and 'input_context_sha256' not in inputs and
                inputs.get('source_formal_provenance', {}).get('expected_docs_ref') == pins['docs_ref'],
                'Canonical formal schema provenance differs')
        context_hash = 'source_pointer_sha256'
    else:
        provenance = inputs.get('source_input_provenance')
        require('source_formal_provenance' not in inputs and 'source_pointer_sha256' not in inputs and
                isinstance(provenance, dict) and set(provenance) == {
                    'kind', 'expected_docs_ref', 'bundle_manifest_sha256', 'historical_formal_ref',
                    'input_context_sha256', 'input_source_receipts_sha256'} and
                provenance['kind'] == 'reviewed_git_input' and
                provenance['expected_docs_ref'] == pins['docs_ref'] and
                provenance['bundle_manifest_sha256'] == pins['bundle_manifest_sha256'] and
                revision(provenance['historical_formal_ref']) and
                digest(provenance['input_context_sha256']) and
                provenance['input_context_sha256'] == inputs.get('input_context_sha256') and
                digest(provenance['input_source_receipts_sha256']),
                'Canonical reviewed schema provenance differs')
        context_hash = 'input_context_sha256'
    for key in ('runtime_acquisition_sha256', 'canonical_manifest_sha256', 'current_before_sha256',
                'current_after_sha256', context_hash, 'source_receipts_sha256'):
        require(digest(inputs.get(key)), 'Canonical input hash missing: ' + key)
    runtime = report.get('runtime')
    require(isinstance(runtime, dict) and set(runtime) == {'artifact_revision', 'source_digest', 'compiler_revision', 'generation'}
            and digest(runtime['artifact_revision']) and digest(runtime['source_digest'])
            and revision(runtime['compiler_revision']) and type(runtime['generation']) is int
            and runtime['generation'] > 0, 'Canonical Runtime identity invalid')
    require(inputs['runtime_acquisition_sha256'] == report.get('runtime_acquisition_sha256') and
            same(inputs.get('runtime'), report.get('runtime')), 'Canonical input Runtime identity differs')
    require(inputs.get('source_checked_at') == report.get('source_governance', {}).get('checked_at'),
            'Canonical source assessment clock differs')
    require(same(inputs.get('source_observations'), report.get('source_governance', {}).get('sources')),
            'Canonical original source observations differ')
    frozen, current = (inputs.get(key) for key in ('frozen_input_files_sha256', 'current_input_files_sha256'))
    require(isinstance(frozen, dict) and frozen and isinstance(current, dict) and current and
            all(isinstance(name, str) and not name.startswith('/') and '..' not in name.split('/') and digest(value)
                for name, value in frozen.items()) and
            all(name in frozen and value == frozen[name] for name, value in current.items()),
            'Canonical fixed schema input hashes invalid')
    if inputs['schema_version'] == 2:
        for path, key in (
                ('docs/schema-inputs/context.json', 'input_context_sha256'),
                ('docs/schema-inputs/source-receipts.json', 'input_source_receipts_sha256')):
            require(frozen.get(path) == provenance[key] and current.get(path) == provenance[key],
                    'Canonical reviewed input evidence hashes differ')
    artifact = report.get('publication_artifact', {})
    assessed, previous = imported.get('assessed_base'), imported.get('previous_formal_ref')
    require(revision(assessed) and revision(previous) and artifact.get('published_ref') == assessed,
            'Canonical assessed base binding differs')
    lineage = imported.get('registry_lineage', {})
    require(lineage.get('previous_formal_provenance', {}).get('expected_docs_ref') == previous and
            digest(lineage.get('previous_registry_sha256')) and digest(lineage.get('fixed_registry_sha256')),
            'Canonical registry lineage differs')
    require(lineage['fixed_registry_sha256'] == frozen.get('openapi/registry.yaml'),
            'Canonical registry input hash differs')
    require(artifact.get('assessment_scope') == ARTIFACT_SCOPE, 'Canonical artifact assessment scope differs')
    from runtime_consolidate_openapi import SKIP_FILES
    files = artifact.get('files_sha256', {})
    native = imported.get('native_sha256')
    require(isinstance(files, dict) and isinstance(native, dict) and native and
            all(isinstance(name, str) and PROVIDER.fullmatch(name) and digest(value) for name, value in native.items()),
            'Canonical native hashes invalid')
    expected_native = {name[len('openapi/'):-5]: value for name, value in files.items()
        if name.startswith('openapi/') and name.count('/') == 1 and name.endswith('.json')
        and name.split('/')[-1] not in SKIP_FILES}
    require(same(native, expected_native) and digest(imported.get('aggregate_sha256')) and
            files.get('openapi/openapi.json') == imported['aggregate_sha256'],
            'Canonical publication native or aggregate hashes differ')
    if receipt is not None:
        require(same(inputs['runtime'], {key: receipt.get(key) for key in
            ('artifact_revision', 'source_digest', 'compiler_revision', 'generation')}),
            'Canonical receipt Runtime identity differs')
        rows = receipt.get('manifest_files')
        require(isinstance(rows, list) and all(isinstance(row, dict) and isinstance(row.get('name'), str)
                and digest(row.get('sha256')) for row in rows), 'Canonical receipt member hashes invalid')
        members = {row['name']: row['sha256'] for row in rows}
        require(len(members) == len(rows), 'Duplicate canonical receipt member')
        expected = {'contracts/native/' + name + '.json': value for name, value in native.items()}
        expected.update({'contracts/openapi.json': imported['aggregate_sha256'],
                         'contracts/manifest.json': inputs['canonical_manifest_sha256']})
        actual = {name: value for name, value in members.items() if name.startswith('contracts/')
                  and name != 'contracts/readiness.json'}
        require(same(expected, actual) and digest(members.get('contracts/readiness.json')) and
                receipt.get('canonical_validation', {}).get('protocol_version') == pins['protocol_version'],
                'Canonical receipt graph differs from publication')
    return mode
