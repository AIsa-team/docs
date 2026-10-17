"""Pin each bounded amendment without approving Runtime forwarding or new debt."""
import copy
import json
from pathlib import Path
import unittest
from jsonschema import Draft7Validator

from compose_openapi import digest
from source_governance import policy_errors

ROOT = Path(__file__).resolve().parents[2]


class CurrentPrimaryQueryAmendmentTests(unittest.TestCase):
    def test_exact_primary_parameters_and_unchanged_other_declarations(self):
        review = json.loads((ROOT / 'docs/current-source-review-20261017/query-parameter-primary-fragments.json').read_text())
        self.assertEqual(len(review['rows']), 14)
        documents = {name: json.loads((ROOT / name).read_text()) for name in review['files']}
        for row in review['rows']:
            document = documents[row['source_file']]
            op = document['paths'][row['source_path']][row['method']]
            matching = [p for p in op['parameters'] if p.get('in') == 'query' and p.get('name') == row['field']]
            self.assertEqual(matching, [row['parameter']])
            self.assertFalse(row['parameter'].get('required', False))
            expected = copy.deepcopy(row['official_parameter'])
            for normalization in row.get('normalizations', []):
                self.assertEqual(normalization['path'], 'example')
                self.assertEqual(expected['schema']['type'], 'boolean')
                self.assertEqual(expected['example'], normalization['before'])
                expected['example'] = normalization['after']
            self.assertEqual(row['parameter'], expected)
            if 'example' in row['parameter']:
                Draft7Validator(row['parameter']['schema']).validate(row['parameter']['example'])
            self.assertFalse(row['production_profile_applied'])
            self.assertTrue(row['primary_url'].startswith('https://docs.'))
            self.assertRegex(row['primary_raw_sha256'], r'^[0-9a-f]{64}$')
        for name, original in review['files'].items():
            document = copy.deepcopy(documents[name])
            source = document['info'].pop('x-aisa-source')
            self.assertEqual(source['content_hash'], digest(document))
            self.assertEqual(source['prior_source'], original['prior_source'])
            for key in ('fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision', 'url'):
                self.assertEqual(source[key], original['prior_source'][key])
            self.assertEqual(policy_errors(source), [])
            for row in review['rows']:
                if row['source_file'] != name:
                    continue
                op = document['paths'][row['source_path']][row['method']]
                op['parameters'] = [p for p in op['parameters'] if not (p.get('in') == 'query' and p.get('name') == row['field'])]
            self.assertEqual(digest(document), original['unchanged_declarations_sha256'])


if __name__ == '__main__':
    unittest.main()
