"""Strictly convert public Theneo response declarations without fixing their types.

Named children of an array are ambiguous and rejected. Array element prototypes
must be numeric and describe the same schema; raw values never become defaults.
"""
import copy
import hashlib
from html.parser import HTMLParser
import re
from source_json import loads
from compose_openapi import digest

VERSION = 'scripts/import_similarweb_response_reference.py@2'
ORIGIN = 'https://api.similarweb.com/'


class CanonicalURL(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag != 'link':
            return
        values = dict(attrs)
        if values.get('rel') == 'canonical':
            if len([key for key, _ in attrs if key in {'rel', 'href'}]) != 2:
                raise ValueError('ambiguous Similarweb canonical link')
            self.urls.append(values.get('href'))


def declaration(raw, expected_path):
    matches = re.findall(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw.decode(), re.S)
    if len(matches) != 1:
        raise ValueError('expected one official Similarweb page declaration')
    props = loads(matches[0])['props']['pageProps']
    section = props['initialSectionData']
    if section.get('endpoints') != {'method': 'get', 'path': expected_path.lstrip('/')}:
        raise ValueError('official Similarweb endpoint mismatch')
    same = [x for x in props['documents']['data']['transformedSection'] if x.get('_id') == section.get('_id')]
    if len(same) != 1 or same[0].get('urls', {}).get('Production') != [ORIGIN]:
        raise ValueError('official Similarweb production authority mismatch')
    return section


def field_schema(node, location):
    if not isinstance(node, dict) or node.get('complexItems') not in (None, []):
        raise ValueError('unsupported Similarweb complex declaration at ' + location)
    allowed_node = {'_id', 'name', 'description', 'isRequired', 'value', 'valueType', 'items', 'options', 'complexItems'}
    if set(node) - allowed_node:
        raise ValueError('unrepresented Similarweb node semantics at ' + location)
    kind = node.get('valueType')
    if kind not in {'object', 'array', 'string', 'integer', 'number', 'boolean'}:
        raise ValueError('unsupported Similarweb declared type at ' + location)
    schema = {'type': kind}
    options = node.get('options', {})
    if not isinstance(options, dict): raise ValueError('invalid Similarweb options')
    allowed = {'nullable','enumValue','example','format','minLength','maxLength','minimum','maximum','xml','schemaNames','style'}
    if set(options) - allowed:
        raise ValueError('unrepresented Similarweb option at ' + location)
    if options.get('style') is not None:
        raise ValueError('unrepresented Similarweb serialization style')
    if options.get('schemaNames') not in (None, []) or options.get('xml') not in (None, {'prefix': None}):
        raise ValueError('unrepresented Similarweb schema/XML declaration')
    if options.get('nullable') is not None and type(options['nullable']) is not bool:
        raise ValueError('invalid nullable marker')
    if options.get('nullable') is True: schema['type'] = [kind, 'null']
    for key in ('example','format','minLength','maxLength','minimum','maximum'):
        if key in options: schema[key] = copy.deepcopy(options[key])
    if node.get('description'): schema['description'] = node['description']
    children = node.get('items', [])
    if not isinstance(children, list): raise ValueError('invalid Similarweb children')
    enums = options.get('enumValue')
    if enums is not None:
        if not isinstance(enums, list) or any(not isinstance(x, dict) or set(x) != {'value'} for x in enums):
            raise ValueError('unrepresented Similarweb enum declaration')
        values = [x['value'] for x in enums]
        if kind != 'array': schema['enum'] = values + ([None] if options.get('nullable') is True and None not in values else [])
    if kind == 'object':
        schema.update(object_fields(children, location))
    elif kind == 'array':
        prototypes = []
        for child in children:
            if not isinstance(child, dict) or not str(child.get('name', '')).isdigit():
                raise ValueError('array declares named child instead of an item at ' + location)
            prototypes.append(field_schema(child, location + '[]'))
        if not prototypes:
            raise ValueError('array item schema absent at ' + location)
        if len({digest(x) for x in prototypes}) != 1:
            raise ValueError('array item prototypes conflict at ' + location)
        schema['items'] = prototypes[0]
        if enums is not None and schema['items'].get('enum') != values:
            raise ValueError('array enum is not proven by explicit item enum at ' + location)
    elif children:
        raise ValueError('scalar declares child fields at ' + location)
    return schema


def object_fields(children, location):
    properties, required = {}, []
    for child in children:
        if not isinstance(child, dict) or not isinstance(child.get('name'), str) or not child['name'] or child['name'] in properties or type(child.get('isRequired')) is not bool:
            raise ValueError('invalid/duplicate Similarweb field or requiredness at ' + location)
        properties[child['name']] = field_schema(child, location + '.' + child['name'])
        if child['isRequired']: required.append(child['name'])
    return {'properties': properties, **({'required': required} if required else {})}


def convert_reference(raw, expected_path, source_url):
    if not source_url.startswith('https://docs.similarweb.com/api-v5/'):
        raise ValueError('official Similarweb source URL required')
    parser = CanonicalURL()
    parser.feed(raw.decode())
    if parser.urls != [source_url]:
        raise ValueError('official Similarweb canonical source URL mismatch')
    section = declaration(raw, expected_path)
    responses = section.get('responses')
    if not isinstance(responses, list) or len(responses) != 1 or responses[0].get('statusCode') != 200 or responses[0].get('contentType') != 'application/json':
        raise ValueError('unsupported Similarweb response status/media declaration')
    response = responses[0]
    schema = {'type': 'object', **object_fields(response['body'], 'response')}
    return {'openapi':'3.1.0','info':{'title':'Similarweb explicit response declaration','version':str(section['schemaVersion'])},
        'servers':[{'url':ORIGIN}], 'paths':{expected_path:{'get':{'responses':{'200':{
            'description':response['description'],'content':{'application/json':{'schema':schema}}}}}}}}, {
        'kind':'manual','converter':VERSION,'refresh_policy':'automatic','source_pages':[{'url':source_url,
            'raw_content_hash':'sha256:'+hashlib.sha256(raw).hexdigest()}],
        'limits':['UI value fields are example values, not defaults. Named array children and differing prototypes fail closed.']}


def convert_response_only_reference(raw, expected_path, source_url, public_path):
    """Prepare a response-only candidate for the reviewed AIsa v5 path mapping."""
    if not expected_path.startswith('/v5/') or public_path != '/apis/v1/similarweb/' + expected_path[len('/v5/'):]:
        raise ValueError('Similarweb public response mapping requires exact v5 suffix')
    document, metadata = convert_reference(raw, expected_path, source_url)
    document['paths'] = {public_path: document['paths'][expected_path]}
    document['servers'] = [{'url': 'https://api.aisa.one'}]
    metadata.update(response_only=True, path_space='public',
        upstream_path_sha256=hashlib.sha256(expected_path.encode()).hexdigest(),
        upstream_origin_sha256=hashlib.sha256(ORIGIN.rstrip('/').encode()).hexdigest())
    return document, metadata
