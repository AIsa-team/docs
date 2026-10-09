import copy
from contextlib import redirect_stderr
from http.client import BadStatusLine
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch_runtime_release import (acquire, save, sha, PublicReader, NoRedirect,
                                   AcquisitionRejected, failure_diagnostic, main)


def encoded(value):
    return json.dumps(value, separators=(',', ':')).encode()


class PublicReleaseTests(unittest.TestCase):
    def test_cli_unexpected_protocol_error_omits_untrusted_exception_text(self):
        with tempfile.TemporaryDirectory() as temp:
            stderr = io.StringIO()
            with patch('fetch_runtime_release.acquire', side_effect=BadStatusLine('secret protocol line')):
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                    main(['--artifact-revision', 'a' * 64, '--compiler-revision', 'b' * 40,
                          '--output', str(Path(temp) / 'facts')])
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(stderr.getvalue(), 'Runtime acquisition rejected: BadStatusLine\n')
            self.assertFalse((Path(temp) / 'facts').exists())

    def test_failure_diagnostics_preserve_guard_reason_without_untrusted_details(self):
        self.assertEqual(failure_diagnostic(AcquisitionRejected('Manifest revision hash mismatch')),
                         'Manifest revision hash mismatch')
        for exc in (ValueError('secret response body'), KeyError('secret field'),
                    OSError('secret filename')):
            self.assertEqual(failure_diagnostic(exc), type(exc).__name__)

    def test_network_failure_reports_status_or_type_without_url_reason_or_body(self):
        for exc, expected in (
                (HTTPError('https://user:secret@example.test', 403, 'secret reason', {}, None), 'HTTP 403'),
                (URLError('secret reason'), 'URLError'),
                (TimeoutError('secret reason'), 'TimeoutError')):
            reader = PublicReader('https://api.aisa.one', float('inf'))
            reader.opener = Mock()
            reader.opener.open.side_effect = exc
            with self.assertRaises(AcquisitionRejected) as raised:
                reader('/public/api-contract/current')
            self.assertEqual(failure_diagnostic(raised.exception), 'Public metadata request failed: ' + expected)

    def fixture(self, mutate_index=None, mutate_current=None):
        compiler = 'b' * 40
        provider = {'info': {'x-aisa-document': {'facts_hash': 'c' * 64}}, 'paths': {}}
        index = {'pending_endpoints': [], 'pending_providers': [],
                 'providers': [{'id': 'example', 'facts_hash': 'c' * 64}],
                 'coverage': {'selected_endpoint_count': 1, 'projected_endpoint_count': 1,
                              'pending_endpoint_count': 0, 'inventory_endpoint_count': 2}}
        if mutate_index:
            mutate_index(index)
        payload = {'index.json': encoded(index), 'providers/example.json': encoded(provider)}
        files = [{'name': name, 'media_type': 'application/json', 'sha256': sha(raw)} for name, raw in sorted(payload.items())]
        manifest = {'schema_version': 1, 'source_digest': 'a' * 64, 'compiler_revision': compiler, 'files': files}
        revision = sha(encoded(manifest))
        current = {**manifest, 'artifact_revision': revision, 'fresh': True, 'generation': 3, 'published_generation': 3}
        if mutate_current:
            mutate_current(current)
        calls = []
        def reader(path):
            calls.append(path)
            if path == '/public/api-contract/current':
                return encoded(current), {}
            if path == '/info/apis/category':
                return encoded({'apis': [{'id': 'example'}]}), {}
            prefix = '/public/api-contract/releases/' + revision + '/'
            self.assertTrue(path.startswith(prefix))
            raw = payload[path[len(prefix):]]
            return raw, {'etag': '"' + sha(raw) + '"'}
        return revision, compiler, reader, current, payload, calls

    def test_real_protocol_manifest_and_flat_cli_export_preserve_raw_bytes(self):
        revision, compiler, reader, current, payload, calls = self.fixture()
        result = acquire(revision, compiler, reader)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'facts'
            save(output, result)
            self.assertEqual((output / 'example.json').read_bytes(), payload['providers/example.json'])
            self.assertEqual((output / 'providers/example.json').read_bytes(), payload['providers/example.json'])
            self.assertEqual((output / 'index.json').read_bytes(), payload['index.json'])
            receipt = json.loads((output / 'acquisition-receipt.json').read_text())
            self.assertIn('outside immutable release', receipt['category_scope'])
            with self.assertRaises(ValueError):
                save(output, result)
        self.assertEqual(calls.count('/public/api-contract/current'), 2)
        self.assertEqual(calls.count('/info/apis/category'), 2)

    def test_wrong_pins_stale_generation_and_manifest_corruption_fail_before_files(self):
        for mutation in (lambda c: c.update(fresh=False), lambda c: c.update(generation=4),
                         lambda c: c.update(compiler_revision='d' * 40),
                         lambda c: c['files'][0].update(sha256='e' * 64),
                         lambda c: c['files'].append(copy.deepcopy(c['files'][0]))):
            revision, compiler, reader, _, _, calls = self.fixture(mutate_current=mutation)
            with self.assertRaises(ValueError):
                acquire(revision, compiler, reader)
            self.assertEqual(len(calls), 1)

    def test_file_etag_and_payload_corruption_fail(self):
        for corrupt_body in (False, True):
            revision, compiler, original, *_ = self.fixture()
            def reader(path):
                raw, headers = original(path)
                if '/releases/' in path:
                    return (raw + b' ' if corrupt_body else raw), {'etag': '"wrong"'}
                return raw, headers
            with self.assertRaises(ValueError):
                acquire(revision, compiler, reader)

    def test_exact_weak_sha_etag_is_accepted_with_unchanged_bytes(self):
        revision, compiler, original, *_ = self.fixture()
        def reader(path):
            raw, headers = original(path)
            if '/releases/' in path:
                headers = {'etag': 'W/' + headers['etag']}
            return raw, headers
        result = acquire(revision, compiler, reader)
        self.assertEqual(result[-1]['artifact_revision'], revision)

    def test_weak_tag_never_replaces_exact_sha_or_body_check(self):
        variants = ('wrong-sha', 'unquoted', 'lowercase', 'list', 'body-mismatch')
        for variant in variants:
            revision, compiler, original, *_ = self.fixture()
            def reader(path):
                raw, headers = original(path)
                if '/releases/' in path:
                    tag = headers['etag']
                    malformed = {'wrong-sha': 'W/"wrong"', 'unquoted': 'W/' + tag.strip('"'),
                                 'lowercase': 'w/' + tag, 'list': 'W/' + tag + ', ' + tag,
                                 'body-mismatch': 'W/' + tag}
                    headers = {'etag': malformed[variant]}
                    if variant == 'body-mismatch':
                        raw += b' '
                return raw, headers
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                acquire(revision, compiler, reader)

    def test_pending_or_incomplete_or_unbound_index_cannot_export(self):
        for mutation in (lambda i: i.update(pending_endpoints=[{'id': 1}]),
                         lambda i: i['coverage'].update(selected_endpoint_count=2),
                         lambda i: i['providers'][0].update(facts_hash='d' * 64),
                         lambda i: i.update(providers=[]),
                         lambda i: i['providers'][0].update(id='../secret')):
            revision, compiler, reader, *_ = self.fixture(mutate_index=mutation)
            with self.assertRaises(ValueError):
                acquire(revision, compiler, reader)

    def test_moving_current_or_category_rejected_after_download(self):
        for move_current in (False, True):
            revision, compiler, original, current, *_ = self.fixture()
            category_reads, current_reads = 0, 0
            def reader(path):
                nonlocal category_reads, current_reads
                raw, headers = original(path)
                if path.endswith('/current'):
                    current_reads += 1
                    if move_current and current_reads == 2:
                        return encoded({**current, 'generation': 4, 'published_generation': 4}), headers
                if path.endswith('/category'):
                    category_reads += 1
                    if not move_current and category_reads == 2:
                        return encoded({'apis': []}), headers
                return raw, headers
            with self.assertRaises(ValueError):
                acquire(revision, compiler, reader)

    def test_only_category_cache_timestamp_can_change(self):
        for change in ('cached_at', 'provider_price', 'extra_field', 'invalid_cached_at',
                       'one_to_true', 'zero_to_false'):
            revision, compiler, original, *_ = self.fixture()
            reads = 0
            def reader(path):
                nonlocal reads
                raw, headers = original(path)
                if path == '/info/apis/category':
                    reads += 1
                    category = json.loads(raw)
                    category['cached_at'] = 100 + reads
                    if change == 'one_to_true':
                        category['apis'][0]['pricing'] = {'price': 1 if reads == 1 else True}
                    elif change == 'zero_to_false':
                        category['apis'][0]['pricing'] = {'price': 0 if reads == 1 else False}
                    if reads == 2 and change == 'provider_price':
                        category['apis'][0]['pricing'] = {'price': 1}
                    elif reads == 2 and change == 'extra_field':
                        category['new_field'] = True
                    elif reads == 2 and change == 'invalid_cached_at':
                        category['cached_at'] = True
                    raw = encoded(category)
                return raw, headers
            with self.subTest(change=change):
                if change == 'cached_at':
                    result = acquire(revision, compiler, reader)
                    self.assertNotEqual(result[-1]['category_sha256'], result[-1]['category_after_sha256'])
                    self.assertEqual(result[-1]['category_ignored_volatile_fields'], ['cached_at'])
                else:
                    with self.assertRaises(ValueError):
                        acquire(revision, compiler, reader)

    def test_network_boundary_rejects_credentials_http_redirects_and_expired_deadline(self):
        for origin in ('http://api.aisa.one', 'https://user:secret@api.aisa.one',
                       'https://api.aisa.one/path', 'https://api.aisa.one?key=secret'):
            with self.assertRaises(ValueError):
                PublicReader(origin, 0)
        reader = PublicReader('https://api.aisa.one', 0)
        with self.assertRaises(ValueError):
            reader('/public/api-contract/current')
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None)


if __name__ == '__main__':
    unittest.main()
