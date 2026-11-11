"""Customer pricing through the actual dev acquisition/generation entrypoint."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_dev_runtime as dev
from runtime_localize_openapi_zh import split_frontmatter
import test_dev_runtime


# Public dev Adyntel declaration: the supplier rate is not a request price.
ADYNTEL_PRICING = {
    'cost_contract': 'response_units', 'customer_multiplier': 1.0,
    'customer_pricing': 'provider_cost_multiplier', 'estimate_source': 'unavailable',
    'estimate_unavailable_reason': 'reference_request_unavailable',
    'evidence_source': 'response_header', 'unit': 'provider_credit', 'unit_rate_usd': .000001,
}
OLD_SUMMARY = ('<!-- aisa-pricing:start -->\n'
               'A request reference price is not currently available; use a request quote where supported. '
               'Declared unit rate: $0.000001 USD per provider_credit. '
               'Account-specific pricing and final settlement may differ.\n<!-- aisa-pricing:end -->')


class DevCustomerPricingTests(unittest.TestCase):
    def test_retained_operation_is_clean_before_hashing_and_full_regeneration_is_stable(self):
        _, _, reader = test_dev_runtime.DevRuntimeTests().fixture()
        files = dev.acquire(reader)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
            (root / 'docs.json').write_text('{"navigation":{"languages":[]}}')

            def write(outputs):
                for name, raw in outputs.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)

            write(dev.generate(root, files)[0])
            spec = root / 'openapi/similarweb.json'
            document = json.loads(spec.read_text())
            retired = copy.deepcopy(document['paths']['/apis/v1/similarweb/test']['post'])
            retired.update(operationId='historic_identity', description='Old ads.\n\n' + OLD_SUMMARY)
            for key in ('x-aisa-identity', 'x-aisa-runtime-operation'):
                retired.pop(key, None)
            retired['x-aisa-pricing'] = copy.deepcopy(ADYNTEL_PRICING)
            document['paths']['/apis/v1/similarweb/retired'] = {'post': retired}
            spec.write_text(json.dumps(document))
            page = root / 'api-reference/similarweb/retired.mdx'
            page.write_text('---\nopenapi: "openapi/similarweb.json POST /apis/v1/similarweb/retired"\n'
                            'x-aisa-operation-id: "historic_identity"\n---\n')
            outputs, _ = dev.generate(root, files)
            write(outputs)
            repeated, _ = dev.generate(root, files)
            for prefix in ('', 'zh/'):
                name = 'openapi/' + prefix + 'similarweb.json'
                operation = json.loads(outputs[name])['paths']['/apis/v1/similarweb/retired']['post']
                self.assertEqual(operation['description'], 'Old ads.')
                self.assertEqual(operation['x-aisa-status'], 'disabled')
                self.assertEqual(operation['x-aisa-pricing'], ADYNTEL_PRICING)
                self.assertEqual(outputs[name], repeated[name])
                name = prefix + 'api-reference/similarweb/retired.mdx'
                self.assertNotIn('aisa-pricing:', outputs[name].decode())
                self.assertNotIn('provider_credit', outputs[name].decode())
                self.assertEqual(outputs[name], repeated[name])
            self.assertEqual(outputs['docs/dev-runtime.json'], repeated['docs/dev-runtime.json'])

    def test_retained_blocked_and_absent_references_clean_both_description_surfaces(self):
        # Dev retains these pages even when they cannot be freshly composed.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'navigation': {'pages': []}}
            documents = {}
            for provider, status in [('absent', 'enabled'), ('blocked', 'enabled'), ('current', 'disabled')]:
                for prefix in ('', 'zh/'):
                    spec = root / ('openapi/' + prefix + provider + '.json')
                    spec.parent.mkdir(parents=True, exist_ok=True)
                    operation = {'operationId': provider, 'description': 'Find ads.\n\n' + OLD_SUMMARY,
                                 'x-aisa-status': status, 'x-aisa-pricing': copy.deepcopy(ADYNTEL_PRICING),
                                 'x-aisa-constraints': {'notes': ['Request note']}}
                    document = {'info': {'x-aisa-document': {'document_hash': 'historical'}},
                                'paths': {'/ads': {'get': operation}}}
                    spec.write_text(json.dumps(document))
                    documents[spec] = copy.deepcopy(document)
                    page = root / (prefix + 'api-reference/' + provider + '/ads.mdx')
                    page.parent.mkdir(parents=True, exist_ok=True)
                    page.write_text('---\ntitle: Ads\ndescription: ' + json.dumps(OLD_SUMMARY)
                                    + '\nopenapi: "' + spec.relative_to(root).as_posix() + ' GET /ads"\n---\n\nExample.\n'
                                    + '\n{/* aisa-contract-details:start */}\n\nOld provider_credit rate\n{/* aisa-contract-details:end */}\n')
                    config['navigation']['pages'].append(page.relative_to(root).with_suffix('').as_posix())
            (root / 'docs.json').write_text(json.dumps(config))
            summary = {'current': {}, 'blocked': {'blocked': 'unresolved source'}}
            for repeat in range(2):
                aggregate = {'info': {}, 'paths': {}}
                dev.scope_presentation(root, aggregate, summary)
                for spec, before in documents.items():
                    document = json.loads(spec.read_text())
                    expected = copy.deepcopy(before)
                    expected['paths']['/ads']['get']['description'] = 'Find ads.'
                    self.assertEqual(document, expected)
                for page in root.glob('**/*.mdx'):
                    text = page.read_text()
                    self.assertIn('Example.', text)
                    self.assertIn('Request note', text)
                    self.assertNotIn('provider_credit', text)
                    self.assertNotIn('aisa-pricing:', text)
                    self.assertNotIn('0.000001', text)
                    language = 'zh' if '/zh/' in str(page) else 'en'
                    self.assertEqual(text.count(dev.HISTORIC_NOTES[language]), 1)
                    heading = '## 费用与请求规则' if language == 'zh' else '## Cost and request rules'
                    self.assertEqual(text.count(heading), 1)
                snapshot = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                if repeat:
                    self.assertEqual(snapshot, previous)
                previous = snapshot

    def test_adyntel_pattern_has_one_price_block_and_no_internal_prices_after_regeneration(self):
        fixture = test_dev_runtime.DevRuntimeTests()
        values, _, reader = fixture.fixture()
        document = values['/info/openapi/similarweb.json']
        operation = document['paths']['/apis/v1/similarweb/test']['post']
        operation['description'] = 'Find ads for a company.\n\n' + OLD_SUMMARY
        operation['x-aisa-pricing'] = copy.deepcopy(ADYNTEL_PRICING)
        original = copy.deepcopy(document)
        files = dev.acquire(reader)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
            config = {'navigation': {'languages': [
                {'language': language, 'tabs': [{'tab': tab, 'groups': []}]}
                for language, tab in [('en', 'API Reference'), ('zh', 'API 参考')]]}}
            (root / 'docs.json').write_text(json.dumps(config))
            for prefix in ('', 'zh/'):
                page = root / (prefix + 'api-reference/similarweb/published_identity.mdx')
                page.parent.mkdir(parents=True)
                page.write_text('---\ntitle: Find ads\ndescription: ' + json.dumps(OLD_SUMMARY) + '\n---\n')
            outputs, report = dev.generate(root, files)
            self.assertEqual(report['status'], 'generated')
            for prefix, heading in [('', '## Cost and request rules'), ('zh/', '## 费用与请求规则')]:
                page = outputs[prefix + 'api-reference/similarweb/published_identity.mdx'].decode()
                header, body = split_frontmatter(page)
                for internal in ('provider_credit', 'provider credit', '提供商额度', '0.000001',
                                 'unit_rate_usd', 'customer_multiplier', 'micro-USD', 'aisa-pricing:'):
                    self.assertNotIn(internal, page)
                self.assertEqual(body.count(heading), 1)
                self.assertIn('当前暂无预估金额' if prefix else 'A price estimate is not currently available', body)
                self.assertNotIn('$', header)
                spec = json.loads(outputs['openapi/' + prefix + 'similarweb.json'])
                published = spec['paths']['/apis/v1/similarweb/test']['post']
                self.assertEqual(published['x-aisa-pricing'], ADYNTEL_PRICING)
                self.assertEqual(published['description'], 'Find ads for a company.')
            for name, raw in outputs.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            repeated, _ = dev.generate(root, files)
            for name, raw in outputs.items():
                if name.endswith('.mdx') or name in ('openapi/similarweb.json', 'openapi/zh/similarweb.json'):
                    self.assertEqual(repeated[name], raw, name)
        self.assertEqual(document, original)


if __name__ == '__main__':
    unittest.main()
