#!/usr/bin/env python3
"""Convert locked official FRED HTML parameter references; never infer response schemas."""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
from compose_openapi import digest
from source_json import checked_float

INDEX = 'https://fred.stlouisfed.org/docs/api/fred/'
CONVERTER = 'scripts/import_fred_reference.py@4'
GEO_REFERENCE = {
    '/geofred/shapes/file': 'shapes.html',
    '/geofred/series/group': 'series_group.html',
    '/geofred/series/data': 'series_data.html',
    '/geofred/regional/data': 'regional_data.html',
}
VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'wbr', 'source'}


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self, skip=()):
        return ' '.join(' '.join(c if isinstance(c, str) else c.text(skip)
                                for c in self.children if isinstance(c, str) or c.tag not in skip).split())

    def raw_text(self):
        return ''.join(c if isinstance(c, str) else c.raw_text() for c in self.children)

    def all(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.all(tag)


class Tree(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(raw.decode('utf-8'))

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def official_url(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.netloc != 'fred.stlouisfed.org' or not parts.path.startswith('/docs/api/') or parts.query or parts.fragment:
        raise ValueError('only canonical official FRED reference URLs are allowed')
    return url


class OfficialRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Validate before following a redirect; never contact a business API or
        # another host and only reject its response afterwards.
        official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    with build_opener(OfficialRedirectHandler()).open(official_url(url), timeout=40) as response:
        official_url(response.url)
        raw = response.read((2 << 20) + 1)
        if len(raw) > 2 << 20:
            raise ValueError('official reference exceeds 2MiB bound')
        return raw


def parameter(name, nodes, defaults=None):
    bullets = [node.text(skip={'p', 'ul', 'ol'}) for node in nodes if node.tag == 'li']
    if defaults and name in defaults and not any('default:' in s for s in bullets):
        bullets.append('optional, default: ' + defaults[name])
    declarations = [s for s in bullets if re.search(r'\b(required|optional)\b|default:', s)]
    if not declarations:
        raise ValueError(f'{name}: required/optional is not stated')
    declaration = declarations[0]
    required = bool(re.search(r'\brequired\b', declaration))
    if 'integer' in declaration.lower():
        schema = {'type': 'integer'}
    elif 'string' in declaration.lower() or any(re.match(r'On(?:e)? of the following (?:strings|values):', s) for s in bullets):
        schema = {'type': 'string'}
    elif 'boolean' in declaration:
        schema = {'type': 'boolean'}
    else:
        raise ValueError(f'{name}: unsupported type declaration {declaration!r}')
    if 'YYYY-MM-DD formatted string' in declaration:
        schema['format'] = 'date'
    bound = re.search(r'integer between (\d+) and (\d+)', declaration)
    if bound:
        schema.update(minimum=int(bound[1]), maximum=int(bound[2]))
    elif 'non-negative integer' in declaration:
        schema['minimum'] = 0
    elif re.search(r'\b(between|at least|at most|greater than|less than)\b', declaration):
        raise ValueError(f'{name}: unsupported numeric constraint {declaration!r}')
    for node in (n for n in nodes if n.tag == 'li'):
        bullet = node.text(skip={'p', 'ul', 'ol'})
        if re.match(r'On(?:e)? of the following (?:values|strings):', bullet):
            values = re.findall(r"'([^']*)'", bullet)
            if not values:
                # Regional Data declares region_type as nested list items,
                # rather than quoted values in the parent bullet.
                children = [child for child in node.children
                            if isinstance(child, Node) and child.tag in ('ul', 'ol')]
                values = [item.text() for child in children for item in child.all('li')]
                if any(not re.fullmatch(r'[a-zA-Z0-9_]+', value) for value in values):
                    raise ValueError(f'{name}: unsupported nested enum declaration')
            if not values:
                raise ValueError(f'{name}: unsupported enum declaration')
            schema['enum'] = [int(v) for v in values] if schema['type'] == 'integer' else values
    default = re.search(r'default:\s*([^\s(]+)', declaration)
    # Search ordering has defaults conditional on another parameter. Preserve
    # that rule in the description, not as a bogus literal default of "If".
    if default and not re.search(r'default:\s*[Ii]f\b', declaration):
        token = default[1].rstrip('.')
        if token not in ('today\'s', 'no') and (schema.get('format') != 'date' or re.fullmatch(r'\d{4}-\d{2}-\d{2}', token)):
            if schema['type'] == 'integer':
                if not re.fullmatch(r'\d+', token):
                    raise ValueError(f'{name}: unsupported integer default')
                value = int(token)
            elif schema['type'] == 'boolean':
                if token not in ('true', 'false'):
                    raise ValueError(f'{name}: unsupported boolean default')
                value = token == 'true'
            else:
                value = token
            if 'enum' in schema and value not in schema['enum']:
                raise ValueError(f'{name}: default absent from enum')
            schema['default'] = value
    # Descriptions retain conditional constraints and dynamic defaults exactly as
    # documented, rather than pretending prose is a second executable validator.
    paragraphs = [n.text() for n in nodes if n.tag in ('p', 'li')]
    description = '\n'.join(dict.fromkeys(x for x in paragraphs if x))
    return {'name': name, 'in': 'query', 'required': required, 'schema': schema,
            'description': description, 'x-aisa-reference-declarations': bullets}


def reference_identity(raw, url):
    official_url(url)
    tree = Tree(raw).root
    content = next((n for n in tree.all() if n.attrs.get('id') == 'content-container'), None)
    if content is None:
        raise ValueError('reference content container missing')
    title = next((n.text() for n in content.all('h1')), '')
    upstream = set()
    for node in content.all('pre'):
        for value in re.findall(r'https://api\.stlouisfed\.org/((?:fred|geofred)/[a-z_/]+)\?', node.text()):
            upstream.add('/' + value)
    if len(upstream) != 1:
        raise ValueError('unique official upstream request path missing')
    path = upstream.pop()
    if path.startswith('/fred/'):
        expected_url = INDEX + path.removeprefix('/fred/').replace('/', '_') + '.html'
        if url != expected_url or path != '/' + title:
            raise ValueError('reference title, request path and source URL disagree')
    elif path.startswith('/geofred/'):
        filename = GEO_REFERENCE.get(path)
        if filename is None or url != 'https://fred.stlouisfed.org/docs/api/geofred/' + filename:
            raise ValueError('GeoFRED request path and source URL disagree')
    if not any('Request (HTTPS GET)' == n.text() for n in content.all() if n.tag in ('h3','h4')):
        raise ValueError('official GET method declaration missing')
    return content, title, path


def unique_json_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON response example member')
        result[key] = value
    return result


def reject_json_constant(token):
    raise ValueError('non-JSON response example constant')


def response_evidence(content):
    # Carry explicit representations/examples, never infer schema from samples.
    media = set(re.findall(r'HTTP Content-Type is ([a-z]+/[a-z0-9.+-]*[a-z0-9+-])', content.text()))
    content_values, pending, declarations = {}, [], []
    representation, response = None, False
    for node in content.all():
        if node.tag == 'h2':
            representation, response = None, False
        elif node.tag == 'h3' and node.text() in ('XML', 'JSON'):
            representation, response = node.text(), False
        elif node.tag in ('h3', 'h4') and node.text() == 'Response':
            response = True
        elif node.tag in ('h3', 'h4') and node.text().startswith('Request'):
            response = False
        elif node.tag == 'p' and response and representation == 'XML':
            # These are explicit XML attribute declarations, not facts learned
            # from example values or statements about the JSON representation.
            match = re.fullmatch(r"The ([A-Za-z_][A-Za-z0-9_.-]*) tag's "
                                 r"([A-Za-z_][A-Za-z0-9_.-]*)(?: and ([A-Za-z_][A-Za-z0-9_.-]*))? "
                                 r"attributes? (?:is|are) optional\.", node.text())
            if match:
                element, first, second = match.groups()
                for attribute in (first, second):
                    if attribute is not None:
                        declaration = {'media_type': 'text/xml', 'element': element,
                                       'attribute': attribute, 'required': False,
                                       'source_statement': node.text()}
                        if declaration not in declarations:
                            declarations.append(declaration)
        elif node.tag == 'pre' and response:
            raw = node.raw_text().strip().strip('`').strip()
            kind = {'XML': 'text/xml', 'JSON': 'application/json'}.get(representation)
            # GeoFRED shapes explicitly says that only JSON is returned.
            if kind is None and 'only returns the shape files as json' in content.text():
                kind = 'application/json'
            if kind is None:
                pending.append({'reason': 'response representation not explicitly declared'})
                continue
            if kind == 'application/json':
                try:
                    value = json.loads(raw, object_pairs_hook=unique_json_members, parse_float=checked_float, parse_constant=reject_json_constant)
                except (ValueError, TypeError):
                    pending.append({'media_type': kind, 'reason': 'official JSON response example is not valid JSON',
                                    'example_sha256': hashlib.sha256(raw.encode()).hexdigest()})
                    continue
            else:
                from xml.etree import ElementTree
                if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
                    pending.append({'media_type': kind, 'reason': 'XML declarations are unsupported'})
                    continue
                try:
                    ElementTree.fromstring(raw)
                except ElementTree.ParseError:
                    pending.append({'media_type': kind, 'reason': 'official XML response example is not well formed',
                                    'example_sha256': hashlib.sha256(raw.encode()).hexdigest()})
                    continue
                value = raw
            bucket = content_values.setdefault(kind, {'examples': {}})['examples']
            bucket['official_' + str(len(bucket) + 1)] = {'value': value, 'description': 'Official response example only; not a complete payload schema.'}
    for kind in sorted(media):
        content_values.setdefault(kind, {})
    return {'content': content_values, 'pending': pending,
            'field_declarations': declarations,
            'schema_status': 'not_declared_in_reference', 'schema_inferred': False}


def parse_reference(raw, url):
    content, title, path = reference_identity(raw, url)
    defaults = dict(re.findall(r'default value of ([a-z_]+) is ([a-z0-9_]+)\.', content.text()))
    all_nodes = list(content.all())
    starts = [i for i,n in enumerate(all_nodes) if n.tag == 'h2' and n.text() == 'Parameters']
    if not starts:
        raise ValueError('parameter section missing')
    description = ''
    in_description = False
    for node in all_nodes[:starts[-1]]:
        if node.tag == 'h2':
            in_description = node.text() == 'Description'
        elif in_description and node.tag == 'p' and not description:
            description = node.text()
    parameters, name, nodes, in_parameters = [], None, [], False
    for node in all_nodes[starts[-1]:]:
        if node.tag == 'h2':
            if node.text() == 'Parameters':
                in_parameters = True
            elif in_parameters:
                raise ValueError('unexpected section after Parameters')
        elif in_parameters and node.tag == 'h3':
            if name is not None:
                parameters.append(parameter(name, nodes, defaults))
            name, nodes = node.text(), []
            if not re.fullmatch(r'[a-z_]+', name):
                raise ValueError('invalid parameter section name')
        elif in_parameters and name:
            nodes.append(node)
    if name is not None:
        parameters.append(parameter(name, nodes, defaults))
    if not parameters or len({p['name'] for p in parameters}) != len(parameters):
        raise ValueError('empty or duplicate parameter declarations')
    if not any(p['name'] == 'api_key' and p['required'] for p in parameters):
        raise ValueError('official provider authentication declaration missing')
    evidence = response_evidence(content)
    response = {'description': 'Official representation and examples only; no complete response schema is declared.'}
    if evidence['content']:
        response['content'] = evidence['content']
    return path, {'summary': description or title, 'description': description,
                  'parameters': parameters, 'security': [{'fred_api_key': []}],
                  'externalDocs': {'url': url}, 'responses': {'200': response},
                  'x-aisa-response-evidence': evidence}


def import_reference(provider, url=INDEX, fetcher=None):
    if provider != 'fred' or url != INDEX:
        raise ValueError('FRED converter requires provider fred and its canonical official index')
    fetcher = fetcher or fetch
    index = fetcher(url)
    links = {}
    for link in Tree(index).root.all('a'):
        text = link.text()
        href = link.attrs.get('href', '')
        if re.fullmatch(r'fred/[a-z_/]+', text) or href.startswith('/docs/api/geofred/') and href.endswith('.html'):
            destination = official_url(urljoin(url, link.attrs.get('href', '')))
            if text in links and links[text] != destination:
                raise ValueError('ambiguous official index endpoint')
            links[text] = destination
    if not links:
        raise ValueError('official index has no FRED endpoint references')
    paths, sources, pending, identities = {}, [], [], []
    for title, destination in sorted(links.items()):
        raw = fetcher(destination)
        source = {'url': destination, 'sha256': hashlib.sha256(raw).hexdigest()}
        sources.append(source)
        # Method/path proof is independent of complete parameter declarations.
        # Incomplete requests are evidence only, never emitted in paths.
        content, reference_title, identity_path = reference_identity(raw, destination)
        if identity_path in {row['path'] for row in identities} or title.startswith('fred/') and identity_path != '/' + title:
            raise ValueError('index and reference path disagree')
        identity = dict(source, path=identity_path, method='GET',
                        identity_source='official_reference_path_and_explicit_method',
                        response_evidence=response_evidence(content))
        identities.append(identity)
        try:
            path, operation = parse_reference(raw, destination)
        except ValueError as error:
            pending.append(dict(source, path=identity_path, method='GET', reason=str(error)))
            identity.update(request_status='pending', request_reason=str(error))
            continue
        if title.startswith('fred/') and path != '/' + title or path in paths:
            raise ValueError('index and reference path disagree')
        paths[path] = {'get': operation}
        source.update(path=path, parameter_count=len(operation['parameters']))
        identity.update(request_status='complete', parameter_count=len(operation['parameters']))
    source = {'kind': 'provider_openapi', 'url': url, 'converter': CONVERTER,
              'fetched_at': datetime.now(timezone.utc).isoformat(),
              'index_sha256': hashlib.sha256(index).hexdigest(), 'references': sources, 'pending_references': pending,
              'operation_identity_evidence': identities,
              'request_contract_source': 'official_html_parameter_declarations',
              'response_schema_available': False,
              'response_example_contract': 'authoritative examples retained without schema inference or debt closure',
              'limitations': ['Conditional prose constraints remain descriptions, not executable validation.',
                             'References with incomplete type or required/optional declarations are explicitly pending and not emitted.']}
    document = {'openapi': '3.1.0', 'info': {'title': 'Official FRED reference', 'version': 'reference-html-1', 'x-aisa-source': source},
                'servers': [{'url': 'https://api.stlouisfed.org'}], 'paths': paths,
                'components': {'securitySchemes': {'fred_api_key': {'type': 'apiKey', 'in': 'query', 'name': 'api_key'}}}}
    source['content_hash'] = digest({**document, 'info': {key: value for key, value in document['info'].items() if key != 'x-aisa-source'}})
    return document


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = import_reference('fred')
    if args.write:
        destination = args.root / 'openapi/upstream/fred-official.json'
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
