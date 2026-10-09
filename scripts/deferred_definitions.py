"""The user-approved CR003 exact enabled definition deferral, separate from baseline.

This changes release blocking only. It grants no method, request, response schema,
identity, source authority, price, or runtime execution permission.
"""
import hashlib
import json
from pathlib import Path

POLICY_PATH = 'openapi/policies/deferred-enabled-20261010.json'
POLICY_SHA256 = '004d82c4dd026ed5ebf326ba9ce10bbea77e836e00f89f63931be28bcc8c32ee'


def canonical_key(provider, kind, key):
    return json.dumps([provider, kind, key], separators=(',', ':'), ensure_ascii=False)


class DeferredDefinitions:
    def __init__(self, value):
        self.metadata = {'policy_id': value['policy_id'], 'path': POLICY_PATH,
                         'sha256': POLICY_SHA256, 'scope': dict(value['scope'])}
        self.keys = frozenset(canonical_key(item['provider'], item['kind'], item['gate_identity'])
                              for item in value['items'])

    def matches(self, provider, kind, key):
        return key is not None and key[-1] == 'enabled' and canonical_key(provider, kind, key) in self.keys


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
    return policy


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
    for scope in (report, report.get('composed_candidate', {})):
        if scope.get('deferred_definitions') != expected:
            raise ValueError('Formal report deferral policy mismatch')
        seen = set()
        for provider, result in scope.get('providers', {}).items():
            for kind, field, key_fn in (('request', 'deferred_pending', _pending_key),
                                        ('response', 'deferred_response_pending', gap_key)):
                for row in result.get(field, []):
                    key = key_fn(row)
                    identity = canonical_key(provider, kind, key)
                    if not policy or not policy.matches(provider, kind, key) or identity in seen:
                        raise ValueError('Formal report contains unapproved or duplicate deferral')
                    seen.add(identity)
