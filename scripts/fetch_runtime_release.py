#!/usr/bin/env python3
"""Read a pinned, fresh public Runtime release; never synthesize facts or approval."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from runtime_contract_artifact import member_name, file_limit, validate_canonical_files

MAX_FILE = 8 << 20
MAX_TOTAL = 64 << 20
HEX64 = re.compile(r'[0-9a-f]{64}')
HEX40 = re.compile(r'[0-9a-f]{40}')
PROVIDER = re.compile(r'[a-z0-9][a-z0-9_.-]*')
REQUEST_TIMEOUT = 30
REQUEST_ATTEMPTS = 3


class AcquisitionRejected(ValueError):
    """A controlled diagnostic containing no response body or credentials."""


def failure_diagnostic(exc):
    return str(exc) if isinstance(exc, AcquisitionRejected) else type(exc).__name__


def require(condition, message):
    if not condition:
        raise AcquisitionRejected(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'Duplicate JSON key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(AcquisitionRejected('Non-finite JSON')))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise AcquisitionRejected('HTTP redirect rejected')


class PublicReader:
    def __init__(self, origin, deadline):
        parsed = urlsplit(origin)
        require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and
                not parsed.password and not parsed.query and not parsed.fragment and
                parsed.path in ('', '/'), 'Expected a public HTTPS origin')
        self.origin, self.deadline = origin.rstrip('/'), deadline
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def __call__(self, path):
        match = re.fullmatch(r'/public/api-contract/releases/[0-9a-f]{64}/(contracts/(?:openapi|manifest|readiness)\.json)', path)
        limit = file_limit(match[1], MAX_FILE) if match else MAX_FILE
        request = Request(self.origin + path, headers={'Accept': 'application/json'})
        target = public_target(path)
        for attempt in range(1, REQUEST_ATTEMPTS + 1):
            remaining = self.deadline - time.monotonic()
            require(remaining > 0, 'Acquisition deadline exceeded')
            try:
                with self.opener.open(request, timeout=min(REQUEST_TIMEOUT, remaining)) as response:
                    require(response.status == 200, 'Expected HTTP 200')
                    raw = response.read(limit + 1)
                    headers = dict((k.lower(), v) for k, v in response.headers.items())
            except HTTPError as exc:
                failure = 'HTTP ' + str(exc.code)
                retry = exc.code in (429, 500, 502, 503, 504)
                exc.close()
            except (URLError, TimeoutError, OSError) as exc:
                failure = type(exc).__name__
                reason = exc.reason if isinstance(exc, URLError) else exc
                retry = isinstance(reason, (TimeoutError, ConnectionError)) or (
                    isinstance(reason, socket.gaierror) and reason.errno == socket.EAI_AGAIN)
            else:
                require(time.monotonic() <= self.deadline, 'Acquisition deadline exceeded')
                require(len(raw) <= limit, 'Public file exceeds byte limit')
                if '110' in headers.get('warning', ''):
                    raise AcquisitionRejected(stale_diagnostic(target, raw))
                return raw, headers
            if not retry or attempt == REQUEST_ATTEMPTS:
                raise AcquisitionRejected(
                    f'Public metadata request failed: {failure} (target={target}, attempts={attempt})') from None
            delay = 0.5 * attempt
            require(self.deadline - time.monotonic() > delay, 'Acquisition deadline exceeded')
            print(f'Runtime acquisition retry: target={target}, attempt={attempt}, failure={failure}', file=sys.stderr)
            time.sleep(delay)


def public_target(path):
    """Name only known public protocol members, never origins or arbitrary URLs."""
    if path == '/public/api-contract/current':
        return 'current'
    if path == '/info/apis/category':
        return 'category'
    match = re.fullmatch(r'/public/api-contract/releases/[0-9a-f]{64}/(.+)', path)
    if match and member_name(match[1]):
        return 'release/' + match[1]
    return 'public-file'


def stale_diagnostic(target, raw):
    """Expose bounded public release identities without logging response bodies."""
    fields = ['target=' + target]
    if target == 'current':
        try:
            current = decode(raw)
        except (ValueError, UnicodeError, TypeError):
            current = None
        if isinstance(current, dict):
            if type(current.get('fresh')) is bool:
                fields.append('fresh=' + str(current['fresh']).lower())
            for key in ('generation', 'published_generation'):
                value = current.get(key)
                if type(value) is int and 0 <= value < 2**64:
                    fields.append(f'{key}={value}')
            for key, pattern in (('compiler_revision', HEX40), ('artifact_revision', HEX64)):
                value = current.get(key)
                if isinstance(value, str) and pattern.fullmatch(value):
                    fields.append(key + '=' + value)
    return 'Stale public metadata rejected (' + ', '.join(fields) + ')'


def validate_current(current, revision, compiler):
    require(isinstance(current, dict) and current.get('artifact_revision') == revision and
            current.get('compiler_revision') == compiler and
            HEX64.fullmatch(str(current.get('source_digest', ''))) and
            current.get('fresh') is True, 'Current release does not match fresh pinned revision')
    generation = current.get('generation')
    require(type(generation) is int and generation >= 0 and
            type(current.get('published_generation')) is int and
            generation == current['published_generation'], 'Current generation is not published')
    files = current.get('files')
    require(isinstance(files, list) and 1 <= len(files) <= 512, 'Invalid file manifest')
    names = []
    for row in files:
        require(isinstance(row, dict) and set(row) == {'name', 'media_type', 'sha256'}, 'Unsupported manifest entry')
        name = row['name']
        require(member_name(name) and row['media_type'] == 'application/json' and
                HEX64.fullmatch(str(row['sha256'])), 'Invalid manifest member')
        names.append(name)
    require(names == sorted(set(names)) and 'index.json' in names, 'Manifest is not ordered and unique')
    # Exact Go contractpublication.manifest / File field order; fields are ASCII.
    manifest = {'schema_version': 1, 'source_digest': current['source_digest'],
                'compiler_revision': compiler, 'files': [
                    {key: row[key] for key in ('name', 'media_type', 'sha256')} for row in files]}
    require(sha(json.dumps(manifest, separators=(',', ':')).encode()) == revision,
            'Manifest revision hash mismatch')


def category_content(raw):
    category = decode(raw)
    require(isinstance(category, dict) and isinstance(category.get('apis'), list),
            'Invalid live category response')
    # Runtime api_catalog_handlers.go stamps cache construction time independently
    # of catalog content. Every other field and ordered API row must still match.
    if 'cached_at' in category:
        require(type(category['cached_at']) is int and category['cached_at'] >= 0,
                'Invalid category cache timestamp')
    content = {key: value for key, value in category.items() if key != 'cached_at'}
    # Canonical JSON keeps booleans distinct from numbers (True == 1 in Python).
    return json.dumps(content, sort_keys=True, separators=(',', ':')).encode()


def validate_release_files(contents):
    """Validate the closed immutable facts graph without performing acquisition."""
    index = decode(contents['index.json'])
    require(index.get('pending_endpoints') == [] and index.get('pending_providers') == [],
            'Runtime release still has pending projections')
    coverage = index.get('coverage', {})
    selected, projected = coverage.get('selected_endpoint_count'), coverage.get('projected_endpoint_count')
    require(type(selected) is int and selected >= 0 and type(projected) is int and selected == projected and
            type(coverage.get('pending_endpoint_count')) is int and
            coverage['pending_endpoint_count'] == 0, 'Incomplete Runtime selected coverage')
    providers = index.get('providers')
    require(isinstance(providers, list), 'Missing Runtime provider index')
    expected = {'index.json'}
    for provider in providers:
        key = provider.get('id', '')
        require(isinstance(key, str) and PROVIDER.fullmatch(key) and key not in
                {'index', 'category', 'current-before', 'current-after', 'acquisition-receipt'},
                'Invalid or reserved provider identity')
        name = 'providers/' + key + '.json'
        require(name not in expected and name in contents, 'Provider graph mismatch')
        expected.add(name)
        meta = decode(contents[name]).get('info', {}).get('x-aisa-document', {})
        require(HEX64.fullmatch(str(provider.get('facts_hash', ''))) and
                meta.get('facts_hash') == provider['facts_hash'], 'Index/provider facts hash mismatch')
    require(expected == set(contents), 'Manifest contains an unindexed provider')
    return index, providers, selected


def facts_members(contents):
    return {name: raw for name, raw in contents.items() if not name.startswith('contracts/')}


def validate_artifact_files(contents, current, *, canonical_result=None):
    result = validate_canonical_files(contents, current)
    if canonical_result is not None and result is not None:
        canonical_result.update(result)
    return validate_release_files(facts_members(contents))


def acquire(revision, compiler, reader):
    require(HEX64.fullmatch(revision) and HEX40.fullmatch(compiler), 'Full artifact and compiler revisions required')
    started = datetime.now(timezone.utc).isoformat()
    before_raw, _ = reader('/public/api-contract/current')
    before = decode(before_raw)
    validate_current(before, revision, compiler)
    contents, total = {}, 0
    for row in before['files']:
        raw, headers = reader('/public/api-contract/releases/' + revision + '/' + row['name'])
        total += len(raw)
        require(len(raw) <= file_limit(row['name'], MAX_FILE) and total <= MAX_TOTAL, 'Release byte limit exceeded')
        tag = '"' + row['sha256'] + '"'
        # Public intermediaries may weaken the validator without changing bytes.
        # Accept only this exact manifest SHA; body hashing remains mandatory.
        require(sha(raw) == row['sha256'] and headers.get('etag') in (tag, 'W/' + tag),
                'Immutable file hash or ETag mismatch')
        decode(raw)
        contents[row['name']] = raw
    canonical_validation = {}
    index, providers, selected = validate_artifact_files(contents, before, canonical_result=canonical_validation)
    coverage = index['coverage']
    category, _ = reader('/info/apis/category')
    catalog = category_content(category)
    category_after, _ = reader('/info/apis/category')
    require(catalog == category_content(category_after), 'Live category changed during acquisition')
    after_raw, _ = reader('/public/api-contract/current')
    after = decode(after_raw)
    validate_current(after, revision, compiler)
    require(before == after, 'Current Runtime release changed during acquisition')
    receipt = {'schema_version': 1, 'artifact_revision': revision, 'compiler_revision': compiler,
               'source_digest': before['source_digest'], 'generation': before['generation'],
               'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
               'fresh_before_and_after': True, 'manifest_files': before['files'],
               'inventory_endpoint_count': coverage.get('inventory_endpoint_count'),
               'selected_endpoint_count': selected, 'provider_count': len(providers),
               'category_sha256': sha(category), 'category_after_sha256': sha(category_after),
               'category_content_sha256': sha(catalog),
               'category_ignored_volatile_fields': ['cached_at'],
               'category_scope': 'live unversioned category content, stable twice except cache construction timestamp; outside immutable release manifest',
               'scope': 'actual public Runtime input acquisition only; no Docs readiness or baseline approval'}
    if canonical_validation:
        receipt['canonical_validation'] = canonical_validation
    return contents, category, before_raw, after_raw, receipt


def save(output, acquisition):
    require(not output.exists() and not output.is_symlink(), 'Output directory already exists')
    contents, category, before, after, receipt = acquisition
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.runtime-release-', dir=output.parent))
    try:
        for name, raw in contents.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            if name.startswith('providers/'):
                # Existing Docs CLI takes flat provider documents. Keep raw bytes.
                (temporary / Path(name).name).write_bytes(raw)
        (temporary / 'category.json').write_bytes(category)
        (temporary / 'current-before.json').write_bytes(before)
        (temporary / 'current-after.json').write_bytes(after)
        (temporary / 'acquisition-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        require(not output.exists() and not output.is_symlink(), 'Output directory appeared during acquisition')
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://api.aisa.one')
    parser.add_argument('--artifact-revision')
    parser.add_argument('--compiler-revision')
    parser.add_argument('--current', action='store_true', help='Discover current pins, then use the same strict immutable acquisition')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(not args.output.exists() and not args.output.is_symlink(), 'Output directory already exists')
        require((args.current and not args.artifact_revision and not args.compiler_revision) or
                (not args.current and args.artifact_revision and args.compiler_revision),
                'Choose current discovery or both explicit revision pins')
        reader = PublicReader(args.base_url, time.monotonic() + 180)
        revision, compiler = args.artifact_revision, args.compiler_revision
        discovered = None
        if args.current:
            discovered = decode(reader('/public/api-contract/current')[0])
            revision, compiler = discovered.get('artifact_revision', ''), discovered.get('compiler_revision', '')
            validate_current(discovered, revision, compiler)
        result = acquire(revision, compiler, reader)
        if discovered is not None:
            require(decode(result[2]) == discovered, 'Current release changed after discovery')
        save(args.output, result)
        print(json.dumps(result[-1], sort_keys=True))
    except Exception as exc:
        parser.exit(1, 'Runtime acquisition rejected: ' + failure_diagnostic(exc) + '\n')


if __name__ == '__main__':
    main()
