"""Normalize the rendered 200 JSON schema without changing its validation rules."""


def normalize_response_refs(operation):
    response = operation.get('responses', {}).get('200', {})
    media = response.get('content', {}).get('application/json', {})
    schema = media.get('schema')
    if not isinstance(schema, dict):
        return False

    changed = False
    for branch in schema.get('allOf', []):
        if (isinstance(branch, dict) and set(branch) == {'$ref', 'properties'}
                and branch['$ref'].startswith('#/components/schemas/') and branch['properties'] == {}):
            # Mintlify's resolver overlays the empty map onto the component.
            # An empty properties keyword imposes no constraint in JSON Schema.
            del branch['properties']
            changed = True
    return changed
