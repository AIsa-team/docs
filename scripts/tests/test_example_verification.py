"""Spec #1285 R1: Reference examples only with verified production evidence."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playground_examples import (add_body_code_sample, add_get_code_sample, apply_example_verification,  # noqa: E402
                                 example_scenario, example_sha256)
from readable_contract_notes import PENDING_NOTICE_EN, PENDING_NOTICE_ZH, readable_block  # noqa: E402

SERVERS = [{'url': 'https://api.aisa.one'}]


def get_operation(marker=None, value='stripe.com'):
    op = {'operationId': 'widgets.search',
          'parameters': [{'name': 'domain', 'in': 'query', 'required': True, 'schema': {'type': 'string'},
                          'examples': {'default': {'value': value}}}]}
    if marker is not None:
        op['x-aisa-example'] = marker
    return op


class ExampleVerificationTests(unittest.TestCase):
    def test_cross_repository_hash_vectors(self):
        # The same vectors are fixed in AIsaServices (packages/endpointhealth).
        self.assertEqual(example_sha256({'body': {'domain': 'stripe.com'}, 'parameters': {}}),
                         '2246533e1dd54faf1ff40e9d44cfe765f720ec23742b9a2e58743296d9d4bc5f')
        self.assertEqual(example_sha256({'body': None, 'parameters': {'query:domain': 'stripe.com'}}),
                         'b651ca09556cfe6b1c91aac3ca40b44d50a428681731d968264793793a2cbc48')

    def test_scenario_uses_named_default_query_path_and_body_only(self):
        op = {'parameters': [{'name': 'id', 'in': 'path', 'examples': {'default': {'value': 7}}},
                             {'name': 'X-Mode', 'in': 'header', 'examples': {'default': {'value': 'h'}}},
                             {'name': 'q', 'in': 'query', 'examples': {'minimal': {'value': 'm'}}}],
              'requestBody': {'content': {'application/json': {'examples': {'default': {'value': {'a': 1}}}}}}}
        self.assertEqual(example_scenario(op), {'body': {'a': 1}, 'parameters': {'path:id': 7}})

    def test_unscoped_operations_keep_existing_behavior(self):
        op = get_operation()
        self.assertTrue(apply_example_verification(op))
        self.assertNotIn('x-aisa-verification', op)

    def test_verified_matching_example_publishes_reference_sample(self):
        scenario = {'body': None, 'parameters': {'query:domain': 'stripe.com'}}
        op = get_operation({'state': 'verified', 'id': 'widgets.search#1', 'sha256': example_sha256(scenario)})
        self.assertTrue(apply_example_verification(op))
        add_get_code_sample(op, '/apis/v1/widgets/search', SERVERS)
        self.assertIn('domain=stripe.com', op['x-codeSamples'][0]['source'])
        self.assertNotIn('x-aisa-verification', op)

    def test_unverified_states_publish_pending_marker_and_no_sample(self):
        cases = [({'state': 'pending', 'reason': 'no_fixture'}, 'no_fixture'),
                 ({'state': 'expired'}, 'expired'),
                 ({'state': 'failed', 'reason': 'probe_failed'}, 'probe_failed'),
                 ({'state': 'pending', 'reason': 'something_new'}, 'no_evidence'),
                 ({'state': 'verified', 'sha256': '0' * 64}, 'contract_changed'),
                 ('garbage', 'no_evidence')]
        for marker, reason in cases:
            with self.subTest(marker=marker):
                op = get_operation(marker)
                op['x-codeSamples'] = [{'lang': 'text', 'label': 'Reference example', 'source': 'old'}]
                self.assertFalse(apply_example_verification(op))
                self.assertEqual(op['x-aisa-verification'], {'state': 'pending', 'reason': reason})
                self.assertNotIn('x-codeSamples', op)

    def test_pending_keeps_unrelated_maintained_samples(self):
        op = get_operation({'state': 'pending', 'reason': 'no_evidence'})
        op['x-codeSamples'] = [{'lang': 'Bash', 'source': 'maintained'},
                               {'lang': 'text', 'label': 'Reference example', 'source': 'old'}]
        apply_example_verification(op)
        self.assertEqual(op['x-codeSamples'], [{'lang': 'Bash', 'source': 'maintained'}])

    def test_body_sample_requires_verified_body_example(self):
        body = {'domain': 'stripe.com'}
        op = {'requestBody': {'content': {'application/json': {'examples': {'default': {'value': body}},
                                                               'schema': {'type': 'object'}}}},
              'x-aisa-example': {'state': 'verified', 'sha256': example_sha256({'body': body, 'parameters': {}})}}
        self.assertTrue(apply_example_verification(op))
        add_body_code_sample(op, 'post', '/apis/v1/widgets/enrich', SERVERS)
        self.assertIn('stripe.com', op['x-codeSamples'][0]['source'])

    def test_pending_notice_is_rendered_in_both_languages(self):
        op = {'x-aisa-verification': {'state': 'pending', 'reason': 'no_evidence'}}
        self.assertIn(PENDING_NOTICE_EN, readable_block(op))
        self.assertIn(PENDING_NOTICE_ZH, readable_block(op, 'zh'))
        self.assertEqual(readable_block({}), '')
        for text in (PENDING_NOTICE_EN, PENDING_NOTICE_ZH):
            self.assertIn('X-AISA-Cost-Mode: quote', text)


if __name__ == '__main__':
    unittest.main()
