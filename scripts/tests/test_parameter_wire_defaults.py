import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import parameter_wire_default


class ParameterWireDefaultTests(unittest.TestCase):
    def test_http_scalar_string_defaults_keep_the_same_wire_value(self):
        for value, wire in [(False, 'false'), (True, 'true'), (7, '7'), (1.5, '1.5')]:
            parameter = {'in': 'query', 'name': 'collect', 'schema': {'type': 'string', 'default': value}}
            converted = parameter_wire_default(parameter)
            self.assertEqual(converted['schema']['default'], wire)
            self.assertEqual(parameter['schema']['default'], value)

    def test_body_and_boolean_schema_defaults_are_not_coerced(self):
        for location, kind in [('query', 'boolean'), ('body', 'string')]:
            parameter = {'in': location, 'name': 'flag', 'schema': {'type': kind, 'default': False}}
            self.assertEqual(parameter_wire_default(parameter), parameter)
