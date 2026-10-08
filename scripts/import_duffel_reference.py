#!/usr/bin/env python3
"""Convert saved official Duffel v2 references, without network or publication."""
import argparse
import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path

from compose_openapi import digest
from source_json import loads

CONVERTER = 'scripts/import_duffel_reference.py@1'
ORIGIN = 'https://api.duffel.com'
REFERENCE = 'https://duffel.com/docs/api/v2/'
SDK_REVISION = 'ebcf6c483b0ec7d0290e9e020e261cf5d15b7d16'
# The fixed SDK supplies the wire data envelope and array/single distinction.
# Client.ts proves status/headers are SDK additions, not wire properties.
SDK_HASHES = {
    'src__types__ClientType.ts': '3aa0ea34054d294f71deaad9005eba83e841cfb70588ca47b6ba55a9f59161b5',
    'src__Client.ts': '0de07d39cc8dd3faae13561cd2e291e7bcaaf58761433bd35db4d929bc8d6b7b',
    'src__Stays__SearchResults__SearchResults.ts': '3e7bba8537165c3f4ce5335917e83e5033e32ae15be19df138db60a17c48e47b',
    'src__Stays__Quotes__Quotes.ts': '3e23e6b8d5c914fd9bb23360241878a85921734bf21d761207862d8664fca299',
    'src__Stays__Bookings__Bookings.ts': 'b903a3227b7a364545853c082db3d2ebb50e46cd9b4cfb1c06f50fe696865c9a',
    'src__Stays__LoyaltyProgrammes__LoyaltyProgrammes.ts': '6fec6a4a64ad279177af097a476d13afce6a2b291ced73d0d32f81f9c4c3ede0',
    'src__Stays__Stays.ts': '807594b33c581196b12a237bd19186ae1ca77d5f79a31dd8860a709c5e64f4c3',
}
OPERATIONS = {
    'search': {'stays-search': ('POST', '/stays/search', False)},
    'search-result': {'fetch-all-rates': ('POST', '/stays/search_results/{search_result_id}/actions/fetch_all_rates', False)},
    'quotes': {'create-quote': ('POST', '/stays/quotes', False), 'get-quote': ('GET', '/stays/quotes/{id}', False)},
    'bookings': {'list-bookings': ('GET', '/stays/bookings', True), 'create-booking': ('POST', '/stays/bookings', False),
                 'cancel-booking': ('POST', '/stays/bookings/{booking_id}/actions/cancel', False),
                 'get-booking': ('GET', '/stays/bookings/{id}', False)},
    'accommodation-loyalty-programmes': {'list-loyalty-programmes': ('GET', '/stays/loyalty_programmes', True)},
}


class NextData(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=False)
        self.active, self.parts, self.count = False, [], 0
        self.feed(raw.decode('utf-8'))
        if self.count != 1:
            raise ValueError('exactly one __NEXT_DATA__ script required')

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == '__NEXT_DATA__':
            self.active = True
            self.count += 1

    def handle_endtag(self, tag):
        if tag == 'script':
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def page(raw, slug):
    if slug not in OPERATIONS:
        raise ValueError('unsupported official resource')
    parsed = NextData(raw)
    value = loads(''.join(parsed.parts))['props']['pageProps']
    if value['version'] != 'v2' or value['resourceSlug'] != slug:
        raise ValueError('official resource/version mismatch')
    resource = value['resource']
    if resource['model'].get('type') != 'object' or not resource['model'].get('properties'):
        raise ValueError('explicit resource object schema missing')
    return resource


def envelope(model, array=False):
    # PaginationMeta is copied from the hash-locked SDK declaration. We retain
    # its number type, optional fields and nullable after exactly as declared.
    return {'type': 'object', 'required': ['data'], 'properties': {
        'data': {'type': 'array', 'items': copy.deepcopy(model)} if array else copy.deepcopy(model),
        'meta': {'type': 'object', 'properties': {
            'limit': {'type': 'number'}, 'before': {'type': 'string'},
            'after': {'type': 'string', 'nullable': True}}}}}


