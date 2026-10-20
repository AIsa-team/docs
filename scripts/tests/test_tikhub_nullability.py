import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from compose_openapi import compose, digest, resolve, schema_30_to_31
from runtime_registry import public_mirror_index
from source_governance import policy_errors
from test_runtime_contracts import facts, operation


ROOT = Path(__file__).resolve().parents[2]


def at_path(schema, fields):
    if not fields:
        return [schema]
    result = []
    if fields[0] in schema.get('properties', {}):
        result.extend(at_path(schema['properties'][fields[0]], fields[1:]))
    for keyword in ('allOf', 'anyOf', 'oneOf'):
        for child in schema.get(keyword, []):
            result.extend(at_path(child, fields))
    if fields[0] == '*' and isinstance(schema.get('items'), dict):
        result.extend(at_path(schema['items'], fields[1:]))
    return result


class TikHubNullabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads((ROOT / 'docs/current-source-review-20261017/tikhub-nullability-review.json').read_text())
        cls.doc = json.loads((ROOT / cls.review['source_file']).read_text())

    def test_only_exact_reviewed_request_roots_change_and_source_clock_is_preserved(self):
        doc = copy.deepcopy(self.doc)
        source = doc['info'].pop('x-aisa-source')
        self.assertEqual(source['content_hash'], digest(doc))
        self.assertEqual(source['prior_source'], self.review['prior_source'])
        self.assertFalse(policy_errors(source))
        for key in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy', 'review_period_days', 'policy_revision'):
            self.assertEqual(source[key], self.review['prior_source'][key])
        changed = set()
        for edit in reversed(self.review['edits']):
            self.assertIn(edit['pointer'][3], ('parameters', 'requestBody'))
            changed.add(tuple(edit['pointer'][1:3]))
            parent = doc
            for key in edit['pointer'][:-1]:
                parent = parent[key]
            self.assertEqual(digest(parent[edit['pointer'][-1]]), edit['after_sha256'])
            parent[edit['pointer'][-1]] = copy.deepcopy(edit['before'])
        self.assertEqual(len(changed), 10)
        self.assertEqual(len(self.review['edits']), 16)
        self.assertEqual(digest(doc), self.review['unchanged_declarations_sha256'])
        self.assertFalse(self.review['whole_source_maintenance_clock_advanced'])
        self.assertEqual(self.review['primary']['sha256'], '908b21213eeb9466c155971fce9ac4841bc57108d5f748406285f13573e71b9c')

    def test_actual_composer_accepts_all_reviewed_null_positions(self):
        mirrors = public_mirror_index(ROOT)
        by_id = {}
        for row in self.review['operations']:
            method = row['method'].lower()
            runtime = facts('provider', method)
            op = copy.deepcopy(operation(runtime))
            op.update(operationId=row['operation_id'], parameters=[], **{
                'x-aisa-upstream-path': row['path'].replace('/apis/v1/tikhub', '/api/v1', 1),
                'x-aisa-query-policy': {'request_wins': True}})
            runtime['paths'] = {row['path']: {method: op}}
            document, pending = compose(runtime, public_mirrors=mirrors)
            self.assertFalse(pending, row['operation_id'])
            by_id[row['operation_id']] = (resolve(document['paths'][row['path']][method], document), row)
        self.assertEqual(len(by_id), 10)
        for node in self.review['nodes']:
            op, row = by_id[node['operation_id']]
            if node['location'].startswith('body:'):
                roots = [op['requestBody']['content'][node['location'].removeprefix('body:')]['schema']]
            else:
                # The reviewed query schemas are nullable enums; only these
                # operation parameters changed, not numeric ratio bounds.
                roots = [p['schema'] for p in op['parameters'] if p['in'] + ':' + p['name'] == node['location']]
            with self.subTest(operation=row['operation_id'], path=node['field_path']):
                candidates = [s for root in roots for s in at_path(root, node['field_path'])]
                self.assertTrue(candidates)
                self.assertTrue(any(Draft202012Validator(s).is_valid(None) for s in candidates))
        self.assertEqual(len(self.review['nodes']), 129)

    def test_null_only_branch_cannot_admit_extra_non_null_values(self):
        schema = schema_30_to_31({'type': 'string', 'nullable': True, 'enum': [None]})
        validator = Draft202012Validator(schema)
        validator.validate(None)
        for value in ('', 'null', 0, False, {}, [], 'unexpected'):
            with self.subTest(value=value):
                self.assertFalse(validator.is_valid(value))

    def test_existing_enum_rate_and_nested_object_constraints_remain(self):
        for suffix, allowed in [('search_anchor', [9]), ('search_creator', [3, 1, 2]), ('search_toutiao_creator', [11])]:
            op = self.doc['paths']['/tikhub/douyin/xingtu_v2/' + suffix]['get']
            for parameter in op['parameters']:
                schema = schema_30_to_31(resolve(parameter['schema'], self.doc))
                validator = Draft202012Validator(schema)
                if parameter['name'] == 'price_type':
                    for value in [None, *allowed]:
                        validator.validate(value)
                    self.assertFalse(validator.is_valid(999))
                if parameter['name'].startswith(('burst_text_rate_', 'interact_rate_', 'play_over_rate_')):
                    for value in [None, 0, 0.5, 1]:
                        validator.validate(value)
                    self.assertFalse(validator.is_valid(-0.1))
                    self.assertFalse(validator.is_valid(1.1))
        op = self.doc['paths']['/tikhub/xiaohongshu/pgy/get_live_blogger_list']['post']
        schema = schema_30_to_31(resolve(op['requestBody'], self.doc)['content']['application/json']['schema'])
        candidates = at_path(schema, ['buyer'])
        self.assertTrue(any(Draft202012Validator(s).is_valid(None) for s in candidates))
        self.assertTrue(all(not Draft202012Validator(s).is_valid({'unexpected_field': True}) for s in candidates))


if __name__ == '__main__':
    unittest.main()
