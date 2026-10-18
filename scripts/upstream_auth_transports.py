"""Finite driver-owned server authentication, separate from caller forwarding.

These facts describe selected transport mechanics. They do not attest key
validity, account ownership, supplier acceptance, or customer key support.
"""
from __future__ import annotations

import hashlib
import json

ORIGIN = 'https://relayer-v2.polymarket.com'
SOURCE = 'https://docs.polymarket.com/api-spec/relayer-openapi.yaml'
BUILDER = frozenset({'poly_builder_api_key', 'poly_builder_timestamp',
                     'poly_builder_passphrase', 'poly_builder_signature'})
API_KEY = frozenset({'relayer_api_key', 'relayer_api_key_address'})
SCHEMES = {'polymarket_relayer_api_key': API_KEY, 'polymarket_builder_hmac': BUILDER}
FIELDS = frozenset({'schema_version', 'driver', 'scheme', 'credential_source',
                    'upstream_method', 'upstream_origin_sha256',
                    'upstream_path_sha256', 'public_selector_sha256'})


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def server_auth_headers(runtime, provider, method, document, source):
    """Validate a closed descriptor against a locked official source operation.

    The selected group is supplied by the driver; optional alternative groups
    are not caller inputs. Unknown headers are deliberately not exempted.
    """
    if 'x-aisa-upstream-auth' not in runtime:
        return frozenset()
    auth = runtime['x-aisa-upstream-auth']
    invalid = ValueError('invalid or mismatched runtime server-auth transport')
    if (type(auth) is not dict or set(auth) != FIELDS
            or type(auth.get('schema_version')) is not int or auth['schema_version'] != 1
            or any(type(auth[k]) is not str for k in FIELDS - {'schema_version'})
            or auth['driver'] != 'polymarket_relayer_v1'
            or auth['credential_source'] != 'provider_configuration'
            or auth['scheme'] not in SCHEMES or provider != 'polymarket-relayer'
            or runtime.get('x-aisa-validation') not in {'provider', 'mixed'}):
        raise invalid
    path = runtime.get('x-aisa-upstream-path')
    if (path, method.upper()) not in {('/submit', 'POST'), ('/transactions', 'GET')}:
        raise invalid
    selector = json.dumps({'auth_location': 'header', 'credential_scheme': auth['scheme'],
                           'origin': ORIGIN}, sort_keys=True, separators=(',', ':'))
    expected = {'upstream_method': method.upper(), 'upstream_origin_sha256': _sha(ORIGIN),
                'upstream_path_sha256': _sha(path), 'public_selector_sha256': _sha(selector)}
    if any(auth[k] != v for k, v in expected.items()):
        raise invalid
    original = document.get('paths', {}).get(path, {}).get(method.lower(), {})
    servers = original.get('servers', document.get('paths', {}).get(path, {}).get('servers', document.get('servers', [])))
    if (not original or document.get('info', {}).get('x-aisa-source', {}).get('url') != SOURCE
            or not isinstance(servers, list) or len(servers) != 1
            or type(servers[0]) is not dict or servers[0].get('url') != ORIGIN):
        raise invalid
    known = BUILDER | API_KEY
    seen = set()
    for parameter in source.get('parameters', []):
        if parameter.get('in') != 'header':
            continue
        name = parameter.get('name', '').lower()
        if name not in known:
            continue
        if (name in seen or parameter.get('schema', {}).get('type') != 'string'
                or type(parameter.get('required', False)) is not bool
                or (parameter.get('required') is True and name not in SCHEMES[auth['scheme']])):
            raise invalid
        seen.add(name)
    if not SCHEMES[auth['scheme']] <= seen:
        raise invalid
    return frozenset(seen)
