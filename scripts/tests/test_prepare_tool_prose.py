import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_tool_prose import prepare_text, details, title, retain_runtime_free_statement


class ToolProsePreparationTests(unittest.TestCase):
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
