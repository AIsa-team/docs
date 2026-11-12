"""Replay exact response-shape amendments without publishing production payloads.

The source-only importer remains strict. Private capture bytes produce a pinned
shape attestation; repository examples are explicitly synthetic. Presence in a
capture is not converted into required fields or sample-value enums.
"""
import copy
import hashlib
import json

from jsonschema import Draft202012Validator, FormatChecker

from compose_openapi import digest
from import_similarweb_response_reference import (
    convert_response_only_reference, declaration, object_fields,
)

VERSION = 'scripts/amend_similarweb_observed_responses.py@2'
CASES = {
    '/apis/v1/similarweb/keyword-analysis/keywords/overview': {
        'name': 'keywords',
        'prior_hash': 'sha256:9e612a2d79ac41928a6d3de949e2d7ead736737bab64a187e25a3094e1b684c6',
        'body_hash': 'sha256:621736c1323cb14d3d4df3b44c7e357844ef49efb2e1b495f9314780538ab157',
        'attestation_hash': 'sha256:961c915b132d62b1561717a39d897a821643be2c29d1b4a075bfd9fcd6f08890',
        'partial': ('data',),
    },
    '/apis/v1/similarweb/website-analysis/websites/traffic-by-demographics/aggregated': {
        'name': 'demographics',
        'prior_hash': 'sha256:6c33479d8ad5f17d03f8bdf90a9df0c50c7e54569086e313e0d88af2f43281aa',
        'body_hash': 'sha256:94c5bec29f5ba549ac36ea3080569e88ec36749cf56c4da723734671dcb15e46',
        'attestation_hash': 'sha256:4a19c61b678321f1546e5ce8f5ff3d3519b74cb484fc1715305ef6338123610a',
        'partial': ('data', 'meta.request.age_buckets', 'meta.request.metrics'),
    },
}


def child(nodes, name):
    matches = [node for node in nodes if node.get('name') == name]
    if len(matches) != 1:
        raise ValueError('one exact official field required: ' + name)
    return matches[0]


def shape_attestation(value):
    """Project only types, field names, array sizes and date-format results."""
    if isinstance(value, dict):
        return {'type': 'object', 'properties': {key: shape_attestation(item) for key, item in value.items()}}
    if isinstance(value, list):
        return {'type': 'array', 'observed_item_count': len(value),
                'observed_items': [shape_attestation(item) for item in value]}
    if value is None:
        return {'type': 'null'}
    if isinstance(value, bool):
        return {'type': 'boolean'}
    if isinstance(value, int):
        return {'type': 'integer'}
    if isinstance(value, float):
        return {'type': 'number'}
    if isinstance(value, str):
        result = {'type': 'string'}
        checker = FormatChecker()
        if checker.conforms(value, 'date'):
            result['format_checks'] = {'date': True, 'date-time': checker.conforms(value, 'date-time')}
        return result
    raise ValueError('unsupported captured JSON value')


def attest_private_response(record_bytes):
    """Extract a value-free attestation from PRIVATE capture bytes, not a schema."""
    record = json.loads(record_bytes)
    request = record.get('request', {})
    path = request.get('path')
    body = record.get('body')
    if path not in CASES or request.get('method') != 'GET' or request.get('origin') != 'https://api.aisa.one':
        raise ValueError('observation route/origin/method mismatch')
    if (record.get('http_status') != 200 or record.get('state') != 'completed'
            or record.get('mode') != 'run' or not isinstance(body, dict)
            or not isinstance(body.get('meta'), dict) or body['meta'].get('status') != 'success'
            or not isinstance(body.get('data'), list) or not body['data']
            or any(not isinstance(item, dict) or not item for item in body['data'])):
        raise ValueError('nonempty successful HTTP 200 observation required')
    if digest(body) != CASES[path]['body_hash']:
        raise ValueError('private observation body does not match the reviewed capture hash')
    return {
        'kind': 'private_response_shape_attestation',
        'representation': 'Types, field names, array counts and date-format checks extracted from a private production response. This is not the response payload or a required-field schema.',
        'request': copy.deepcopy(request), 'mode': record['mode'], 'state': record['state'],
        'observed_at': record['completed_at'], 'http_status': record['http_status'],
        'response_status': body['meta']['status'],
        'capture_hashes': {
            'record_file_sha256': 'sha256:' + hashlib.sha256(record_bytes).hexdigest(),
            'record_canonical_hash': digest(record),
            'body_canonical_hash': digest(body),
            'raw_body_sha256': record['raw_body_sha256'],
        },
        'body_shape': shape_attestation(body),
    }


