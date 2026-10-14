#!/usr/bin/env python3
"""Collect unauthenticated MPP challenges, never credentials or paid requests.

Run after backend mpp-catalog verify and refreshing runtime OpenAPI sources.
"""
import argparse
import base64
import datetime
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from payment_catalog import USD_ASSETS, digest, key, local_file

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_challenge(header):
    if not header or not header.startswith('Payment '):
        raise ValueError('No MPP Payment challenge')
    fields = dict(re.findall(r'([A-Za-z]+)="([^"\\]*)"', header))
    raw = fields['request']
    request = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
    chain = request.get('methodDetails', {}).get('chainId', request.get('chainId'))
    chain = int(chain)
    offer = {k: fields[k] for k in ('method', 'intent')}
    offer.update({k: request[k] for k in ('amount', 'currency')})
    offer['description'] = fields.get('description', 'AIsa API request')
    decimals = USD_ASSETS.get((chain, offer['currency'].lower()))
    if decimals is None or not fields.get('expires'):
        raise ValueError('Unreviewed chain/currency or missing expiry')
    return {'offer': offer, 'chain_id': chain, 'decimals': decimals, 'expires': fields['expires']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-plan', type=Path, required=True)
    parser.add_argument('--allowlist', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--server', required=True, help='Explicit staging or production HTTPS origin')
    parser.add_argument('--environment', choices=('staging', 'production'), required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'https://[a-zA-Z0-9.-]+(?::[0-9]+)?', args.server):
        parser.error('server must be an HTTPS origin with no path or credentials')
    if args.environment == 'production' and args.server != 'https://api.aisa.one':
        parser.error('unexpected production origin')
    if args.output.exists():
        parser.error('output exists; preserve previous evidence and choose a new file')
    plan_raw = args.runtime_plan.read_bytes()
    plan = json.loads(plan_raw)
    allowed = {key(op): op for op in json.loads(args.allowlist.read_bytes())}
    result = {'version': 2, 'environment': args.environment, 'server': args.server,
              'runtime_plan_sha256': digest(plan_raw), 'operations': [],
              'verification': '402 challenge probes only; no payment submitted, no execution or settlement claim.'}
    opener = urllib.request.build_opener(NoRedirect())
    for quote in plan['entries']:
        if quote.get('blocked_reason'):
            continue
        op = quote['operation']
        if key(op) not in allowed or op['provider'] == 'tikhub' or op['method'] not in ('GET', 'POST'):
            raise ValueError('Runtime plan contains an operation outside allowlist')
        spec = allowed[key(op)]
        raw = local_file(ROOT, spec['source']).read_bytes()
        row = {k: op[k] for k in ('provider', 'method', 'path')}
        row.update({'source_sha256': digest(raw), 'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        try:
            source_op = json.loads(raw)['paths'][op['path']][op['method'].lower()]
            if source_op.get('x-aisa-status') != 'enabled' or source_op.get('x-aisa-capabilities', {}).get('mpp') is not True:
                raise ValueError('Refresh runtime docs after enabling this method')
            # Authentication returns the challenge before body validation/upstream.
            # Template placeholders need only route matching; these are not paid inputs.
            path = re.sub(r'\{[^{}]+\}', 'discovery', op['path'])
            request = urllib.request.Request(args.server + path, method=op['method'],
                                             headers={'X-MPP-Discovery': 'true', 'Accept': 'application/json'},
                                             data=b'{}' if op['method'] == 'POST' else None)
            try:
                with opener.open(request, timeout=20) as response:
                    status, headers = response.status, response.headers
            except urllib.error.HTTPError as response:
                status, headers = response.code, response.headers
                response.close()
            if status != 402:
                raise ValueError('Expected 402; received HTTP ' + str(status))
            row.update(parse_challenge(headers.get('WWW-Authenticate')))
            row['status'] = status
            if int(row['offer']['amount']) != quote['price_micros_usd']:
                raise ValueError('Challenge differs from runtime six-decimal USD quote')
        except (ValueError, KeyError, urllib.error.URLError, TimeoutError) as exc:
            row['error'] = str(exc)
        result['operations'].append(row)
        print(op['provider'], op['method'], op['path'], row.get('error', '402 matched'))
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
