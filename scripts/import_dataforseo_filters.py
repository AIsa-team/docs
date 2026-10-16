"""Preserve official JSON filter values without inventing a provider DSL schema."""
import copy

SOURCE_URL = 'https://raw.githubusercontent.com/dataforseo/OpenApiDocumentation/master/openapi_specification.yaml'
VERSION = 'scripts/import_dataforseo_filters.py@1'
VALUE = 'AisaDataforseoFilterJsonValue'
FILTERS = {'filters', 'initial_dataset_filters', 'backlinks_filters', 'relevant_pages_filters'}


def normalize_filters(document):
    result = copy.deepcopy(document)
    schemas = result.get('components', {}).get('schemas', {})
    changed = []
    for name, schema in list(schemas.items()):
        if not name.endswith('RequestInfo'):
            continue
        for field, value in schema.get('properties', {}).items():
            if field not in FILTERS or value.get('type') != 'array':
                continue
            # These placeholders contradict the same official declaration's
            # condition-array examples. Never overwrite a structured item schema.
            if value.get('items') not in ({'type': 'object', 'nullable': True}, {'type': 'string'}):
                continue
            value['items'] = {'$ref': '#/components/schemas/' + VALUE}
            changed.append((name, field))
    if changed:
        if VALUE in schemas:
            raise ValueError('DataForSEO JSON value component already declared')
        schemas[VALUE] = {
            'description': 'JSON representation of filter values and nested expressions. Field names, operators, condition counts and operand compatibility remain provider-validated as documented for each endpoint; this is not a complete filter-language validator.',
            'anyOf': [
                {'type': 'string'}, {'type': 'number'}, {'type': 'boolean'},
                {'type': 'object', 'nullable': True,
                 'additionalProperties': {'$ref': '#/components/schemas/' + VALUE}},
                {'type': 'array', 'items': {'$ref': '#/components/schemas/' + VALUE}},
            ],
        }
    return result, changed


def remove_duplicate_batch_examples(document):
    """A whole-task array example belongs on the body, not its object item."""
    changed = []
    schemas = document.get('components', {}).get('schemas', {})
    for item in document.get('paths', {}).values():
        for operation in item.values():
            if not isinstance(operation, dict):
                continue
            for media in operation.get('requestBody', {}).get('content', {}).values():
                array = media.get('schema', {})
                if array.get('type') != 'array' or not isinstance(array.get('example'), list):
                    continue
                for branch in array.get('items', {}).get('oneOf', []):
                    name = branch.get('$ref', '').removeprefix('#/components/schemas/')
                    schema = schemas.get(name, {})
                    if (schema.get('type') == 'object' and isinstance(schema.get('example'), list)
                            and schema['example'] == array['example']):
                        schema.pop('example')
                        changed.append(name)
    return changed
