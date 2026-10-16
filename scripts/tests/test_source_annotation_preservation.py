import copy
import unittest

from compose_openapi import compose, merge_object, retain_source_annotations
from test_runtime_contracts import facts, mirror, operation


class SourceAnnotationPreservationTests(unittest.TestCase):
    def test_runtime_query_constraints_keep_provider_explanation(self):
        runtime, upstream = facts('mixed'), mirror()
        source = operation(upstream)['parameters'][0]
        source.update(description='Controls optional enrichment.', example='legacy')
        source['schema'].update(description='Provider switch.', example='legacy')
        before = copy.deepcopy((runtime, upstream))
        result, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        parameter = operation(result)['parameters'][0]
        self.assertEqual(parameter['description'], source['description'])
        self.assertEqual(parameter['schema'], {
            'type': 'boolean', 'default': False, 'description': 'Provider switch.'})
        self.assertNotIn('example', parameter)
        self.assertEqual((runtime, upstream), before)

    def test_body_examples_do_not_become_defaults_or_restore_constraints(self):
        source = {'properties': {'limit': {
            'type': 'integer', 'description': 'Maximum results.', 'example': 10,
            'minimum': 0, 'maximum': 1000, 'default': 10}}}
        declared = {'properties': {'limit': {
            'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 25}}}
        field = merge_object(source, declared)['properties']['limit']
        self.assertEqual(field, {
            'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 25,
            'description': 'Maximum results.'})
        # Runtime-authored annotations are authoritative too.
        self.assertEqual(retain_source_annotations(
            {'type': 'string', 'description': 'Runtime', 'example': 'runtime'},
            {'type': 'string', 'description': 'Provider', 'example': 'source'}),
            {'type': 'string', 'description': 'Runtime', 'example': 'runtime'})

    def test_number_to_integer_example_and_default_prose_follow_runtime(self):
        source = {'type': 'number', 'minimum': 1, 'maximum': 100, 'default': 40,
                  'description': 'Maximum results. Default 40, range 1-100.', 'example': 10}
        result = retain_source_annotations({'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 25}, source)
        self.assertEqual(result['example'], 10)
        self.assertEqual(result['default'], 25)
        self.assertIn('Default 25, range 1-100', result['description'])
        source['example'] = 1.5
        self.assertNotIn('example', retain_source_annotations({'type': 'integer'}, source))

    def test_incompatible_bounds_or_enum_do_not_restore_invalid_example(self):
        for runtime, source in (
                ({'type': 'integer', 'maximum': 5}, {'type': 'integer', 'maximum': 10, 'example': 10}),
                ({'type': 'string', 'enum': ['a']}, {'type': 'string', 'enum': ['a', 'b'], 'example': 'b'})):
            self.assertNotIn('example', retain_source_annotations(runtime, source))


if __name__ == '__main__':
    unittest.main()
