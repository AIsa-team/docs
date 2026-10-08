"""Review-only PullPosts response from BytePlus's official typed tables.

Other actions are intentionally absent: the captured official page does not
publish their response tables. Examples never supply types or requiredness.
"""
import hashlib
import re
from source_json import loads

REFERENCE_URL = 'https://docs.byteplus.com/en/docs/mkinsights/insightAPI'
VERSION = 'scripts/import_byteplus_response_reference.py@1'


def markdown(raw):
    scripts = re.findall(r'<script[^>]*>window\._ROUTER_DATA = (.*?)</script>', raw.decode(), re.S)
    if len(scripts) != 1:
        raise ValueError('expected one official BytePlus router document')
    doc = loads(scripts[0])['loaderData']['(lang)/docs/(libcode)/(doccode$)/page']['curDoc']
    value = doc.get('MDContent')
    if not isinstance(value, str):
        raise ValueError('official BytePlus Markdown missing')
    return value


def table(section, name):
    match = re.search(r'^#### ' + re.escape(name) + r'\s*$(.*?)(?=^#### |^### |\Z)', section, re.M | re.S)
    if not match:
        raise ValueError('BytePlus response table missing: ' + name)
    rows = [line for line in match[1].splitlines() if line.startswith('|')]
    cells = [[v.strip().replace('**', '').replace('\\>', '>') for v in line.strip('|').split('|')] for line in rows]
    if len(cells) < 3 or cells[0] != ['Parameter', 'Type', 'Required', 'Example', 'Description']:
        raise ValueError('BytePlus table columns changed')
    return cells[2:]


def fields(rows, expected, objects):
    result = {'type': 'object', 'properties': {}}
    for row in rows:
        if len(row) != 5:
            raise ValueError('BytePlus response row width changed')
        name, kind, required, example, description = row
        if name in result['properties'] or expected.get(name) != (kind, required):
            raise ValueError('BytePlus response field/type/required changed')
        if kind in {'bool', 'string'}:
            schema = {'type': {'bool': 'boolean', 'string': 'string'}[kind]}
        elif kind == 'Array<string>':
            schema = {'type': 'array', 'items': {'type': 'string'}}
        elif kind == 'Array<PostStruct>':
            schema = {'type': 'array', 'items': objects['PostStruct']}
        else:
            raise ValueError('unsupported BytePlus response type')
        schema['description'] = description
        result['properties'][name] = schema
        if required == 'Yes':
            result.setdefault('required', []).append(name)
    if set(result['properties']) != set(expected):
        raise ValueError('BytePlus response field omitted')
    return result


def convert_reference(raw):
    text = markdown(raw)
    action = re.search(r'^## 1 PullPosts\s*$(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not action or '|Action |String |Yes |PullPosts |API name |' not in action[1] or '|Version |String |Yes |2026\\-03\\-24 |API version |' not in action[1]:
        # Markdown currently spells the version without escaping hyphens.
        if not action or '|Version |String |Yes |2026-03-24 |API version |' not in action[1] or '|Action |String |Yes |PullPosts |API name |' not in action[1]:
            raise ValueError('BytePlus Action/version declaration changed')
    response = re.search(r'^### Response parameters\s*$(.*?)(?=^### |\Z)', action[1], re.M | re.S)
    if not response:
        raise ValueError('BytePlus response section missing')
    post_expected = {name: ('string', required) for name, required in [
        ('PostID', 'Yes'), ('Title', 'No'), ('Content', 'No'), ('Url', 'Yes'),
        ('PublishTime', 'Yes'), ('Summary', 'No'), ('Ocr', 'No'), ('Emotion', 'No'), ('Reason', 'No')]}
    post_expected['RiskType'] = ('Array<string>', 'No')
    post = fields(table(response[1], 'PostStruct'), post_expected, {})
    result = fields(table(response[1], 'ResultStruct'), {'HasMore': ('bool', 'Yes'),
        'NextPageToken': ('string', 'Yes'), 'ItemDocs': ('Array<PostStruct>', 'Yes')}, {'PostStruct': post})
    # The endpoint page declares ResultStruct, but only an example supplies the
    # top-level Result envelope. Retain the declared component without inventing
    # a complete response or clearing response debt.
    document = {'openapi': '3.1.0', 'info': {'title': 'BytePlus PullPosts declared response component', 'version': '2026-03-24'},
        'servers': [{'url': 'https://mkt-insight.byteplusapi.com'}],
        'components': {'schemas': {'PullPostsResult': result}},
        'paths': {'/': {'post': {
            'x-aisa-byteplus-action': 'PullPosts', 'x-aisa-byteplus-version': '2026-03-24',
            'responses': {'200': {'description': 'ResultStruct fields are declared in components; the complete top-level response envelope remains unverified.'}}}}}}
    return document, {'converter': VERSION, 'refresh_policy': 'automatic', 'kind': 'manual',
        'source_pages': [{'url': REFERENCE_URL, 'raw_content_hash': 'sha256:' + hashlib.sha256(raw).hexdigest()}],
        'limits': ['Only PullPosts ResultStruct is declared on this page; no complete response envelope is asserted.',
            'Official examples contain empty MainDomain; runtime requires nonempty MainDomain in returned ItemDocs. No example is treated as a complete schema.']}
