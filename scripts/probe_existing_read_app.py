#!/usr/bin/env python3
"""Read three fixed GitHub objects with the existing Docs App credential.

This manual feature-branch probe has no qualification, publication or deployment
authority. Tokens stay in memory and only the fixed GitHub API receives them.
"""
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


API = 'https://api.github.com'
APP_ID = '4961124'
APP_SLUG = 'aisa-ci-read-bot'
SERVICES_RUN = 39044122592
SERVICES_HEAD = 'f8cfcb3978481cb714a8b79b48763054c076d8dc'
EXPORT_REVISION = '71cb2eaa4d4fe6b3434b32ded47d08e2ef95b06b'
LOCK_PATH = 'packages/apicontract/composer-inputs.lock.json'
LOCK_SHA256 = 'e677c15f73df26bfe7ae1521a7b91aa0fe47a81168f9cdf04ee9d9b1ca10e175'
LOCK_BLOB_SHA1 = 'c86b8a51134ec8182f9cd1d37d699ba23f3aed54'
DOCS_RUN = 39059640672
DOCS_HEAD = '5b0482e18f59334e9ec871be62d1abe61e7c4862'
PATHS = (
    '/repos/AIsa-team/AIsaServices/actions/runs/' + str(SERVICES_RUN),
    '/repos/AIsa-team/AIsaServices/contents/' + LOCK_PATH + '?ref=' + EXPORT_REVISION,
    '/repos/AIsa-team/docs/actions/runs/' + str(DOCS_RUN),
)
LIMIT = 512 << 10


def require(ok):
    if not ok:
        raise ValueError('Existing Docs Read App probe rejected')


def load(raw):
    require(type(raw) is bytes and 0 < len(raw) <= LIMIT)
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON')))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class FixedAPI:
    def __init__(self, token):
        require(type(token) is str and re.fullmatch('[A-Za-z0-9_]{20,4096}', token))
        self._token = token
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self._deadline = time.monotonic() + 60
        self._calls = 0

    def json(self, path):
        require(path in PATHS)
        self._calls += 1
        remaining = self._deadline - time.monotonic()
        require(self._calls <= 3 and remaining > 0)
        request = urllib.request.Request(API + path, method='GET', headers={
            'Authorization': 'Bearer ' + self._token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'aisa-existing-Docs-read-App-probe',
        })
        with self._opener.open(request, timeout=min(20, remaining)) as response:
            require(response.code == 200)
            length = response.headers.get('Content-Length')
            if length is not None:
                require(length.isdecimal() and 0 < int(length) <= LIMIT)
            reader = getattr(response, 'read1', None)
            require(callable(reader))
            chunks, amount = [], 0
            while amount <= LIMIT:
                remaining = self._deadline - time.monotonic()
                require(remaining > 0)
                sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                if sock is not None:
                    sock.settimeout(min(20, remaining))
                chunk = reader(min(65536, LIMIT + 1 - amount))
                if not chunk:
                    break
                chunks.append(chunk)
                amount += len(chunk)
            require(amount <= LIMIT and time.monotonic() < self._deadline)
            return load(b''.join(chunks))


def run_identity(value, run, head, repository, workflow):
    require(type(value) is dict and type(value.get('id')) is int and value['id'] == run
        and value.get('head_sha') == head and value.get('path') == workflow)
    repo = value.get('repository')
    require(type(repo) is dict and repo.get('full_name') == repository)


def probe(client, app_slug, app_id):
    require(app_slug == APP_SLUG and app_id == APP_ID)
    run = client.json(PATHS[0])
    run_identity(run, SERVICES_RUN, SERVICES_HEAD, 'AIsa-team/AIsaServices',
        '.github/workflows/api-contract-e2e.yml')
    require(run['repository'].get('private') is True and run.get('event') == 'workflow_dispatch'
        and run.get('status') == 'completed' and run.get('conclusion') == 'success')
    lock = client.json(PATHS[1])
    require(type(lock) is dict and lock.get('type') == 'file' and lock.get('path') == LOCK_PATH
        and lock.get('encoding') == 'base64' and lock.get('sha') == LOCK_BLOB_SHA1
        and type(lock.get('content')) is str and len(lock['content']) <= 32768)
    raw = base64.b64decode(''.join(lock['content'].split()), validate=True)
    require(type(lock.get('size')) is int and 0 < len(raw) <= 16384 and lock['size'] == len(raw)
        and hashlib.sha256(raw).hexdigest() == LOCK_SHA256
        and hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == LOCK_BLOB_SHA1)
    run_identity(client.json(PATHS[2]), DOCS_RUN, DOCS_HEAD, 'AIsa-team/docs',
        '.github/workflows/test-runtime-contracts.yml')
    return {'status': 'existing_Docs_Read_App_fixed_private_API_reads_passed',
        'scope': 'credential_read_probe_only_not_qualification',
        'Services_run_id': SERVICES_RUN, 'Docs_run_id': DOCS_RUN,
        'fixed_API_GETs': 3, 'token_exported': False, 'writes': 0,
        'source_qualification': False, 'formal': False, 'deploy': False}


def main():
    try:
        require(len(sys.argv) == 1)
        # Check public App identity before constructing any credential transport.
        slug, app_id = os.environ.get('READ_APP_SLUG'), os.environ.get('READ_APP_ID')
        require(slug == APP_SLUG and app_id == APP_ID)
        result = probe(FixedAPI(os.environ.get('GH_TOKEN')), slug, app_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        sys.stderr.write('Existing Docs Read App probe rejected; private diagnostics withheld\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
