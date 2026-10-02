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
from urllib.request import urlopen
from compose_openapi import digest

INDEX = 'https://fred.stlouisfed.org/docs/api/fred/'
CONVERTER = 'scripts/import_fred_reference.py@2'
VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'wbr', 'source'}


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self, skip=()):
        return ' '.join(' '.join(c if isinstance(c, str) else c.text(skip)
                                for c in self.children if isinstance(c, str) or c.tag not in skip).split())

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


def fetch(url):
    with urlopen(official_url(url), timeout=40) as response:
        official_url(response.url)
        return response.read()


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


def parse_reference(raw, url):
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
    if not any('Request (HTTPS GET)' == n.text() for n in content.all() if n.tag in ('h3','h4')):
        raise ValueError('official GET method declaration missing')
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
    return path, {'summary': description or title, 'description': description,
                  'parameters': parameters, 'security': [{'fred_api_key': []}],
                  'externalDocs': {'url': url},
                  'responses': {'200': {'description': 'Provider response in the requested file_type (XML by default). Official examples are not a complete response schema.'}}}


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
    paths, sources, pending = {}, [], []
    for title, destination in sorted(links.items()):
        raw = fetcher(destination)
        source = {'url': destination, 'sha256': hashlib.sha256(raw).hexdigest()}
        sources.append(source)
        try:
            path, operation = parse_reference(raw, destination)
        except ValueError as error:
            pending.append(dict(source, reason=str(error)))
            continue
        if title.startswith('fred/') and path != '/' + title or path in paths:
            raise ValueError('index and reference path disagree')
        paths[path] = {'get': operation}
        source.update(path=path, parameter_count=len(operation['parameters']))
    source = {'kind': 'provider_openapi', 'url': url, 'converter': CONVERTER,
              'fetched_at': datetime.now(timezone.utc).isoformat(),
              'index_sha256': hashlib.sha256(index).hexdigest(), 'references': sources, 'pending_references': pending,
              'request_contract_source': 'official_html_parameter_declarations',
              'response_schema_available': False,
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
