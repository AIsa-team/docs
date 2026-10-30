"""The user-approved CR003 exact enabled definition deferral, separate from baseline.

This changes release blocking only. It grants no method, request, response schema,
identity, source authority, price, or runtime execution permission.
"""
import hashlib
import json
from pathlib import Path

POLICY_PATH = 'openapi/policies/deferred-enabled-20261010.json'
POLICY_SHA256 = '004d82c4dd026ed5ebf326ba9ce10bbea77e836e00f89f63931be28bcc8c32ee'
REBINDING_PATH = 'docs/deferred-age-response-rebinding-20261012.json'
REBINDING_SHA256 = '92137542ef16cea002f25b2f5033406dc88d6d28d39efd23d6f94401d2dc4c50'
FRED_MIGRATION_SHA256 = 'c77c56e6530dc146956fb9c51f58bbc6791b80b3ba0d63f909f59f0de3d92d50'
RESPONSE_IDENTITY_MIGRATION_SHA256 = 'd0af755342167b54205fda53e6c86fb4277e1782db588469bbd40d70b68bb375'
# CR004: a separate, later user approval, code-pinned here because schema input
# bundles carry a closed, cross-repository input membership. CR003 bytes stay
# untouched; this record only adds its own exact request keys.
_RELAYER_REASON = 'unforwarded_source_header'
RELAYER_DEFERRAL = {
    'policy_id': 'CR004-polymarket-relayer-20261019',
    'authorization': 'User (2026-10-19): Relayer 的接口本次在 Docs 里按延期处理、不发布，#672 之后作为正常 PR 移植到 main',
    'decision': 'deferred; definitions remain pending, not completed',
    'until': ('Services PR #672 (caller-owned key-list and builder auth descriptors) is on Services main; '
              'its Docs counterpart is then ported to main as an ordinary PR and this record is removed'),
    'evidence': {'docs_revision': 'e445f43046ce3b1cf2daea3aa9bf28567c720312',
                 'runtime': 'Services main production runtime facts (snapshot G939) have no '
                            'x-aisa-request-auth / x-aisa-upstream-auth descriptor for these operations'},
    'scope': {'request': 3, 'response': 0},
    'items': [
        {'provider': 'polymarket-relayer', 'kind': 'request', 'gate_identity': [
            'polymarket-relayer', 'any_polymarket_relayer_apis_v1_polymarket_relayer_f3537f',
            '/apis/v1/polymarket/relayer/api/keys', 'GET',
            'sha256:29bf36fb154b3d9eeab786b93f5995a18be91bf9d019be5359fe515c173cc524', _RELAYER_REASON,
            'sha256:18204754c3f45b420bf0da9cf9c57a02e69aebc220d04abf27d8ca1b75e99012', 'enabled']},
        {'provider': 'polymarket-relayer', 'kind': 'request', 'gate_identity': [
            'polymarket-relayer', 'any_polymarket_relayer_apis_v1_polymarket_submit',
            '/apis/v1/polymarket/submit', 'POST',
            'sha256:b4eca409728bb05ebf46c0761fedf2eb3554ef7a2f9a07e1aec2811f028050a4', _RELAYER_REASON,
            'sha256:71333b7b539b1d6a951d4085e6c03f141f6cf6d841eef6a15509f282a866ae0e', 'enabled']},
        {'provider': 'polymarket-relayer', 'kind': 'request', 'gate_identity': [
            'polymarket-relayer', 'any_polymarket_relayer_apis_v1_polymarket_transactions',
            '/apis/v1/polymarket/transactions', 'GET',
            'sha256:29ae89d1301e76571703e9414c27c24b73b56ee7fb8ad28edd9f6a7b6fff12f7', _RELAYER_REASON,
            'sha256:fb2c7fab4d590d693382c1b67dd6f0446005544359c61fa18a184fda5eeb58b2', 'enabled']},
    ],
}
RELAYER_DEFERRAL_PATH = 'scripts/deferred_definitions.py#RELAYER_DEFERRAL'
RELAYER_DEFERRAL_SHA256 = '1f84c17c1f94fe1bdd84772369fa523e7e142ad459c1b4c1643a61f33a8e7e16'
# CR005: a separate user approval for the FastMoss creator operations Services
# enabled before Docs had any upstream source for them. Same code-pinned form
# as CR004; it adds only these exact request keys.
_FASTMOSS_REASON = 'upstream_operation_missing'
FASTMOSS_DEFERRAL = {
    'policy_id': 'CR005-fastmoss-20261030',
    'authorization': 'User (2026-10-30): Docs 加延期',
    'decision': 'deferred; definitions remain pending, not completed',
    'until': ('the FastMoss upstream sources are reviewed into Docs and both operations compose; '
              'this record is then removed'),
    'evidence': {'docs_revision': '6ae94090b8558d4384cf3da050dc631e6c396eea',
                 'runtime': 'Services production enabled FastMoss provider 1000114 (endpoints 1003955, 1003956) '
                            'from snapshot generation 1175; Docs has no FastMoss upstream source'},
    'scope': {'request': 2, 'response': 0},
    'items': [
        {'provider': 'fastmoss', 'kind': 'request', 'gate_identity': [
            'fastmoss', 'post_fastmoss_apis_v1_fastmoss_creator_productlist',
            '/apis/v1/fastmoss/creator/productList', 'POST',
            'sha256:911894d1780478d6a2107049f08eb4cdde8f63e5c1e6dff2eccb754015da8ae2', _FASTMOSS_REASON,
            'sha256:ed7eb0e80bc24391bdd8a721f72f7df3b87cff2408ca649cad6c616d5195fb8f', 'enabled']},
        {'provider': 'fastmoss', 'kind': 'request', 'gate_identity': [
            'fastmoss', 'post_fastmoss_apis_v1_fastmoss_creator_rank_topecommerce',
            '/apis/v1/fastmoss/creator/rank/topEcommerce', 'POST',
            'sha256:e0e341b3e59e42466500db744ccb648397904d9b607b60679b6ccda99a3d4dbc', _FASTMOSS_REASON,
            'sha256:8e1d0589ad8d4a368d06500f9db73a10436fc61493977557c58a89eb41a48fe3', 'enabled']},
    ],
}
FASTMOSS_DEFERRAL_PATH = 'scripts/deferred_definitions.py#FASTMOSS_DEFERRAL'
FASTMOSS_DEFERRAL_SHA256 = 'e5abe3fc278b73fa585dc2cfa10e6b6e9284c35f5eb6d6d312f91b8510cfa50b'


