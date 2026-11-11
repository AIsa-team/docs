"""Strictly convert public Theneo response declarations without fixing their types.

Named children of an array are ambiguous and rejected by default. A caller may
explicitly retain an incomplete outer array at reviewed paths; its item schema
then stays open and visibly unconfirmed. Raw values never become defaults.
"""
import copy
import hashlib
from html.parser import HTMLParser
import re
from source_json import loads
from compose_openapi import digest

VERSION = 'scripts/import_similarweb_response_reference.py@3'
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
    if (not expected_path.startswith('/') or expected_path.startswith('//')
            or section.get('endpoints') not in (
                {'method': 'get', 'path': expected_path},
                {'method': 'get', 'path': expected_path.lstrip('/')},
            )):
        raise ValueError('official Similarweb endpoint mismatch')
    same = [x for x in props['documents']['data']['transformedSection'] if x.get('_id') == section.get('_id')]
    if len(same) != 1 or same[0].get('urls', {}).get('Production') != [ORIGIN]:
        raise ValueError('official Similarweb production authority mismatch')
    return section


def field_parts(node, location):
    """Validate node semantics before either complete or partial conversion."""
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
    return schema, kind, children, enums


def reviewed_array_problem(children, location, outer_enums):
    """Recognize only the two reviewed, immediate item-definition conflicts."""
    if (len(children) != 1 or not isinstance(children[0], dict)
            or not str(children[0].get('name', '')).isdigit()):
        raise ValueError('reviewed incomplete array requires one numeric item prototype at ' + location)
    prototype = children[0]
    _, kind, fields, item_enums = field_parts(prototype, location + '[]')
    if kind != 'array':
        raise ValueError('reviewed incomplete array item is not an ambiguous array at ' + location)
    unconfirmed_enum = None
    if outer_enums is not None or item_enums is not None:
        if (not outer_enums or not item_enums or outer_enums != item_enums or fields
                or len({digest(item['value']) for item in outer_enums}) != len(outer_enums)):
            raise ValueError('reviewed incomplete array enum is not identically declared at both levels at ' + location)
        unconfirmed_enum = [copy.deepcopy(item['value']) for item in outer_enums]
    if not fields:
        return 'absent_array_item_schema', (
            'The provider labels the numeric item prototype as an array but supplies no '
            'schema for that prototype\'s elements. Its item definition remains unconfirmed; '
            'item types and fields are not enforced.'
        ), unconfirmed_enum
    names = set()
    for child in fields:
        if (not isinstance(child, dict) or not isinstance(child.get('name'), str)
                or not child['name'] or child['name'].isdigit() or child['name'] in names
                or type(child.get('isRequired')) is not bool):
            raise ValueError('reviewed incomplete array has a different item conflict at ' + location)
        field_parts(child, location + '[].' + child['name'])
        names.add(child['name'])
    return 'named_array_children', (
        'The provider labels the numeric item prototype as an array but declares named '
        'child fields inside it. Its item definition remains unconfirmed; item types '
        'and fields are not enforced.'
    ), None


def field_schema(node, location, incomplete_arrays=None):
    schema, kind, children, enums = field_parts(node, location)
    if incomplete_arrays is not None and location in incomplete_arrays:
        if kind != 'array':
            raise ValueError('reviewed incomplete path is not an array at ' + location)
        reason, description, unconfirmed_enum = reviewed_array_problem(children, location, enums)
        schema['items'] = {}
        schema['x-aisa-schema-status'] = 'item_definition_unconfirmed'
        if unconfirmed_enum is not None:
            schema['x-aisa-unconfirmed-item-enum'] = unconfirmed_enum
            description += ' The matching item enum declarations are retained only as an unconfirmed annotation and are not enforced.'
        schema['description'] = '\n\n'.join(filter(None, (schema.get('description'), description)))
        incomplete_arrays[location] = reason
        return schema
    if kind == 'object':
        schema.update(object_fields(children, location, incomplete_arrays))
    elif kind == 'array':
        prototypes = []
        for child in children:
            if not isinstance(child, dict) or not str(child.get('name', '')).isdigit():
                raise ValueError('array declares named child instead of an item at ' + location)
            prototypes.append(field_schema(child, location + '[]', incomplete_arrays))
        if not prototypes:
            raise ValueError('array item schema absent at ' + location)
        if len({digest(x) for x in prototypes}) != 1:
            raise ValueError('array item prototypes conflict at ' + location)
        schema['items'] = prototypes[0]
        if enums is not None and schema['items'].get('enum') != [x['value'] for x in enums]:
            raise ValueError('array enum is not proven by explicit item enum at ' + location)
    elif children:
        raise ValueError('scalar declares child fields at ' + location)
    return schema


