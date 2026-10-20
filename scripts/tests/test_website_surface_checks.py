import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_surface_checks import (DISCOVERY_PAGE_RULES, RETIRED_PROVIDER_SLUGS, UNKNOWN_PROVIDER_SLUG,
                                   WEBSITE_LLMS_RULE_CONFLICTS, check_provider_pages, check_surfaces,
                                   check_website_surfaces, compare_discovery_page, compare_mcp_page,
                                   compare_sales_catalog, fixed_sales_catalog, fully_disabled_providers,
                                   mcp_page_prices, page_text)


def page(title, body=''):
    return ('<html><head><title>' + title + '</title><style>a{}</style></head><body>' + body + '</body></html>').encode()


class WebsiteSurfaceChecks(unittest.TestCase):
    def setUp(self):
        self.ref = 'a' * 40
        self.release = 'd' * 64
        self.spec = {'info': {'x-aisa-document': {'providers': {
            'example': {'document_hash': 'c' * 64}, 'legacy': {}}}}}
        self.expected_sales = {'docs_ref': self.ref, 'contract_release': self.release,
                               'provider_counts': {'example': 2, 'models': 1}, 'sha256': 'e' * 64}
        self.sales = {'docs_revision': self.ref, 'contract_release': self.release,
                      'providers': [{'id': 'example', 'endpoint_count': 2}, {'id': 'models', 'endpoint_count': 1}],
                      'operations': [{'operation_id': 'get_example_item', 'provider': 'example', 'quote': {'amount': '0.3'}},
                                     {'operation_id': 'post_example_search', 'provider': 'example', 'quote': {'amount': '0.012'}},
                                     {'operation_id': 'account', 'provider': 'models', 'quote': {'amount': '0'}}]}
        self.servers = {'serverCount': 3, 'toolCount': 10,
                        'entrypoints': [{'slug': 'aisa', 'kind': 'root'}, {'slug': 'seo', 'kind': 'category'},
                                        {'slug': 'finance', 'kind': 'category'}, {'slug': 'gtm', 'kind': 'module'}]}
        self.mcp_html = page('MCP - AIsa', '<p>5 meta tools</p><p>2 categories to pin</p><p>3 servers, one origin</p>'
                             '<p>10 tools reachable</p><p>4 tools listed &middot; 4 reachable</p>'
                             '<p>free &larr; $0.30 example_item &larr; $0.012 example_search &larr; $0.06 spent</p>'
                             '<script>var x = "99 tools";</script>')
        self.discovery = ('> ## Agent Instructions\n> - Direct HTTP calls follow the stricter rule, fallback: https://aisa.one/llms.txt\n\n'
                          '# Agent Discovery\n\n| **Agent setup guide** | llms.txt | `https://aisa.one/llms.txt` | rules |\n\n'
                          'Connect to `https://mcp.aisa.one/mcp` with OAuth first. Direct HTTP with an API key is the documented fallback.\n').encode()
        self.pages = {'example': (200, page('Example API - AIsa')), 'models': (200, page('Models - AIsa')),
                      UNKNOWN_PROVIDER_SLUG: (404, page('API Not Found - AIsa')),
                      RETIRED_PROVIDER_SLUGS[0]: (410, page('Gone'))}
        self.payloads = {'website-sales-catalog': json.dumps(self.sales).encode(),
                         'mcp-servers': json.dumps(self.servers).encode(),
                         'website-mcp-page': self.mcp_html, 'docs-discovery-page': self.discovery}

    def check(self, expected_sales='default'):
        return check_website_surfaces(self.spec, {self.ref},
            read_bytes=lambda name, url: self.payloads[name],
            read_page=lambda name, url: self.pages[name.split(':', 1)[1]],
            expected_sales=self.expected_sales if expected_sales == 'default' else expected_sales)

    def test_consistent_website_surfaces_pass(self):
        result = self.check()
        self.assertEqual(result['missing_inputs'], [])
        self.assertEqual(result['mismatches'], [])
        self.assertEqual(result['observations']['website-mcp-page']['example_prices'], 2)
        self.assertEqual(sorted(result['observations']['website-provider-pages']),
                         sorted(['example', 'models', UNKNOWN_PROVIDER_SLUG, RETIRED_PROVIDER_SLUGS[0]]))

    def test_soft_404_non_200_unknown_and_retired_pages_are_independent_codes(self):
        self.pages['example'] = (200, page('API Not Found - AIsa'))
        self.pages['models'] = (500, page('Error'))
        self.pages[UNKNOWN_PROVIDER_SLUG] = (200, page('API Not Found - AIsa'))
        self.pages[RETIRED_PROVIDER_SLUGS[0]] = (200, page('Image Generation via Chat API - AIsa'))
        result = self.check()
        self.assertEqual(result['mismatches'], [
            'website-provider-pages:example:not_found',
            'website-provider-pages:image-generation-via-chat:retired_page_returns_200',
            'website-provider-pages:models:http_500',
            'website-provider-pages:unknown-slug:soft_404_returns_200'])
        self.assertEqual(result['missing_inputs'], [])
        self.pages[UNKNOWN_PROVIDER_SLUG] = (200, page('Unknown Provider - AIsa'))
        self.assertIn('website-provider-pages:unknown-slug:unknown_slug_returns_200', self.check()['mismatches'])

    def test_one_same_origin_temporary_redirect_to_a_real_page_is_accepted(self):
        reads = []
        pages = {'https://aisa.one/api/twitter': (307, b'', 'https://aisa.one/api/twitter-api'),
                 'https://aisa.one/api/twitter-api': (200, page('Twitter API - AIsa')),
                 'https://aisa.one/api/financial': (307, b'', '/api/financial-api'),
                 'https://aisa.one/api/financial-api': (200, page('Financial API - AIsa')),
                 'https://aisa.one/api/scholar': (308, b'', 'scholar-api'),
                 'https://aisa.one/api/scholar-api': (200, page('Scholar API - AIsa')),
                 'https://aisa.one/api/relative-offsite': (307, b'', '//example.com/api/x'),
                 'https://aisa.one/api/relative-gone': (307, b'', '/api/relative-gone-card'),
                 'https://aisa.one/api/relative-gone-card': (200, page('API Not Found - AIsa')),
                 'https://aisa.one/api/empty-location': (307, b'', ''),
                 'https://aisa.one/api/gone': (308, b'', 'https://aisa.one/api/gone-card'),
                 'https://aisa.one/api/gone-card': (200, page('API Not Found - AIsa')),
                 'https://aisa.one/api/chain': (307, b'', 'https://aisa.one/api/chain-2'),
                 'https://aisa.one/api/chain-2': (307, b'', 'https://aisa.one/api/chain-3'),
                 'https://aisa.one/api/offsite': (307, b'', 'https://example.com/api/offsite'),
                 'https://aisa.one/api/http-origin': (307, b'', 'http://aisa.one/api/http-origin'),
                 'https://aisa.one/api/permanent': (301, b'', 'https://aisa.one/api/permanent-card'),
                 'https://aisa.one/api/' + UNKNOWN_PROVIDER_SLUG: (307, b'', 'https://aisa.one/api/unknown-card'),
                 'https://aisa.one/api/' + RETIRED_PROVIDER_SLUGS[0]: (404, page('API Not Found - AIsa'))}
        def read_page(name, url):
            reads.append((name, url))
            return pages[url]
        mismatches, missing, observations = check_provider_pages(
            {'twitter', 'financial', 'scholar', 'gone', 'chain', 'offsite', 'http-origin', 'permanent',
             'relative-offsite', 'relative-gone', 'empty-location'}, read_page)
        self.assertEqual(missing, [])
        self.assertEqual(mismatches, [
            'website-provider-pages:chain:redirect_target_not_found',
            'website-provider-pages:empty-location:redirect_offsite',
            'website-provider-pages:gone:redirect_target_not_found',
            'website-provider-pages:http-origin:redirect_offsite',
            'website-provider-pages:offsite:redirect_offsite',
            'website-provider-pages:permanent:http_301',
            'website-provider-pages:relative-gone:redirect_target_not_found',
            'website-provider-pages:relative-offsite:redirect_offsite'])
        self.assertEqual(observations['twitter'], {'status': 307, 'title': '', 'location': 'https://aisa.one/api/twitter-api',
                                                   'resolved_location': 'https://aisa.one/api/twitter-api',
                                                   'target': {'status': 200, 'title': 'Twitter API - AIsa'}})
        # Path-only and bare relative Locations, as Next.js emits them, resolve against the request URL.
        self.assertEqual(observations['financial']['resolved_location'], 'https://aisa.one/api/financial-api')
        self.assertEqual(observations['financial']['target']['status'], 200)
        self.assertEqual(observations['scholar']['resolved_location'], 'https://aisa.one/api/scholar-api')
        self.assertIn(('website-provider-page:financial:financial-api', 'https://aisa.one/api/financial-api'), reads)
        self.assertNotIn('target', observations['relative-offsite'])
        self.assertEqual(observations['offsite']['location'], 'https://example.com/api/offsite')
        self.assertNotIn('target', observations['offsite'])
        self.assertIn(('website-provider-page:twitter:twitter-api', 'https://aisa.one/api/twitter-api'), reads)
        self.assertNotIn('https://example.com/api/offsite', [url for _, url in reads])
        self.assertNotIn('https://aisa.one/api/chain-3', [url for _, url in reads])
        self.assertNotIn('https://aisa.one/api/unknown-card', [url for _, url in reads])
        self.assertEqual(observations[UNKNOWN_PROVIDER_SLUG]['status'], 307)

    def test_live_page_reader_returns_redirects_unfollowed_and_closes_the_response(self):
        import gc
        import http.server
        import threading
        import warnings
        from check_contract_revisions import read_public_page
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/api/twitter':
                    self.send_response(307)
                    self.send_header('Location', 'http://%s:%d/api/twitter-api' % self.server.server_address)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                elif self.path == '/api/financial':
                    self.send_response(307)
                    self.send_header('Location', '/api/twitter-api')  # path-only, as Next.js emits
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                elif self.path == '/api/twitter-api':
                    body = page('Twitter API - AIsa')
                    self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
                    self.wfile.write(body)
                else:
                    body = page('API Not Found - AIsa')
                    self.send_response(404); self.send_header('Content-Length', str(len(body))); self.end_headers()
                    self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = 'http://%s:%d' % server.server_address
            with warnings.catch_warnings():
                warnings.simplefilter('error', ResourceWarning)
                redirect = read_public_page(origin + '/api/twitter')
                relative = read_public_page(origin + '/api/financial')
                target = read_public_page(origin + '/api/twitter-api')
                missing = read_public_page(origin + '/api/nothing')
                gc.collect()
            self.assertEqual(redirect, (307, b'', origin + '/api/twitter-api'))
            self.assertEqual(relative, (307, b'', '/api/twitter-api'))
            self.assertEqual((target[0], target[2]), (200, None))
            self.assertIn(b'Twitter API - AIsa', target[1])
            self.assertEqual(missing[0], 404)
            self.assertIn(b'API Not Found', missing[1])
            with __import__('unittest.mock').mock.patch('public_surface_checks.PROVIDER_PAGE_ORIGIN', origin), \
                    __import__('unittest.mock').mock.patch('public_surface_checks.PROVIDER_PAGE', origin + '/api/{}'):
                mismatches, missing_inputs, observations = check_provider_pages(
                    {'twitter', 'financial'}, lambda name, url: read_public_page(url))
            self.assertEqual((mismatches, missing_inputs), ([], []))
            self.assertEqual(observations['twitter']['target']['status'], 200)
            self.assertEqual(observations['financial']['resolved_location'], origin + '/api/twitter-api')
            self.assertEqual(observations['financial']['target']['title'], 'Twitter API - AIsa')
        finally:
            server.shutdown()
            server.server_close()

    def test_provider_ids_come_from_publication_and_sales_union_and_unreadable_pages_are_missing(self):
        self.sales['providers'].append({'id': 'sales-only', 'endpoint_count': 1})
        self.payloads['website-sales-catalog'] = json.dumps(self.sales).encode()
        result = self.check()
        self.assertIn('website-provider-pages:sales-only:unavailable:KeyError', result['missing_inputs'])
        self.assertIn('website-sales-catalog:sales-only:provider_not_in_publication', result['mismatches'])
        self.assertNotIn('legacy', result['observations']['website-provider-pages'])
        del self.payloads['website-sales-catalog']
        result = self.check()
        self.assertIn('website-sales-catalog:unavailable:KeyError', result['missing_inputs'])
        self.assertIn('website-mcp-page:sales_quotes_unavailable', result['missing_inputs'])
        self.assertIn('example', result['observations']['website-provider-pages'])

    def test_mcp_page_counts_and_example_prices_must_match_live_catalogs(self):
        text = page_text(self.mcp_html)
        self.assertNotIn('99 tools', text)
        self.assertEqual(mcp_page_prices(text), [('0.30', 'example_item'), ('0.012', 'example_search')])
        self.assertEqual(compare_mcp_page(text, self.servers, self.sales)[0], [])
        for name, mutate, code in [
            ('tools', lambda s, c: s.update(toolCount=12), 'website-mcp-page:tool_count_mismatch'),
            ('servers', lambda s, c: s.update(serverCount=4), 'website-mcp-page:server_count_mismatch'),
            ('categories', lambda s, c: s['entrypoints'].append({'kind': 'category'}), 'website-mcp-page:category_count_mismatch'),
            ('price', lambda s, c: c['operations'][0]['quote'].update(amount='0.05'), 'website-mcp-page:example_item:example_price_mismatch'),
            ('unknown', lambda s, c: c['operations'].pop(1), 'website-mcp-page:example_search:example_operation_unknown'),
            ('ambiguous', lambda s, c: c['operations'].append({'operation_id': 'get_example_search', 'quote': {'amount': '0.012'}}), 'website-mcp-page:example_search:example_operation_ambiguous'),
            ('invalid', lambda s, c: s.update(toolCount='10'), 'mcp-servers:tool_count_invalid'),
        ]:
            with self.subTest(name=name):
                servers, sales = copy.deepcopy(self.servers), copy.deepcopy(self.sales)
                mutate(servers, sales)
                self.assertIn(code, compare_mcp_page(text, servers, sales)[0])
        errors, _ = compare_mcp_page('No numbers here.', self.servers, self.sales)
        self.assertEqual(errors, ['website-mcp-page:counts_unparsed'])

    def test_sales_catalog_revision_release_and_counts_are_independent(self):
        self.assertEqual(compare_sales_catalog(self.sales, self.expected_sales, {self.ref}), [])
        for name, mutate, code in [
            ('revision', lambda s: s.update(docs_revision='b' * 40), 'website-sales-catalog:docs_revision_mismatch'),
            ('release', lambda s: s.update(contract_release='f' * 64), 'website-sales-catalog:contract_release_mismatch'),
            ('count', lambda s: s['providers'][0].update(endpoint_count=3), 'website-sales-catalog:example:endpoint_count_mismatch'),
            ('missing', lambda s: s['providers'].pop(1), 'website-sales-catalog:models:provider_missing'),
            ('extra', lambda s: s['providers'].append({'id': 'other', 'endpoint_count': 1}), 'website-sales-catalog:other:provider_not_in_publication'),
            ('invalid', lambda s: s['providers'].append({'endpoint_count': 1}), 'website-sales-catalog:provider_record_invalid'),
        ]:
            with self.subTest(name=name):
                changed = copy.deepcopy(self.sales)
                mutate(changed)
                self.assertIn(code, compare_sales_catalog(changed, self.expected_sales, {self.ref}))
        result = self.check(expected_sales=None)
        self.assertIn('website-sales-catalog:fixed_formal_sales_view_missing', result['missing_inputs'])

    def test_fixed_sales_catalog_counts_non_disabled_operations_by_registry_provider(self):
        import subprocess
        import tempfile
        document = {'document': {'paths': {
            '/a': {'get': {'x-aisa-registry-provider': 'example'}, 'post': {'x-aisa-registry-provider': 'example', 'x-aisa-status': 'disabled'}},
            '/b': {'get': {'x-aisa-registry-provider': 'example'}, 'parameters': []},
            '/v1/models': {'get': {}}}}}
        raw = json.dumps(document).encode()
        import hashlib
        digest = hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs/publication').mkdir(parents=True)
            (root / 'docs/publication/sales-catalog.json').write_bytes(raw)
            pointer = {'status': 'passed', 'contract_release': self.release,
                       'sales_catalog': {'path': 'docs/publication/sales-catalog.json', 'sha256': digest},
                       'files_sha256': {'docs/publication/sales-catalog.json': digest}}
            (root / 'docs/publication/current.json').write_text(json.dumps(pointer))
            env = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t',
                   'HOME': directory, 'PATH': '/usr/bin:/bin'}
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True, env=env)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True, env=env)
            subprocess.run(['git', 'commit', '-q', '-m', 'fixture'], cwd=root, check=True, env=env)
            ref = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, env=env, text=True).strip()
            expected = fixed_sales_catalog(root, ref)
            self.assertEqual(expected['provider_counts'], {'example': 2, 'models': 1})
            self.assertEqual(expected['contract_release'], self.release)
            pointer['sales_catalog']['sha256'] = 'f' * 64
            (root / 'docs/publication/current.json').write_text(json.dumps(pointer))
            subprocess.run(['git', 'commit', '-q', '-am', 'unbound'], cwd=root, check=True, env=env)
            with self.assertRaises(ValueError):
                fixed_sales_catalog(root, 'HEAD')

    def test_discovery_page_rules_are_string_checks_on_the_body_only(self):
        self.assertEqual(compare_discovery_page(self.discovery), [])
        header_only = b'> https://aisa.one/llms.txt agent setup guide https://mcp.aisa.one/mcp oauth fallback\n\n# Page\n'
        self.assertEqual(set(compare_discovery_page(header_only)),
                         {'docs-discovery-page:' + code for code, (mode, _) in DISCOVERY_PAGE_RULES.items() if mode == 'required'})
        stale = self.discovery.replace(b'Agent setup guide', b'Product llms.txt') + \
            b'\nRequests use Bearer token authentication with an AIsa API key.\n'
        self.assertEqual(compare_discovery_page(stale), [
            'docs-discovery-page:agent_setup_guide_link_missing',
            'docs-discovery-page:http_key_primary_flow_present',
            'docs-discovery-page:product_llms_label_present'])
        self.payloads['docs-discovery-page'] = stale
        self.assertIn('docs-discovery-page:product_llms_label_present', self.check()['mismatches'])
        del self.payloads['docs-discovery-page']
        self.assertIn('docs-discovery-page:unavailable:KeyError', self.check()['missing_inputs'])

    def test_website_llms_rule_conflicts_are_reported_with_existing_llms_surface(self):
        digest = 'b' * 64
        llms = (f'Declared API contract: {digest}; immutable Docs revision: {self.ref}. '
                f'https://raw.githubusercontent.com/AIsa-team/docs/{self.ref}/openapi.yaml https://aisa.one/openapi.json\n'
                '- HTTP (D): `GET https://api.aisa.one/v1/models` with the Bearer header returns 200.\n'
                '- `401`: not signed in or invalid key. Redo step 1A or check the key.\n').encode()
        payloads = {'website-llms': llms}
        result = check_surfaces({'info': {}}, digest, {self.ref},
            read_bytes=lambda name, url: payloads[name], expected_requests={})
        for code in WEBSITE_LLMS_RULE_CONFLICTS:
            self.assertIn('website-llms:' + code, result['mismatches'])
        payloads['website-llms'] = llms.replace(b'returns 200', b'is only a transport check').replace(
            b'`401`: not signed in or invalid key', b'`401`: invalid key')
        result = check_surfaces({'info': {}}, digest, {self.ref},
            read_bytes=lambda name, url: payloads[name], expected_requests={})
        self.assertFalse([error for error in result['mismatches'] if error.startswith('website-llms:')])
        # The current guide's verify line (credits balance, "returns 200 with the balance") is not a conflict.
        payloads['website-llms'] = llms.replace(
            b'`GET https://api.aisa.one/v1/models` with the Bearer header returns 200.',
            b'`GET https://api.aisa.one/v1/credits/balance` with the Bearer header returns 200 with the balance. '
            b'`GET /v1/models` is only a transport check.')
        result = check_surfaces({'info': {}}, digest, {self.ref},
            read_bytes=lambda name, url: payloads[name], expected_requests={})
        self.assertNotIn('website-llms:http_verification_rule_conflict', result['mismatches'])

    def test_fully_disabled_providers_need_no_website_page(self):
        spec = {'paths': {
            '/off/a': {'post': {'x-aisa-provider': 'off', 'x-aisa-status': 'disabled'}},
            '/off/b': {'get': {'x-aisa-provider': 'off', 'x-aisa-status': 'disabled'}},
            '/mixed/a': {'get': {'x-aisa-provider': 'mixed', 'x-aisa-status': 'disabled'},
                         'post': {'x-aisa-provider': 'mixed'}},
            '/on/a': {'get': {'x-aisa-registry-provider': 'on'}},
        }}
        self.assertEqual(fully_disabled_providers(spec), {'off'})
        self.assertEqual(fully_disabled_providers({'info': {}}), set())


if __name__ == '__main__':
    unittest.main()