def canonical_key(provider, kind, key):
    return json.dumps([provider, kind, key], separators=(',', ':'), ensure_ascii=False)


class DeferredDefinitions:
    def __init__(self, value):
        self.metadata = {'policy_id': value['policy_id'], 'path': POLICY_PATH,
                         'sha256': POLICY_SHA256, 'scope': dict(value['scope'])}
        self.keys = frozenset(canonical_key(item['provider'], item['kind'], item['gate_identity'])
                              for item in value['items'])
        self.response_v2_keys = frozenset()
        self.response_baseline_rebindings = {}

    def matches(self, provider, kind, key):
        return (key is not None and key[-1] == 'enabled' and
                (canonical_key(provider, kind, key) in self.keys or
                 (kind == 'response' and canonical_key(provider, kind, key) in self.response_v2_keys)))

    def response_baseline_matches(self, provider, key, approved):
        old = self.response_baseline_rebindings.get(canonical_key(provider, 'response', key))
        return old is not None and canonical_key(provider, 'response', old) in {
            canonical_key(provider, 'response', prior) for prior in approved}


def _apply_response_identity_v2(policy, migration):
    """Apply only after the loader authenticates the complete record's fixed SHA.

    This binds the existing unknown responses to one initial public Runtime response
    identity. Legacy releases keep their original exact keys during rollout;
    request-sensitive legacy keys never become patterns or response evidence.
    """
    import re
    if (migration.get('schema_version') != 1 or
            migration.get('original_policy_sha256') != POLICY_SHA256 or
            migration.get('baseline_ref') != '78ef376841ead8cde10a79651958790be5a0531c' or
            migration.get('baseline_sha256') != 'e0ef2fdf591d0f6b400d6bf1107bf32a31cc1a3453784dc3962cb66a15d16dbd'):
        raise ValueError('Invalid response identity migration provenance')
    rows = migration.get('bindings', [])
    enabled, baseline, baseline_original, seen_old, seen_new = set(), {}, set(), set(), set()
    for row in rows:
        provider, scope = row.get('provider'), row.get('scope')
        old, new = row.get('old_gate_identity', []), row.get('new_gate_identity', [])
        if (not provider or len(old) != 10 or len(new) != 10 or old[:4] != new[:4]
                or old[7:] != new[7:] or new[4] != 'response-v2'
                or any(not isinstance(new[i], str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', new[i]) for i in (5, 6))):
            raise ValueError('Response identity migration changed protected response identity')
        old_key = canonical_key(provider, 'response', old)
        new_key = canonical_key(provider, 'response', new)
        if old_key in seen_old or new_key in seen_new:
            raise ValueError('Duplicate response identity migration')
        seen_old.add(old_key); seen_new.add(new_key)
        if scope == 'deferred_enabled_response' and old[-1] == 'enabled' and old_key in policy.keys:
            enabled.add(new_key)
        elif scope == 'reviewed_disabled_response_baseline' and old[-1] == 'disabled':
            baseline[new_key] = old
            baseline_original.add(old_key)
        else:
            raise ValueError('Response identity migration expanded original debt scope')
    original = {key for key in policy.keys if json.loads(key)[1] == 'response'}
    if (seen_old - baseline_original != original
            or len(enabled) != migration.get('deferred_response_count')
            or len(baseline) != migration.get('baseline_response_count')
            or migration.get('deferred_response_count') != 53
            or migration.get('baseline_response_count') != 2
            or len(rows) != len(enabled) + len(baseline)):
        raise ValueError('Response identity migration must retain the exact existing response set')
    policy.response_v2_keys = frozenset(enabled)
    policy.response_baseline_rebindings = baseline


def load_deferred_definitions(root):
    path = Path(root) / POLICY_PATH
    if not path.exists():
        return None  # No policy never grants an exemption.
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != POLICY_SHA256:
        raise ValueError('Enabled definition deferral policy differs from approved exact bytes')
    value = json.loads(raw)
    policy = DeferredDefinitions(value)
    if len(policy.keys) != 60 or value['scope'] != {'request': 10, 'response': 50}:
        raise ValueError('Invalid enabled definition deferral scope')
    # A separately reviewed exact replacement retains the original 60-item
    # approval bytes. It never grants both identities or a pattern exemption.
    binding_path = Path(root) / REBINDING_PATH
    if not binding_path.is_file():
        raise ValueError('Missing exact response deferral rebinding')
    binding_raw = binding_path.read_bytes()
    binding_sha = hashlib.sha256(binding_raw).hexdigest()
    if binding_sha not in {REBINDING_SHA256, FRED_MIGRATION_SHA256, RESPONSE_IDENTITY_MIGRATION_SHA256}:
        raise ValueError('Response deferral rebinding differs from reviewed exact bytes')
    record = json.loads(binding_raw)
    if record.get('schema_version') != 1 or len(record.get('rebindings', [])) != 1:
        raise ValueError('Invalid response deferral rebinding scope')
    item = record['rebindings'][0]
    old, new = item['old_gate_identity'], item['new_gate_identity']
    if (item['kind'] != 'response' or len(old) != 10 or len(new) != 10
            or old[:4] != new[:4] or old[7:] != new[7:]
            or old[-1] != 'enabled' or old == new):
        raise ValueError('Response deferral rebinding changed protected identity')
    old_key = canonical_key(item['provider'], item['kind'], old)
    new_key = canonical_key(item['provider'], item['kind'], new)
    if old_key not in policy.keys or new_key in policy.keys:
        raise ValueError('Response deferral rebinding must replace exactly one existing key')
    policy.keys = (policy.keys - {old_key}) | {new_key}
    policy.metadata['rebinding'] = {'path': REBINDING_PATH, 'sha256': binding_sha}
    if binding_sha in {FRED_MIGRATION_SHA256, RESPONSE_IDENTITY_MIGRATION_SHA256}:
        migration = record.get('request_response_migration', {})
        replacements = migration.get('replacements', [])
        if (migration.get('authorization') != value['authorization'] or
                migration.get('original_policy_sha256') != POLICY_SHA256 or
                migration.get('original_scope') != value['scope'] or len(replacements) != 3):
            raise ValueError('Invalid exact FRED debt migration scope')
        expected_paths = {'/apis/v1/fred/series/search', '/apis/v1/geofred/regional/data',
                          '/apis/v1/geofred/shapes/file'}
        if {row['old_gate_identity'][2] for row in replacements} != expected_paths:
            raise ValueError('FRED debt migration changed operation scope')
        for row in replacements:
            old, new = row['old_gate_identity'], row['new_gate_identity']
            if (row['provider'] != 'fred' or row['old_kind'] != 'request' or row['new_kind'] != 'response'
                    or len(old) != 8 or len(new) != 10 or old[0] != 'fred'
                    or old[1:3] != new[:2] or old[3] != 'ANY' or new[2] != 'GET'
                    or old[4] != new[4] or new[3] != 'missing_success_payload'
                    or old[-1] != 'enabled' or new[-1] != 'enabled'):
                raise ValueError('FRED debt migration changed protected Runtime identity')
            old_key = canonical_key('fred', 'request', old)
            new_key = canonical_key('fred', 'response', new)
            if old_key not in policy.keys or new_key in policy.keys:
                raise ValueError('FRED debt migration must replace exactly three original keys')
            policy.keys = (policy.keys - {old_key}) | {new_key}
        if len(policy.keys) != 60:
            raise ValueError('FRED debt migration expanded the original approval')
        policy.metadata['effective_scope'] = {'request': 7, 'response': 53}
    if binding_sha == RESPONSE_IDENTITY_MIGRATION_SHA256:
        _apply_response_identity_v2(policy, record.get('response_identity_migration', {}))
    _apply_relayer_policy(policy)
    _apply_fastmoss_policy(policy)
    return policy


def relayer_deferral_digest(record=None):
    raw = json.dumps(RELAYER_DEFERRAL if record is None else record, sort_keys=True,
                     separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _apply_relayer_policy(policy, record=None):
    """Add CR004's exact Relayer request keys to a loaded CR003 policy.

    Each key is the readiness gate identity of one runtime-enabled Relayer
    operation the composer leaves pending because runtime does not forward the
    source's credential headers. Any other provider, kind, reason, status, or a
    key already covered by CR003 is outside this approval; an edited record
    fails closed instead of silently widening it.
    """
    value = RELAYER_DEFERRAL if record is None else record
    if relayer_deferral_digest(value) != RELAYER_DEFERRAL_SHA256:
        raise ValueError('Relayer deferral record differs from approved exact content')
    items = value['items']
    keys = {canonical_key(item['provider'], item['kind'], item['gate_identity']) for item in items}
    if (value['scope'] != {'request': len(items), 'response': 0} or len(keys) != len(items)
            or any(item['provider'] != 'polymarket-relayer' or item['kind'] != 'request'
                   or len(item['gate_identity']) != 8 or item['gate_identity'][0] != 'polymarket-relayer'
                   or item['gate_identity'][5] != _RELAYER_REASON or item['gate_identity'][-1] != 'enabled'
                   for item in items)
            or keys & policy.keys):
        raise ValueError('Invalid Relayer deferral scope')
    policy.keys = policy.keys | keys
    policy.metadata['additional_policies'] = [{'policy_id': value['policy_id'], 'path': RELAYER_DEFERRAL_PATH,
                                               'sha256': RELAYER_DEFERRAL_SHA256, 'scope': dict(value['scope'])}]


def fastmoss_deferral_digest(record=None):
    raw = json.dumps(FASTMOSS_DEFERRAL if record is None else record, sort_keys=True,
                     separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _apply_fastmoss_policy(policy, record=None):
    """Add CR005's exact FastMoss request keys after CR003 and CR004.

    Each key is the readiness gate identity of one runtime-enabled FastMoss
    operation the composer leaves pending because Docs has no upstream source
    for it. Any other provider, kind, reason, status, or a key already approved
    elsewhere is outside this approval; an edited record fails closed.
    """
    value = FASTMOSS_DEFERRAL if record is None else record
    if fastmoss_deferral_digest(value) != FASTMOSS_DEFERRAL_SHA256:
        raise ValueError('FastMoss deferral record differs from approved exact content')
    items = value['items']
    keys = {canonical_key(item['provider'], item['kind'], item['gate_identity']) for item in items}
    if (value['scope'] != {'request': len(items), 'response': 0} or len(keys) != len(items)
            or any(item['provider'] != 'fastmoss' or item['kind'] != 'request'
                   or len(item['gate_identity']) != 8 or item['gate_identity'][0] != 'fastmoss'
                   or item['gate_identity'][5] != _FASTMOSS_REASON or item['gate_identity'][-1] != 'enabled'
                   for item in items)
            or keys & policy.keys):
        raise ValueError('Invalid FastMoss deferral scope')
    policy.keys = policy.keys | keys
    policy.metadata.setdefault('additional_policies', []).append(
        {'policy_id': value['policy_id'], 'path': FASTMOSS_DEFERRAL_PATH,
         'sha256': FASTMOSS_DEFERRAL_SHA256, 'scope': dict(value['scope'])})


def validate_report_deferrals(root, report):
    """Exporter verifies that a PASS never carries an unbound deferral claim."""
    try:
        from .contract_readiness import _pending_key
        from .gap_evidence import gap_key
    except ImportError:
        from contract_readiness import _pending_key
        from gap_evidence import gap_key
    policy = load_deferred_definitions(root)
    expected = policy.metadata if policy else None
    from formal_assessment import CANONICAL
    # Canonical metadata is independently reconstructed in the outer report;
    # this mode must not fabricate a local Composer result to carry exemptions.
    scopes = (report,) if report.get('evaluation') == CANONICAL else (report, report.get('composed_candidate', {}))
    for scope in scopes:
        if scope.get('deferred_definitions') != expected:
            raise ValueError('Formal report deferral policy mismatch')
        seen = set()
        for provider, result in scope.get('providers', {}).items():
            for kind, field, key_fn in (('request', 'deferred_pending', _pending_key),
                                        ('response', 'deferred_response_pending', gap_key)):
                for row in result.get(field, []):
                    key = key_fn(row)
                    identity = canonical_key(provider, kind, key)
                    if kind == 'response' and key is not None:
                        # A rolling release may recognize two evidence versions
                        # for the same old response debt, never two exemptions.
                        identity = canonical_key(provider, kind, [key[:4], key[-2:]])
                    if not policy or not policy.matches(provider, kind, key) or identity in seen:
                        raise ValueError('Formal report contains unapproved or duplicate deferral')
                    seen.add(identity)
