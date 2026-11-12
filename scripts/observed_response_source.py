"""Publish value-free observed response shapes, never production payloads.

An observation establishes the shape of that successful response only. It does
not establish requiredness, enums, formats, limits or the type of null fields.
"""
import copy
import hashlib

from compose_openapi import digest
from source_governance import initial_policy

VERSION = 'scripts/observed_response_source.py@1'


def project_shape(value, path=(), maps=()):
    if isinstance(value, dict):
        if path in maps:
            variants = {digest(project_shape(v, path + ('*',), maps)): project_shape(v, path + ('*',), maps)
                        for v in value.values()}
            return {'type': 'object', 'map_values': [variants[k] for k in sorted(variants)]}
        return {'type': 'object', 'properties': {
            k: project_shape(v, path + (k,), maps) for k, v in sorted(value.items())}}
    if isinstance(value, list):
        variants = {digest(project_shape(v, path + ('[]',), maps)): project_shape(v, path + ('[]',), maps)
                    for v in value}
        return {'type': 'array', 'item_shapes': [variants[k] for k in sorted(variants)]}
    kind = ('null' if value is None else 'boolean' if isinstance(value, bool)
            else 'integer' if isinstance(value, int) else 'number' if isinstance(value, float)
            else 'string' if isinstance(value, str) else None)
    if kind is None:
        raise ValueError('unsupported JSON value')
    return {'type': kind}


def schema_from_shapes(shapes, root=False):
    if not shapes:
        return {}
    kinds = {s['type'] for s in shapes}
    nonnull = kinds - {'null'}
    if not nonnull:
        return {'description': 'Observed as null; the non-null value type is not established.'}
    if 'number' in nonnull:
        nonnull.discard('integer')
    kinds = nonnull | (set() if root else {'null'})
    result = {'type': next(iter(kinds)) if len(kinds) == 1 else sorted(kinds)}
    objects = [s for s in shapes if s['type'] == 'object']
    if objects:
        result['additionalProperties'] = True
        if any('map_values' in s for s in objects):
            if any('properties' in s for s in objects):
                raise ValueError('mixed map/object observations')
            result['additionalProperties'] = schema_from_shapes([v for s in objects for v in s['map_values']])
        else:
            keys = sorted({k for s in objects for k in s['properties']})
            result['properties'] = {k: schema_from_shapes([s['properties'][k] for s in objects if k in s['properties']]) for k in keys}
    arrays = [s for s in shapes if s['type'] == 'array']
    if arrays:
        result['items'] = schema_from_shapes([v for s in arrays for v in s['item_shapes']])
    return result


def synthetic_example(shape):
    kind = shape['type']
    if kind == 'object':
        if 'map_values' in shape:
            return {'example_key': synthetic_example(shape['map_values'][0])} if shape['map_values'] else {}
        return {k: synthetic_example(v) for k, v in shape['properties'].items()}
    if kind == 'array':
        return [synthetic_example(shape['item_shapes'][0])] if shape['item_shapes'] else []
    return {'null': None, 'string': 'example', 'number': 0.0, 'integer': 0, 'boolean': False}[kind]


def build_source(attestation, evidence_path, offers_schema=None):
    if attestation['http_status'] not in (200, 201) or attestation['mode'] != 'run':
        raise ValueError('actual successful execution required')
    shape = attestation['body_shape']
    if shape.get('type') != 'object' or not shape.get('properties') or 'error' in shape['properties']:
        raise ValueError('nonempty successful response required')
    schema = schema_from_shapes([shape], root=True)
    example = synthetic_example(shape)
    status = str(attestation['http_status'])
    response = {'description': f'Successful JSON response. HTTP {status} was observed through AIsa on 2026-11-12. Observed fields are optional; additional fields and null values remain allowed. The example is synthetic.',
                'content': {'application/json': {'schema': schema, 'examples': {'synthetic_success': {
                    'summary': 'Synthetic illustration of the observed response shape',
                    'description': 'Invented values for shape illustration; not a usable provider record or a production response.', 'value': example}}}}}
    responses = {status: response}
    if offers_schema is not None:
        response['description'] += ' This observed status and shape cover view=itineraries.'
        responses['2XX'] = {
            'description': 'Official default view=offers response model. The supplier SDK accepts successful 2XX responses; an exact status for this view was not established by this live check.',
            'content': {'application/json': {'schema': copy.deepcopy(offers_schema)}}}
    doc = {'openapi': '3.1.0', 'info': {'title': 'Observed successful response: ' + attestation['name'], 'version': '2026-11-12'},
           'servers': [{'url': 'https://api.aisa.one'}],
           'paths': {attestation['public_path']: {attestation['method'].lower(): {'responses': responses}}}}
    source = {'kind': 'manual', 'url': 'https://api.aisa.one' + attestation['public_path'],
              'fetched_at': attestation['observed_at'], 'converter': VERSION, 'content_hash': digest(doc),
              'response_only': True, 'path_space': 'public',
              'upstream_path_sha256': attestation['upstream_path_sha256'],
              'upstream_origin_sha256': attestation['upstream_origin_sha256'],
              'review_evidence': evidence_path,
              'response_basis': 'Actual successful AIsa response; value-free shape projection. This is observed coverage, not an exhaustive official supplier declaration.',
              'observation': {k: attestation[k] for k in ('observed_at', 'http_status', 'raw_body_sha256', 'request_sha256')},
              'shape_attestation_hash': digest(attestation),
              'limits': ['One successful request does not cover every parameter combination or provider result.',
                         'No requiredness, enum, format, limit or non-null type of a null-only field is inferred.',
                         'Dynamic map keys are generalized. Empty arrays keep open items. All example values are synthetic.']}
    if offers_schema is not None:
        source['offers_basis'] = 'Existing reviewed Duffel official offer-request model; retained as a separate default-view branch.'
    doc['info']['x-aisa-source'] = initial_policy(source)
    return doc


def attest(raw, case, request, observed_at, status, maps=()):
    import json
    body = json.loads(raw)
    return {**case, 'kind': 'private_response_shape_attestation', 'mode': 'run',
            'observed_at': observed_at, 'http_status': status,
            'raw_body_sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(),
            'request_sha256': digest(request), 'body_shape': project_shape(body, maps=maps)}
