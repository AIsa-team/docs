import sys
import json
import csv
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_tool_prose import prepare_text, details, title, retain_runtime_free_statement, enrich_purpose


class ToolProsePreparationTests(unittest.TestCase):
    def test_checked_in_evidence_has_unique_exact_identities_and_source_provenance(self):
        root = Path(__file__).resolve().parents[2]
        rows = json.loads((root / 'scripts/data/tool-prose-purpose-evidence.json').read_text())
        identities = [(r['path'], r['method'], r['operation_id']) for r in rows]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(len(rows), 865)
        for row in rows:
            self.assertRegex(row['sha256'], r'^[a-f0-9]{64}$')
            self.assertTrue(row['url'].startswith('https://'))
            self.assertTrue(row['source_description'].strip())
            self.assertFalse(row['description'].startswith('$'))
            if row['source_description'] != row['description']:
                self.assertIn(row['upstream_operation_id'],
                              {'crawl4ai.google.serp.ai_mode', 'apify.google.serp.maps'})

    def test_all_grouped_agentmail_repetitions_have_input_guidance(self):
        from prepare_tool_prose import summary_only
        root = Path(__file__).resolve().parents[2]
        with (root / 'docs/tool-prose-coverage-20261112.csv').open() as stream:
            rows = [r for r in csv.DictReader(stream) if r['provider'] == 'agentmail'
                    and ' - ' in r['summary_before']
                    and summary_only(r['description_before'], r['summary_before'])]
        self.assertEqual(len(rows), 15)
        for row in rows:
            self.assertIn('Required inputs:', row['description_after'])
            self.assertEqual(row['disposition'], 'expanded_from_declared_contract')

    def test_bound_source_requires_exact_identity_original_title_and_weak_prose(self):
        op = {'operationId': 'demo.search', 'summary': 'Search'}
        row = {'before_summary': 'Search', 'description': 'Find published reports by company name.'}
        evidence = {('/search', 'GET', 'demo.search'): row}
        args = ('Demo: Search.', 'bounded_to_declared_purpose', evidence)
        text, disposition, source = enrich_purpose(op, '/search', 'get', *args)
        self.assertIn(row['description'], text)
        self.assertEqual(disposition, 'expanded_from_bound_source')
        self.assertEqual(source, row)
        for changed, path, method in [(op, '/other', 'get'), (op, '/search', 'post'),
                                     ({**op, 'summary': 'Operator edit'}, '/search', 'get'),
                                     ({**op, 'operationId': 'other'}, '/search', 'get')]:
            self.assertEqual(enrich_purpose(changed, path, method, *args)[:2], args[:2])
        self.assertEqual(enrich_purpose(op, '/search', 'get', 'Requires a cookie.',
                                       'preserved_existing_prose', evidence)[0], 'Requires a cookie.')

    def test_operation_parameter_overrides_path_parameter(self):
        _, text, _ = prepare_text({'summary': 'Search', 'parameters': [
            {'name': 'query', 'in': 'query', 'required': False, 'schema': {'type': 'string'}}]}, {},
            {'parameters': [{'name': 'query', 'in': 'query', 'required': True, 'schema': {'type': 'integer'}}]})
        self.assertNotIn('Required inputs:', text)
        self.assertIn('`query` (string)', text)

    def test_invisible_and_pricing_placeholders_are_not_descriptions(self):
        for text in ('\u200c', '\u200b\ufeff', '默认价格配置'):
            _, description, _ = prepare_text({'summary': 'Search', 'description': text},
                                             {'info': {'title': 'Demo'}}, {})
            self.assertEqual(description, 'Demo: Search.')
        _, description, _ = prepare_text({'summary': 'Search', 'description': '\u200cRequires a cookie.'}, {}, {})
        self.assertEqual(description, 'Requires a cookie.')

    def test_exact_runtime_free_statement_survives_projection_boilerplate(self):
        runtime = {'description': 'Poll status. Free.'}
        self.assertEqual(retain_runtime_free_statement('Poll status. See the published pricing.', runtime),
                         'Poll status. Free.')
        self.assertEqual(retain_runtime_free_statement('Poll status with credentials.', runtime),
                         'Poll status with credentials.')

    def test_internal_kalshi_document_id_is_not_a_public_provider_name(self):
        summary, description, _ = prepare_text(
            {'summary': 'Get Market Price', 'description': '默认价格配置'},
            {'info': {'title': 'kalshi-unauthorized'}}, {})
        self.assertEqual(summary, 'Kalshi: Get Market Price')
        self.assertNotIn('kalshi-unauthorized', summary + description)

    def test_grouped_title_is_not_substantive_prose(self):
        op = {'summary': 'Inboxes - Send Message', 'description': 'Send Message',
              'parameters': [{'name': 'inbox_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}]}
        _, description, disposition = prepare_text(op, {'info': {'title': 'AgentMail'}}, {})
        self.assertEqual(disposition, 'expanded_from_declared_contract')
        self.assertIn('`inbox_id`', description)

    def test_batch_alternatives_keep_required_inputs_conditional(self):
        op = {'requestBody': {'required': True, 'content': {'application/json': {'schema': {
            'type': 'array', 'items': {'oneOf': [
                {'properties': {'name': {'type': 'string'}}, 'required': ['name']},
                {'properties': {'id': {'type': 'integer'}}, 'required': ['id']}]}}}}}}
        text, details_found = details(op, {}, {})
        self.assertTrue(details_found)
        self.assertIn('array item, oneOf variant 1 of 2 when selected: `name`', text)
        self.assertIn('array item, oneOf variant 2 of 2 when selected: `id`', text)

    def test_allof_required_names_apply_to_sibling_properties(self):
        op = {'requestBody': {'required': False, 'content': {'application/json': {'schema': {
            'properties': {'query': {'type': 'string'}}, 'allOf': [{'required': ['query']}]}}}}}
        text, _ = details(op, {}, {})
        self.assertIn('Required inputs:', text)
        self.assertIn('when supplied: `query`', text)
        self.assertNotIn('Key optional inputs', text)

    def test_declared_response_envelope_fields_are_expanded(self):
        op = {'responses': {'200': {'content': {'application/json': {'schema': {'properties': {
            'data': {'type': 'array', 'items': {'properties': {'thread_id': {'type': 'string'}}}}}}}}}}}
        text, _ = details(op, {}, {})
        self.assertIn('`data[].thread_id`', text)

    def test_brief_existing_caveat_is_preserved_when_adding_required_inputs(self):
        op = {'summary': 'Read report', 'description': 'Requires a login cookie.',
              'parameters': [{'name': 'report_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}]}
        _, text, disposition = prepare_text(op, {}, {})
        self.assertTrue(text.startswith('Requires a login cookie.\n\n'))
        self.assertIn('`report_id`', text)
        self.assertEqual(disposition, 'supplemented_existing_prose')

    def test_generic_schema_does_not_invent_fields_or_account_scope(self):
        operation = {'summary': 'Search', 'requestBody': {'content': {'application/json': {
            'schema': {'type': 'object', 'additionalProperties': True}}}},
            'responses': {'200': {'content': {'application/json': {'schema': {}}}}}}
        summary, description, status = prepare_text(operation, {'info': {'title': 'Agoda stays'}}, {})
        self.assertEqual(summary, 'Agoda stays: Search')
        self.assertEqual(description, 'Agoda stays: Search.')
        self.assertEqual(status, 'bounded_to_declared_purpose')
        self.assertNotIn('account', description)
        self.assertNotIn('Required', description)

    def test_declared_inputs_and_response_refs_are_used_without_examples(self):
        document = {'info': {'title': 'Demo'}, 'components': {'schemas': {
            'Body': {'type': 'object', 'properties': {'text': {'type': 'string', 'maxLength': 2000}}, 'required': ['text']},
            'Result': {'type': 'object', 'properties': {'sentiment': {'type': 'string'}, 'score': {'type': 'number'}}}}}}
        operation = {'summary': 'Analyze sentiment', 'requestBody': {'required': True,
            'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Body'}, 'example': {'text': 'do not copy examples'}}}},
            'responses': {'200': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Result'}}}}}}
        _, description, status = prepare_text(operation, document, {})
        self.assertEqual(status, 'expanded_from_declared_contract')
        self.assertIn('`text`', description)
        self.assertIn('maximum length: 2000', description)
        self.assertIn('`sentiment`, `score`', description)
        self.assertNotIn('do not copy examples', description)

    def test_existing_caveats_are_retained_and_pricing_is_not_source_text(self):
        caveat = 'Requires a login cookie for an owned account. Not public profile discovery.'
        operation = {'summary': 'Read creator analytics', 'description': caveat + '\n\n<!-- aisa-pricing:start -->Paid<!-- aisa-pricing:end -->'}
        _, description, _ = prepare_text(operation, {'info': {'title': 'TikTok'}}, {})
        self.assertEqual(description, caveat)

    def test_purpose_title_preserves_surface_and_parameter_identifiers(self):
        operation = {'summary': 'douyin fetch_user_by_uid',
                     'description': 'Douyin (creator_v2).\n### Purpose:\n- Get profile by sec_uid'}
        self.assertEqual(title(operation), 'Douyin (creator v2): Get profile by sec_uid')

    def test_optional_body_required_fields_are_conditional_and_not_truncated(self):
        fields = {f'field_{i}': {'type': 'string'} for i in range(12)}
        op = {'requestBody': {'required': False, 'content': {'application/json': {
            'schema': {'type': 'object', 'properties': fields, 'required': list(fields)}}}}}
        guidance, _ = details(op, {}, {})
        self.assertEqual(guidance.count('when supplied'), 12)
        for name in fields:
            self.assertIn('`' + name + '`', guidance)

    def test_long_description_is_never_cut(self):
        original = 'Read report. ' * 400 + 'Requires approval before submitting.'
        _, description, status = prepare_text({'summary': 'Read report', 'description': original}, {}, {})
        self.assertEqual(status, 'front_loaded_existing_detail')
        self.assertTrue(description.endswith(original))


if __name__ == '__main__':
    unittest.main()
