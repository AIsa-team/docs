import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator
from compose_openapi import compose, digest
from runtime_registry import public_mirror_index
from source_governance import policy_errors
from test_runtime_contracts import facts, operation


ROOT = Path(__file__).resolve().parents[2]


class TikHubRegionInputsTests(unittest.TestCase):
    def test_only_two_exact_official_optional_query_parameters_are_added(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/tikhub-region-inputs-review.json').read_text())
        doc = json.loads((ROOT / review['source_file']).read_text())
        source = doc['info'].pop('x-aisa-source')
        self.assertEqual(source['content_hash'], digest(doc))
        # Validate this historical amendment against its exact source, after
        # undoing the separately reviewed later nullable-only amendment.
        later = json.loads((ROOT / 'docs/current-source-review-20261017/tikhub-nullability-review.json').read_text())
        self.assertEqual(source['prior_source'], later['prior_source'])
        for edit in reversed(later['edits']):
            parent = doc
            for key in edit['pointer'][:-1]:
                parent = parent[key]
            self.assertEqual(digest(parent[edit['pointer'][-1]]), edit['after_sha256'])
            parent[edit['pointer'][-1]] = copy.deepcopy(edit['before'])
        source = source['prior_source']
        self.assertEqual(source['content_hash'], digest(doc))
        self.assertEqual(source['prior_source'], review['prior_source'])
        self.assertEqual(policy_errors(source), [])
        for key in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision'):
            self.assertEqual(source[key], review['prior_source'][key])
        self.assertFalse(review['whole_source_maintenance_clock_advanced'])
        self.assertEqual(len(review['rows']), 2)
        self.assertTrue(review['primary']['url'].startswith('https://raw.githubusercontent.com/TikHub/TikHub-API-Python-SDK/'))
        for row in review['rows']:
            op = doc['paths'][row['source_path']]['get']
            matches = [p for p in op['parameters'] if p.get('name') == 'region' and p.get('in') == 'query']
            self.assertEqual(matches, [row['official_parameter']])
            self.assertFalse(matches[0]['required'])
            Draft7Validator(matches[0]['schema']).validate(matches[0]['example'])
            op['parameters'].remove(matches[0])
        self.assertEqual(digest(doc), review['unchanged_declarations_sha256'])

    def test_normal_public_mirror_composition_exposes_region_without_Runtime_revision(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/tikhub-region-inputs-review.json').read_text())
        mirrors = public_mirror_index(ROOT)
        for row in review['rows']:
            runtime = facts('provider', 'get')
            op = copy.deepcopy(operation(runtime))
            op.update(operationId=row['runtime_operation_id'], parameters=[],
                      **{'x-aisa-upstream-path': row['upstream_path'],
                         'x-aisa-query-policy': {'request_wins': True}})
            runtime['paths'] = {row['public_path']: {'get': op}}
            composed, pending = compose(runtime, public_mirrors=mirrors)
            self.assertFalse(pending)
            parameters = composed['paths'][row['public_path']]['get']['parameters']
            self.assertEqual([p for p in parameters if p.get('name') == 'region'], [row['parameter']])


if __name__ == '__main__':
    unittest.main()