def validate_private_response(source, record_bytes, attestation):
    """Validate privately supplied actual bytes; ordinary CI has no such bytes."""
    if attest_private_response(record_bytes) != attestation:
        raise ValueError('private capture does not reproduce the published attestation')
    path = attestation['request']['path']
    schema = source['paths'][path]['get']['responses']['200']['content']['application/json']['schema']
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(record_bytes)['body'])
    return {'actual_private_body_validation': 'passed with JSON Schema Draft 2020-12 and FormatChecker',
            'body_canonical_hash': attestation['capture_hashes']['body_canonical_hash'],
            'attestation_hash': digest(attestation), 'schema_hash': digest(schema)}


def amend_observed_response(source, official_html, observation, evidence_path, example):
    """Replay only the pinned shape proof; publish a separate synthetic example."""
    request = observation.get('request', {})
    path = request.get('path')
    if path not in CASES or request.get('method') != 'GET' or request.get('origin') != 'https://api.aisa.one':
        raise ValueError('observation route/origin/method mismatch')
    case = CASES[path]
    if (observation.get('kind') != 'private_response_shape_attestation'
            or observation.get('http_status') != 200 or observation.get('state') != 'completed'
            or observation.get('mode') != 'run' or observation.get('response_status') != 'success'
            or not observation.get('observed_at')):
        raise ValueError('successful HTTP 200 shape attestation required')
    if digest(observation) != case['attestation_hash']:
        raise ValueError('attestation does not match the reviewed capture projection hash')
    if observation['capture_hashes']['body_canonical_hash'] != case['body_hash']:
        raise ValueError('attested private body hash mismatch')
    if example.get('kind') != 'synthetic_example' or not isinstance(example.get('body'), dict):
        raise ValueError('separately labeled synthetic example required')
    shape = observation['body_shape']
    data_proof = shape['properties']['data']
    if (data_proof.get('type') != 'array' or not data_proof.get('observed_items')
            or data_proof['observed_item_count'] != len(data_proof['observed_items'])
            or any(item.get('type') != 'object' or not item.get('properties') for item in data_proof['observed_items'])):
        raise ValueError('nonempty object-item attestation required')
    meta_proof = shape['properties']['meta']['properties']
    request_proof = meta_proof['request']['properties']
    result = copy.deepcopy(source)
    metadata = result['info'].pop('x-aisa-source')
    if set(result['paths']) != {path} or digest(result) != case['prior_hash'] or metadata['content_hash'] != case['prior_hash']:
        raise ValueError('prior source does not match the reviewed declaration')
    upstream_path = '/v5/' + path.removeprefix('/apis/v1/similarweb/')
    original, _ = convert_response_only_reference(
        official_html, upstream_path, metadata['url'], path,
        incomplete_array_paths=case['partial'],
    )
    if digest(original) != case['prior_hash']:
        raise ValueError('official declarations differ from the reviewed predecessor')
    section = declaration(official_html, upstream_path)
    official_response = next(response for response in section['responses']
                             if response['statusCode'] == 200 and response['contentType'] == 'application/json')
    nodes = copy.deepcopy(official_response['body'])
    changes = []

    def replace(node, key, value, location, reason):
        changes.append({'path': location + '.' + key, 'before': copy.deepcopy(node.get(key)),
                        'after': copy.deepcopy(value), 'reason': reason})
        if value is None:
            node.pop(key, None)
        else:
            node[key] = value

    data = child(nodes, 'data')
    prototype = data['items'][0]
    replace(prototype, 'valueType', 'object', 'data[0]', 'The pinned private-response projection attests nonempty object items; official named field declarations are retained.')
    meta = child(nodes, 'meta')
    echoed = child(meta['items'], 'request')
    string_arrays = []
    if case['name'] == 'keywords':
        proofs = [item['properties']['ai_overview'] for item in data_proof['observed_items']]
        string_arrays.append((child(prototype['items'], 'ai_overview'), 'data[0].ai_overview', proofs))
    else:
        for name in ('age_buckets', 'metrics'):
            string_arrays.append((child(echoed['items'], name), 'meta.request.' + name, [request_proof[name]]))
    for node, location, proofs in string_arrays:
        if any(proof.get('type') != 'array' or not proof.get('observed_items')
               or proof['observed_item_count'] != len(proof['observed_items'])
               or any(item.get('type') != 'string' for item in proof['observed_items']) for proof in proofs):
            raise ValueError('nonempty string-item attestation required: ' + location)
        replace(node['items'][0], 'valueType', 'string', location + '[0]', 'The pinned projection attests nonempty string items; official optionality and nullability are retained.')
        if 'enumValue' in node['options']:
            if node['options']['enumValue'] != node['items'][0]['options'].get('enumValue'):
                raise ValueError('official duplicated item enum differs')
            replace(node['options'], 'enumValue', None, location + '.options',
                    'Remove the duplicate array-level representation; the identical official enum remains enforced on the now-confirmed string item.')

    dates = [(child(echoed['items'], name), 'meta.request.' + name, [request_proof[name]])
             for name in ('start_date', 'end_date')]
    dates += [(node, 'meta.' + node['name'], [meta_proof[node['name']]]) for node in meta['items']
              if node['name'] in ('last_update', 'last_updated') and node['name'] in meta_proof]
    if case['name'] == 'keywords':
        dates.append((child(prototype['items'], 'date'), 'data[0].date',
                      [item['properties']['date'] for item in data_proof['observed_items']]))
    for node, location, proofs in dates:
        if (node.get('options', {}).get('format') == 'date-time'
                and all(proof.get('type') == 'string' and proof.get('format_checks') == {'date': True, 'date-time': False}
                        for proof in proofs)):
            replace(node['options'], 'format', None, location + '.options',
                    'The exact observed field passed date and failed date-time checks; preserve string/nullability without imposing an unsupported format.')
    corrected = {'type': 'object', **object_fields(nodes, 'response')}
    if case['name'] == 'demographics':
        if meta_proof.get('last_updated', {}).get('type') != 'string':
            raise ValueError('observed last_updated string attestation required')
        corrected['properties']['meta']['properties']['last_updated'] = {
            'type': 'string', 'description': 'Data update date observed as a string in the successful AIsa response; a timestamp format is not required.',
        }
        changes.append({'path': 'meta.last_updated', 'before': None,
                        'after': corrected['properties']['meta']['properties']['last_updated'],
                        'reason': 'The private capture contains last_updated; the separate unobserved official last_update declaration, including its date-time format, is unchanged.'})
    Draft202012Validator.check_schema(corrected)
    Draft202012Validator(corrected, format_checker=FormatChecker()).validate(example['body'])
    response = result['paths'][path]['get']['responses']['200']
    response['description'] = 'Successful JSON response. Official fields with captured AIsa success-response shape corrections; the example uses synthetic values.'
    response['content']['application/json'] = {
        'schema': corrected,
        'examples': {'synthetic_success': {
            'summary': 'Illustrative successful response with synthetic values',
            'description': 'This is not a production response. Field shapes use the reviewed official declarations and private capture attestation recorded in ' + evidence_path + '.',
            'value': copy.deepcopy(example['body']),
        }},
    }
    receipt = {
        'amendment': VERSION, 'public_path': path, 'method': 'GET',
        'prior_content_hash': case['prior_hash'], 'official_response_hash': digest(official_response),
        'observation_body_hash': observation['capture_hashes']['body_canonical_hash'],
        'observation_record_hash': observation['capture_hashes']['record_canonical_hash'],
        'captured_record_file_sha256': observation['capture_hashes']['record_file_sha256'],
        'captured_raw_body_sha256': observation['capture_hashes']['raw_body_sha256'],
        'shape_attestation_hash': digest(observation),
        'observed_at': observation['observed_at'], 'query': copy.deepcopy(request['query']),
        'http_status': 200, 'response_status': 'success', 'changes': changes,
        'synthetic_example_hash': digest(example),
        'validation': 'CI replays the pinned type/format/element-shape attestation and validates the separately labeled synthetic example with JSON Schema Draft 2020-12 and FormatChecker. Production-body validation requires the private capture bytes.',
        'limits': ['A single successful request confirms these corrected shapes, not every request combination.',
                   'No required fields or enum values were inferred from sample presence or values. Official field nullability and constraints are retained.',
                   'Committed examples contain synthetic values. The shape attestation is not a raw response payload; production payloads remain private.'],
    }
    metadata['prior_source'] = copy.deepcopy(metadata)
    metadata['converter'] = VERSION
    metadata['partial_response_scope'] = []
    metadata['source_review_evidence'] = metadata['review_evidence']
    metadata['review_evidence'] = evidence_path
    metadata['limits'] = receipt['limits'] + ['Only HTTP 200 application/json is covered by this amendment.']
    metadata['observed_at'] = receipt['observed_at']
    metadata['observed_response_amendment'] = {'evidence': evidence_path, **{key: receipt[key] for key in (
        'prior_content_hash', 'official_response_hash', 'observation_body_hash', 'observation_record_hash', 'shape_attestation_hash', 'observed_at')}}
    metadata['response_basis'] = 'Official HTTP 200 JSON field declarations with exact, replayable corrections supported by a pinned shape attestation from a private nonempty successful AIsa response.'
    metadata['content_hash'] = digest(result)
    receipt['content_hash'] = metadata['content_hash']
    result['info']['x-aisa-source'] = metadata
    return result, receipt
