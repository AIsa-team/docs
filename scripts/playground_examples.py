"""Project canonical request examples into a separate Mintlify reference sample.

Never synthesize values from type/enum/bounds or change wire `default` semantics.
Named `default` examples are a single scenario, shared across request parameters.
"""
import json
import shlex
from urllib.parse import urlencode, quote

_MISSING = object()


def example_value(node):
    examples = node.get('examples', {})
    if isinstance(examples, dict) and isinstance(examples.get('default'), dict):
        return examples['default'].get('value', _MISSING)
    if 'example' in node:
        return node['example']
    if isinstance(examples, list) and len(examples) == 1:
        return examples[0]
    return _MISSING


def add_get_code_sample(operation, path, servers):
    """Replace Mintlify's omitted-query default cURL from one canonical scenario.

    Only ordinary scalar form query and simple path serialization are supported.
    No generated code is supplied when a required value is unknown.
    """
    if operation.get("requestBody"):
        return
    params = operation.get('parameters', [])
    if any('content' in p for p in params):
        return
    if not any(p.get('required') and p.get('in') in {'query', 'path'} for p in params):
        return
    query = []
    for param in params:
        location = param.get('in')
        if location not in {'query', 'path'}:
            if param.get('required') or example_value(param) is not _MISSING:
                return
            continue
        value = example_value(param)
        if value is _MISSING and param.get('required'):
            value = example_value(param.get('schema', {}))
        if value is _MISSING:
            if param.get('required'):
                return
            continue
        if not isinstance(value, (str, int, float, bool)) or param.get('style', 'form' if location == 'query' else 'simple') != ('form' if location == 'query' else 'simple'):
            return
        value = str(value).lower() if isinstance(value, bool) else str(value)
        if location == 'path':
            path = path.replace('{' + param['name'] + '}', quote(value, safe=''))
        else:
            query.append((param['name'], value))
    if '{' in path or not servers or not servers[0].get('url', '').startswith('https://'):
        return
    url = servers[0]['url'].rstrip('/') + path
    if query:
        url += '?' + urlencode(query)
    source = 'curl --request GET ' + chr(92) + '\n  --url ' + shlex.quote(url) + ' ' + chr(92) + '\n  --header ' + shlex.quote('Authorization: Bearer <token>')
    samples = operation.setdefault('x-codeSamples', [])
    samples[:] = [s for s in samples if not (s.get('lang') == 'text' and s.get('label') == 'Reference example')]
    samples.insert(0, {'lang': 'text', 'label': 'Reference example', 'source': '# Fixed reference example. Playground inputs do not update this sample.\n' + source})


def required_body_example(schema):
    value = example_value(schema)
    if value is not _MISSING:
        return value
    if schema.get('type') == 'object' or 'properties' in schema:
        if len(schema.get('required', [])) != 1:
            return _MISSING
        result = {}
        for name in schema.get('required', []):
            child = schema.get('properties', {}).get(name)
            if not isinstance(child, dict):
                return _MISSING
            value = required_body_example(child)
            if value is _MISSING:
                return _MISSING
            result[name] = value
        return result
    return _MISSING


def add_body_code_sample(operation, method, path, servers):
    """Publish a complete declared JSON example, or known required values only."""
    body = operation.get('requestBody', {})
    content = body.get('content', {})
    if set(content) != {'application/json'} or '{' in path or not servers or not servers[0].get('url', '').startswith('https://'):
        return
    # Do not silently discard query/path/header members of the same scenario.
    if any(p.get('required') or example_value(p) is not _MISSING for p in operation.get('parameters', [])):
        return
    media = content['application/json']
    value = example_value(media)
    if value is _MISSING:
        value = required_body_example(media.get('schema', {}))
    if value is _MISSING:
        return
    url = servers[0]['url'].rstrip('/') + path
    parts = ['curl --request ' + method.upper(), '--url ' + shlex.quote(url),
             '--header ' + shlex.quote('Authorization: Bearer <token>'),
             '--header ' + shlex.quote('Content-Type: application/json'),
             '--data ' + shlex.quote(json.dumps(value, ensure_ascii=False, indent=2))]
    source = (' ' + chr(92) + '\n  ').join(parts)
    samples = operation.setdefault('x-codeSamples', [])
    samples[:] = [s for s in samples if not (s.get('lang') == 'text' and s.get('label') == 'Reference example')]
    samples.insert(0, {'lang': 'text', 'label': 'Reference example', 'source': '# Fixed reference example. Playground inputs do not update this sample.\n' + source})
