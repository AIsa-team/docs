"""Convert Cloudsway's official smart reference; keep the account endpoint private."""
import hashlib
import re
from import_querit_reference import ReferenceTables

REFERENCE_URL = 'https://docs.infra-agent.ai/Smart_Search/Cloudsway_Smart_Search/api/'
ORIGINAL_REFERENCE_URL = 'https://docs.cloudsway.net/Smart_Search/Cloudsway_Smart_Search/api/'
VERSION = 'scripts/wrapper_cloudsway_reference.py@1'
# Reviewed routing proof: AIsaConsole bin/cloudsway_search_api_import.sh names
# Cloudsway and maps this configured path to smart. No account path is published.
UPSTREAM_PATH_SHA256 = '96e1bbbdf395b4c6825c213d53fcd646493e1426452ed6a2d33825fa073cc27d'


def convert_reference(raw):
    parser = ReferenceTables()
    parser.feed(raw.decode())
    table = parser.unique_section('Request Parameter')['tables']
    if len(table) != 1 or table[0][0] != ['Parameter', 'Required', 'Type', 'Description']:
        raise ValueError('Cloudsway parameter declaration changed')
    if '/search/{Endpoint}/smart' not in raw.decode() or 'GET' not in ''.join(parser.unique_section('request method')['text']):
        raise ValueError('Cloudsway route or method changed')
    rows = []
    for row in table[0][1:]:
        if len(row) != 4:
            raise ValueError('Cloudsway table row width changed')
        if not any(row[1:]):
            if not rows:
                raise ValueError('orphan Cloudsway parameter continuation')
            rows[-1][3] += ' ' + row[0]
        else:
            rows.append(row[:])
    parameters = []
    types = {'String': 'string', 'Short': 'integer', 'bool': 'boolean', 'Float': 'number'}
    for name, required, kind, description in rows:
        if required not in {'Y', 'N'} or kind not in types:
            raise ValueError('unsupported Cloudsway required/type declaration')
        schema = {'type': types[kind]}
        if kind in {'Short', 'Float'}:
            default = re.search(r'Defaults to (\d+(?:\.\d+)?)', description)
            maximum = re.search(r'maximum (\d+(?:\.\d+)?)', description)
            cast = int if kind == 'Short' else float
            if default: schema['default'] = cast(default[1])
            if maximum: schema['maximum'] = cast(maximum[1])
        if 'cannot be empty' in description: schema['minLength'] = 1
        if 'zero-based offset' in description: schema['minimum'] = 0
        if kind == 'bool':
            default = re.search(r'Default(?:s to)? (true|false)', description)
            if default: schema['default'] = default[1] == 'true'
        if name == 'count':
            match = re.search(r'Enumerated values: (\d+(?: / \d+)*)', description)
            if not match: raise ValueError('count enum removed')
            schema['enum'] = [int(x.strip()) for x in match[1].split('/')]
        if name == 'freshness':
            choices = re.findall(r'-\s*(Day|Week|Month)\b', description)
            if choices != ['Day', 'Week', 'Month']: raise ValueError('freshness choices changed')
            schema['enum'] = choices
        if name == 'contentType':
            choices = re.findall(r'-\s*(HTML|MARKDOWN|TEXT)\b', description)
            if choices != ['HTML', 'MARKDOWN', 'TEXT'] or 'TEXT(default)' not in description:
                raise ValueError('contentType choices/default changed')
            schema.update(enum=choices, default='TEXT')
        parameters.append({'name': name, 'in': 'query', 'required': required == 'Y', 'description': description, 'schema': schema})
    if not any(p['name'] == 'q' and p['required'] for p in parameters):
        raise ValueError('query requirement removed')
    headers = parser.unique_section('request header')['tables']
    for name, kind, description in headers[0][1:]:
        if name == 'Authorization': continue  # gateway owns authentication
        if name != 'Pragma' or kind != 'String': raise ValueError('new upstream header needs review')
        parameters.append({'name': name, 'in': 'header', 'required': False, 'description': description, 'schema': {'type': 'string'}})
    document = {'openapi': '3.1.0', 'info': {'title': 'Cloudsway smart search official request', 'version': '1'},
        'paths': {'/apis/v1/search/smart': {'get': {'summary': 'Perform Smart Search', 'parameters': parameters,
            'responses': {'200': {'description': 'Provider response; response required fields are not inferred.'}}}}}}
    return document, {'kind': 'manual', 'refresh_policy': 'automatic', 'converter': VERSION, 'path_space': 'public', 'upstream_path_sha256': UPSTREAM_PATH_SHA256,
        'original_upstream_path_template': '/search/{Endpoint}/smart',
        'public_path_mapping': 'Reviewed AIsa routing maps the account-specific Cloudsway endpoint to /apis/v1/search/smart.',
        'source_pages': [{'url': REFERENCE_URL, 'raw_content_hash': 'sha256:' + hashlib.sha256(raw).hexdigest()}]}


def import_reference(fetch):
    return convert_reference(fetch(REFERENCE_URL))