def object_fields(children, location, incomplete_arrays=None):
    properties, required = {}, []
    for child in children:
        if not isinstance(child, dict) or not isinstance(child.get('name'), str) or not child['name'] or child['name'] in properties or type(child.get('isRequired')) is not bool:
            raise ValueError('invalid/duplicate Similarweb field or requiredness at ' + location)
        if incomplete_arrays and '.' in child['name']:
            raise ValueError('ambiguous reviewed array path: literal field name contains a dot at ' + location)
        properties[child['name']] = field_schema(child, location + '.' + child['name'], incomplete_arrays)
        if child['isRequired']: required.append(child['name'])
    return {'properties': properties, **({'required': required} if required else {})}


def convert_reference(raw, expected_path, source_url, *, incomplete_array_paths=()):
    if not source_url.startswith('https://docs.similarweb.com/api-v5/'):
        raise ValueError('official Similarweb source URL required')
    parser = CanonicalURL()
    parser.feed(raw.decode())
    if parser.urls != [source_url]:
        raise ValueError('official Similarweb canonical source URL mismatch')
    section = declaration(raw, expected_path)
    responses = section.get('responses')
    if not isinstance(responses, list):
        raise ValueError('unsupported Similarweb response status/media declaration')
    declarations = []
    identities = set()
    for index, response in enumerate(responses):
        if (not isinstance(response, dict) or type(response.get('statusCode')) is not int
                or not 100 <= response['statusCode'] <= 599
                or not isinstance(response.get('contentType'), str) or not response['contentType']):
            raise ValueError('unsupported Similarweb response status/media declaration')
        identity = response['statusCode'], response['contentType']
        if identity in identities:
            raise ValueError('duplicate Similarweb response status/media declaration')
        identities.add(identity)
        declarations.append({'status': identity[0], 'media_type': identity[1],
                             'pointer': f'/props/pageProps/initialSectionData/responses/{index}'})
    selected = [index for index, response in enumerate(responses)
                if (response['statusCode'], response['contentType']) == (200, 'application/json')]
    if len(selected) != 1:
        raise ValueError('one explicit Similarweb HTTP 200 application/json response required')
    if (isinstance(incomplete_array_paths, (str, bytes))
            or not isinstance(incomplete_array_paths, (tuple, list, set, frozenset))):
        raise ValueError('reviewed incomplete array paths must be an explicit collection')
    if any(not isinstance(path, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*', path)
           for path in incomplete_array_paths) or len(set(incomplete_array_paths)) != len(incomplete_array_paths):
        raise ValueError('invalid or duplicate reviewed incomplete array path')
    incomplete = {'response.' + path: None for path in incomplete_array_paths}
    response = responses[selected[0]]
    schema = {'type': 'object', **object_fields(response['body'], 'response', incomplete)}
    if any(reason is None for reason in incomplete.values()):
        raise ValueError('unused reviewed incomplete array path')
    return {'openapi':'3.1.0','info':{'title':'Similarweb explicit response declaration','version':str(section['schemaVersion'])},
        'servers':[{'url':ORIGIN}], 'paths':{expected_path:{'get':{'responses':{'200':{
            'description':response['description'],'content':{'application/json':{'schema':schema}}}}}}}}, {
        'kind':'manual','converter':VERSION,'refresh_policy':'automatic','source_pages':[{'url':source_url,
            'raw_content_hash':'sha256:'+hashlib.sha256(raw).hexdigest()}],
        'response_selection': {'selected': declarations[selected[0]],
            'omitted': [item for index, item in enumerate(declarations) if index != selected[0]]},
        'partial_response_scope': [{'path': path.removeprefix('response.'), 'reason': reason}
                                   for path, reason in sorted(incomplete.items())],
        'limits':['UI value fields are example values, not defaults. Named array children and differing prototypes fail closed unless an exact reviewed array path retains unconfirmed items.',
                  'Only the explicit HTTP 200 application/json declaration is selected; other status/media declarations are not projected.']}


def convert_response_only_reference(raw, expected_path, source_url, public_path, *, incomplete_array_paths=()):
    """Prepare a response-only candidate for the reviewed AIsa v5 path mapping."""
    if not expected_path.startswith('/v5/') or public_path != '/apis/v1/similarweb/' + expected_path[len('/v5/'):]:
        raise ValueError('Similarweb public response mapping requires exact v5 suffix')
    document, metadata = convert_reference(raw, expected_path, source_url,
                                           incomplete_array_paths=incomplete_array_paths)
    document['paths'] = {public_path: document['paths'][expected_path]}
    document['servers'] = [{'url': 'https://api.aisa.one'}]
    metadata.update(response_only=True, path_space='public',
        upstream_path_sha256=hashlib.sha256(expected_path.encode()).hexdigest(),
        upstream_origin_sha256=hashlib.sha256(ORIGIN.rstrip('/').encode()).hexdigest())
    return document, metadata
