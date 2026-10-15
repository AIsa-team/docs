"""Integrity checks for optional Runtime canonical files, never source authorization."""
import hashlib
import json
import re

from source_json import checked_float

PROTOCOL = 'aisa-runtime-canonical-v1'
MANIFEST = 'contracts/manifest.json'
AGGREGATE = 'contracts/openapi.json'
READINESS = 'contracts/readiness.json'
MAX_METADATA = 1 << 20
MAX_AGGREGATE = 32 << 20
FACT = re.compile(r'(?:index\.json|providers/[a-z0-9][a-z0-9_.-]*\.json)')
NATIVE = re.compile(r'contracts/native/[a-z0-9][a-z0-9_.-]*\.json')
HEX64 = re.compile(r'[0-9a-f]{64}')
HEX40 = re.compile(r'[0-9a-f]{40}')
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}
FIELDS = {'protocol_version', 'generation', 'source_digest', 'compiler_revision',
          'bundle_manifest_sha256', 'docs_ref', 'composer_revision', 'source_manifest_sha256', 'files'}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def member_name(name):
    return (isinstance(name, str) and len(name) <= 255 and
            (FACT.fullmatch(name) or NATIVE.fullmatch(name) or name in {MANIFEST, AGGREGATE, READINESS}))


def file_limit(name, facts_limit=8 << 20):
    require(member_name(name), 'Unknown Runtime file role')
    if name == AGGREGATE:
        return MAX_AGGREGATE
    if name in {MANIFEST, READINESS}:
        return MAX_METADATA
    return facts_limit


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate canonical JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('Non-finite canonical JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_float=checked_float, parse_constant=invalid)


def operation_ids(document, *, aggregate=False, security_debt=None):
    # Reuse the production mirror rule and resolver, not a second endpoint list.
    from compose_openapi import effective_object, effective_security
    from runtime_consolidate_openapi import remove_v2_path_mirrors, validate_reference_closure
    require(isinstance(document, dict) and document.get('openapi') in {'3.0.0', '3.0.1', '3.0.2', '3.0.3', '3.1.0', '3.1.1'}
            and isinstance(document.get('info'), dict) and isinstance(document.get('paths'), dict),
            'Invalid canonical OpenAPI document')
    validate_reference_closure(document)
    effective_security({}, document)  # Root declarations cannot claim an operation-only legacy exception.
    selected = {'paths': document['paths']}
    removed = remove_v2_path_mirrors(selected)
    require(not aggregate or removed == 0, 'Aggregate still contains removed v2 mirrors')
    identities = set()
    for path, item in selected['paths'].items():
        require(isinstance(path, str) and path.startswith('/') and isinstance(item, dict),
                'Invalid canonical path item')
        item = effective_object(item, document)
        for method, operation in item.items():
            if method not in METHODS:
                continue
            require(isinstance(operation, dict) and isinstance(operation.get('operationId'), str)
                    and operation['operationId'] and operation['operationId'] not in identities,
                    'Invalid or duplicate canonical operation identity')
            _, missing_schemes = effective_security(operation, document)
            if security_debt is not None:
                security_debt.extend({'path': path, 'method': method.upper(),
                    'operation_id': operation['operationId'], 'scheme': scheme}
                    for scheme in sorted(set(missing_schemes)))
            identities.add(operation['operationId'])
    return identities


def validate_canonical_files(contents, current):
    """Validate optional canonical integrity and report explicit historical auth debt.

    This does not match bundle/build pins to deployment policy, approve source
    freshness, or prove native/aggregate field equivalence. The producer and
    consuming policy must separately establish those properties.
    """
    require(all(member_name(name) for name in contents), 'Unknown Runtime file role')
    names = {name for name in contents if name.startswith('contracts/')}
    if not names:
        return None
    native_names = {name for name in names if NATIVE.fullmatch(name)}
    require(native_names and names == native_names | {MANIFEST, AGGREGATE, READINESS},
            'Incomplete canonical Runtime roles')
    for name in names:
        require(0 < len(contents[name]) <= file_limit(name), 'Canonical role byte limit exceeded')
    manifest = strict_json(contents[MANIFEST])
    require(isinstance(manifest, dict) and set(manifest) == FIELDS and
            manifest['protocol_version'] == PROTOCOL, 'Unsupported canonical Runtime protocol')
    require(type(manifest['generation']) is int and 0 <= manifest['generation'] < 1 << 64 and
            manifest['generation'] == current['generation'], 'Canonical generation differs')
    for key in ('source_digest', 'bundle_manifest_sha256', 'source_manifest_sha256'):
        require(isinstance(manifest[key], str) and HEX64.fullmatch(manifest[key]), 'Invalid canonical digest')
    for key in ('compiler_revision', 'docs_ref', 'composer_revision'):
        require(isinstance(manifest[key], str) and HEX40.fullmatch(manifest[key]), 'Invalid canonical revision')
    require(all(manifest[key] == current[key] for key in ('source_digest', 'compiler_revision')),
            'Canonical source or compiler differs from Runtime')
    rows = manifest['files']
    require(isinstance(rows, list) and 3 <= len(rows) <= 511, 'Invalid canonical member count')
    seen = []
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'path', 'bytes', 'sha256'}, 'Invalid canonical file entry')
        name = row['path']
        require(isinstance(name, str) and name in names - {MANIFEST} and name not in seen,
                'Unknown or duplicate canonical member')
        require(type(row['bytes']) is int and row['bytes'] == len(contents[name]) and
                isinstance(row['sha256'], str) and HEX64.fullmatch(row['sha256']) and
                row['sha256'] == hashlib.sha256(contents[name]).hexdigest(),
                'Canonical member bytes or hash differ')
        seen.append(name)
    require(seen == sorted(seen) and set(seen) == names - {MANIFEST}, 'Canonical graph membership differs')
    identities, owners, security_debt = set(), {}, []
    for name in sorted(native_names):
        missing = []
        native_ids = operation_ids(strict_json(contents[name]), security_debt=missing)
        provider = name.removeprefix('contracts/native/').removesuffix('.json')
        owners.update({identity: provider for identity in native_ids})
        security_debt.extend({**row, 'provider': provider, 'document': name} for row in missing)
        require(not identities.intersection(native_ids), 'Canonical native identities overlap')
        identities.update(native_ids)
    missing = []
    require(identities == operation_ids(strict_json(contents[AGGREGATE]), aggregate=True, security_debt=missing),
            'Canonical native and aggregate identities differ')
    security_debt.extend({**row, 'provider': owners[row['operation_id']], 'document': AGGREGATE}
                         for row in missing)
    readiness = strict_json(contents[READINESS])
    require(isinstance(readiness, dict) and readiness.get('status') == 'passed' and
            all(readiness.get(key) == [] for key in ('global_errors', 'missing_inputs', 'blocked_providers')),
            'Canonical compilation readiness did not pass')
    return {'protocol_version': PROTOCOL, 'operation_identity_count': len(identities),
            'security_status': 'historical_debt' if security_debt else 'passed',
            'historical_security_debt': security_debt,
            'scope': 'integrity_and_operation_identity_only_not_field_equivalence_or_source_authorization'}