def convert(directory, fetched_at):
    directory = Path(directory)
    references, paths, skipped = [], {}, []
    for filename, expected in SDK_HASHES.items():
        raw = (directory / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('SDK authority hash mismatch: ' + filename)
        references.append({'file': filename, 'sha256': expected,
                           'url': 'https://raw.githubusercontent.com/duffelhq/duffel-api-javascript/' + SDK_REVISION + '/' + filename.replace('__', '/')})
    for slug, expected in OPERATIONS.items():
        raw = (directory / (slug + '.html')).read_bytes()
        resource = page(raw, slug)
        references.append({'url': REFERENCE + slug, 'sha256': hashlib.sha256(raw).hexdigest()})
        seen = set()
        for item in resource['operations']:
            name = item['slug']
            if name not in expected:
                skipped.append({'resource': slug, 'operation': name, 'reason': 'no reviewed SDK envelope binding'})
                continue
            method, path, array = expected[name]
            if name in seen or item['endpoint'] != {'method': method, 'uri': ORIGIN + path}:
                raise ValueError('duplicate or changed official operation identity')
            seen.add(name)
            if item['requestHeaders'].get('Duffel-Version') != 'v2' or item['requestHeaders'].get('Accept') != 'application/json':
                raise ValueError('official wire version/media changed')
            if ('bodyDataSchema' in item) != (name in {'stays-search', 'create-quote', 'create-booking'}):
                raise ValueError('reviewed request body declaration changed')
            operation = {'summary': item['title'], 'description': item['description'],
                         'parameters': copy.deepcopy(item['requestParameters']),
                         'x-aisa-reference-url': REFERENCE + slug,
                         'responses': {'2XX': {'description': 'Successful JSON response; SDK accepts the successful HTTP range.',
                             'content': {'application/json': {'schema': envelope(resource['model'], array)}}}}}
            if 'bodyDataSchema' in item:
                operation['requestBody'] = {'required': True, 'content': {'application/json': {
                    'schema': {'type': 'object', 'required': ['data'], 'properties': {'data': copy.deepcopy(item['bodyDataSchema'])}}}}}
            if name == 'cancel-booking':
                # Alpha-renaming only: same literal URL segments and position.
                operation['x-aisa-reference-path'] = path
                path = path.replace('{booking_id}', '{id}')
                for parameter in operation['parameters']:
                    if parameter['in'] == 'path' and parameter['name'] == 'booking_id':
                        parameter['name'] = 'id'
            if method.lower() in paths.setdefault(path, {}):
                raise ValueError('duplicate output operation')
            paths[path][method.lower()] = operation
        if seen != set(expected):
            raise ValueError('reviewed official operation missing')
    document = {'openapi': '3.0.3', 'info': {'title': 'Official Duffel Stays references', 'version': 'v2'},
                'servers': [{'url': ORIGIN}], 'paths': paths}
    source = {'kind': 'manual', 'url': REFERENCE + 'search', 'converter': CONVERTER,
              'fetched_at': fetched_at, 'content_hash': digest(document), 'references': references,
              'sdk_revision': SDK_REVISION, 'skipped_operations': skipped,
              'authority': 'official HTML structured schemas plus pinned provider SDK; converted, not downloaded OpenAPI',
              'response_status_basis': 'Client.request accepts response.ok; no exact success status is inferred',
              'request_body_required_basis': 'Stays.search(params), Quotes.create(rateId) and Bookings.create(payload) have required SDK arguments; Client.request wraps them in data',
              'limitations': ['No examples infer types, required fields, response codes or extra fields.',
                             'SDK-added status and headers are not wire response fields.',
                             'Conditional rules expressed in descriptions remain prose.',
                             'Source acquisition and metadata matches do not prove current wire behavior.']}
    document['info']['x-aisa-source'] = source
    return document


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--fetched-at', required=True)
    args = parser.parse_args()
    print(json.dumps(convert(args.directory, args.fetched_at), ensure_ascii=False, indent=2))
