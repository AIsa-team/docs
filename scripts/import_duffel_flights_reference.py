#!/usr/bin/env python3
"""Convert explicit Duffel Flights HTML schemas plus hash-locked SDK envelopes."""
import copy
import hashlib
import json
from pathlib import Path

from compose_openapi import digest
from import_duffel_reference import NextData, ORIGIN, REFERENCE, SDK_REVISION, envelope
from source_json import loads

CONVERTER = 'scripts/import_duffel_flights_reference.py@1'
SDK_HASHES = {
    "src__types__ClientType.ts": "3aa0ea34054d294f71deaad9005eba83e841cfb70588ca47b6ba55a9f59161b5",
    "src__Client.ts": "0de07d39cc8dd3faae13561cd2e291e7bcaaf58761433bd35db4d929bc8d6b7b",
    "src__booking__OfferRequests__OfferRequests.ts": "0ba7f0987376f743b3e7ff96170826ee5a644b904818e703ccb3f5b0e8ee22c4",
    "src__booking__Offers__Offers.ts": "022d6b38a8f299dadb29f37e6c23c44b23df9842b335ba0fab5c7ed1efef29c5",
    "src__booking__Orders__Orders.ts": "91f5748faac0619fbccb0955156a944507211cfea14df01e323e553138e23a64",
    "src__booking__OrderChangeRequests__OrderChangeRequests.ts": "cf299f61571df50113312835148d507b47ec68033e230876be054d93431e0dfe",
    "src__booking__OrderChanges__OrderChanges.ts": "ba165641b85317525fd8d9f2db61b5fb9072b40177558f26f291797d6adfeb6c",
    "src__booking__OrderCancellations__OrderCancellations.ts": "f93f93edb989e4c8162ace0cc40a01f6b77d29fd671db65dfef59354863d5716",
    "src__booking__SeatMaps__SeatMaps.ts": "07eca0f70081f97688e707bdd7084f8495fb2d3a64bde3d0bc0388bf0ea51b47"
}
# Each tuple binds the reviewed method, wire path, array envelope, request body,
# and whether the resource model covers all documented response variants.
OPERATIONS = {
    'offer-requests': {
        'create-offer-request': ('POST', '/air/offer_requests', False, True, False),
        'get-offer-request-by-id': ('GET', '/air/offer_requests/{id}', False, False, False),
        'get-offer-requests': ('GET', '/air/offer_requests', True, False, True),
    },
    'offers': {
        'get-offer-by-id': ('GET', '/air/offers/{id}', False, False, True),
        'get-offers': ('GET', '/air/offers', True, False, True),
    },
    'orders': {'create-order': ('POST', '/air/orders', False, True, True)},
    'order-change-requests': {
        'get-order-change-request-by-id': ('GET', '/air/order_change_requests/{id}', False, False, True),
        'create-order-change-request': ('POST', '/air/order_change_requests', False, True, True),
    },
    'order-changes': {'create-order-change': ('POST', '/air/order_changes', False, True, True)},
    'order-cancellations': {
        'create-order-cancellation': ('POST', '/air/order_cancellations', False, True, True),
        'get-order-cancellation-by-id': ('GET', '/air/order_cancellations/{id}', False, False, True),
        'confirm-order-cancellation': ('POST', '/air/order_cancellations/{id}/actions/confirm', False, False, True),
    },
    'seat-maps': {'get-seat-maps': ('GET', '/air/seat_maps', True, False, True)},
}


def convert(directory, fetched_at):
    directory = Path(directory)
    references, paths, skipped = [], {}, []
    for filename, expected in SDK_HASHES.items():
        if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != expected:
            raise ValueError('SDK authority hash mismatch: ' + filename)
        references.append({'file': filename, 'sha256': expected,
                           'url': 'https://raw.githubusercontent.com/duffelhq/duffel-api-javascript/' + SDK_REVISION + '/' + filename.replace('__', '/')})
    for slug, expected in OPERATIONS.items():
        raw = (directory / (slug + '.html')).read_bytes()
        value = loads(''.join(NextData(raw).parts))['props']['pageProps']
        if value['version'] != 'v2' or value['resourceSlug'] != slug:
            raise ValueError('official resource/version mismatch')
        resource = value['resource']
        if resource['model'].get('type') != 'object' or not resource['model'].get('properties'):
            raise ValueError('explicit resource object schema missing')
        references.append({'url': REFERENCE + slug, 'sha256': hashlib.sha256(raw).hexdigest()})
        seen = set()
        for item in resource['operations']:
            name = item['slug']
            if name not in expected:
                skipped.append({'resource': slug, 'operation': name, 'reason': 'outside reviewed operation bindings'})
                continue
            method, path, array, body, complete_response = expected[name]
            if name in seen or item['endpoint'] != {'method': method, 'uri': ORIGIN + path}:
                raise ValueError('duplicate or changed official operation identity')
            seen.add(name)
            if item['requestHeaders'].get('Duffel-Version') != 'v2' or item['requestHeaders'].get('Accept') != 'application/json':
                raise ValueError('official wire version/media changed')
            if ('bodyDataSchema' in item) != body:
                raise ValueError('reviewed request body declaration changed')
            response = {'description': 'Successful HTTP response; fixed SDK accepts response.ok.'}
            if complete_response:
                response['content'] = {'application/json': {'schema': envelope(resource['model'], array)}}
            else:
                response['description'] += ' The view=itineraries response variant is not fully declared by the resource model; payload schema remains pending.'
            operation = {'summary': item['title'], 'description': item['description'],
                         'parameters': copy.deepcopy(item['requestParameters']),
                         'x-aisa-reference-url': REFERENCE + slug, 'responses': {'2XX': response}}
            if body:
                operation['requestBody'] = {'required': True, 'content': {'application/json': {
                    'schema': {'type': 'object', 'required': ['data'], 'properties': {'data': copy.deepcopy(item['bodyDataSchema'])}}}}}
            if method.lower() in paths.setdefault(path, {}):
                raise ValueError('duplicate output operation')
            paths[path][method.lower()] = operation
        if seen != set(expected):
            raise ValueError('reviewed official operation missing')
    document = {'openapi': '3.0.3', 'info': {'title': 'Official Duffel Flights references', 'version': 'v2'},
                'servers': [{'url': ORIGIN}], 'paths': paths}
    document['info']['x-aisa-source'] = {
        'kind': 'manual', 'url': REFERENCE + 'offer-requests', 'converter': CONVERTER,
        'fetched_at': fetched_at, 'content_hash': digest(document), 'references': references,
        'sdk_revision': SDK_REVISION, 'skipped_operations': skipped,
        'authority': 'Official HTML structured schemas plus pinned SDK wire envelopes; converted, not downloaded OpenAPI',
        'request_body_required_basis': 'All selected create methods have required SDK payload arguments; Client.request wraps payload in data.',
        'response_status_basis': 'Client.request accepts response.ok; no exact success status inferred.',
        'limitations': ['No schema types or required fields inferred from examples.',
                       'Offer-request create/get alternate view responses remain untyped.',
                       'Source declarations do not prove current execution compatibility.'],
    }
    return document


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--fetched-at', required=True)
    args = parser.parse_args()
    print(json.dumps(convert(args.directory, args.fetched_at), ensure_ascii=False, indent=2))
