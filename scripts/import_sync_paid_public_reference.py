"""Import provider request references for the Treg, Composio and Firecrawl Alexandria gateways.

These catalogs publish typed per-operation input descriptors, not OpenAPI. The
converter maps only declared machine fields (type, requiredness, enum, bounds,
default, example) to JSON Schema at the exact AIsa public route; prose is kept
as description and never turned into constraints. Undeclared nested shapes
stay unconstrained. Runtime facts remain authoritative for identity, status,
prices and the fields the gateway itself validates.

Usage:
  python3 scripts/import_sync_paid_public_reference.py --facts-dir DIR \
    --treg-dir DIR --composio-schemas FILE --firecrawl-captures DIR... --fetched-at ISO --write
"""
import argparse
import copy
import glob
import hashlib
import json
from pathlib import Path

from source_governance import initial_policy

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'scripts/import_sync_paid_public_reference.py@1'
SERVER = [{'url': 'https://api.aisa.one'}]
SOURCES = {
    'treg': ('treg-public.json', 'Treg catalog request reference', 'https://treg.to/catalog/endpoints'),
    'composio': ('composio-public.json', 'Composio Connect tool input reference', 'https://connect.composio.dev/mcp'),
    'firecrawl_alexandria': ('firecrawl-alexandria-public.json', 'Firecrawl Alexandria capability reference', 'https://api.firecrawl.dev/v2/scrape'),
}
DOCUMENTED = {'provider', 'mixed'}


def canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def runtime_operations(facts_dir, catalog):
    document = json.loads((facts_dir / f'{catalog}.json').read_text())
    result = {}
    for path, item in document['paths'].items():
        for method, operation in item.items():
            if isinstance(operation, dict) and 'operationId' in operation and operation.get('x-aisa-validation') in DOCUMENTED:
                result[operation['operationId']] = (path, method)
    return result


def describe(*parts):
    text = '\n\n'.join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    return {'description': text} if text else {}


# Treg declares fields in its own compact vocabulary.
TREG_ARRAYS = {'array[string]': 'string', 'array[object]': 'object', 'array[integer]': 'integer'}


def treg_schema(spec):
    if not isinstance(spec, dict):
        return describe(spec)
    kind = spec.get('type')
    out = describe(spec.get('description'), spec.get('note'))
    if kind in ('string', 'integer', 'number', 'boolean', 'object'):
        out['type'] = kind
    elif kind == 'dict':
        out['type'] = 'object'
    elif kind in ('array', 'list') or kind in TREG_ARRAYS:
        out['type'] = 'array'
        if kind in TREG_ARRAYS:
            out['items'] = {'type': TREG_ARRAYS[kind]}
        elif isinstance(spec.get('items'), dict):
            out['items'] = treg_schema(spec['items'])
    elif kind == 'string_or_array':
        out['anyOf'] = [{'type': 'string'}, {'type': 'array', 'items': {'type': 'string'}}]
    if isinstance(spec.get('anyOf'), list):
        out['anyOf'] = [treg_schema(x) for x in spec['anyOf']]
    numeric = out.get('type') in ('integer', 'number')
    for source, target in (('min', 'minimum' if numeric else None), ('max', 'maximum' if numeric else None),
                           ('minimum', 'minimum'), ('maximum', 'maximum'), ('minLength', 'minLength'),
                           ('maxLength', 'maxLength'), ('minItems', 'minItems'), ('maxItems', 'maxItems'), ('format', 'format')):
        if target and source in spec:
            out[target] = spec[source]
    if out.get('type') == 'string':
        out.update({k: spec[s] for s, k in (('min', 'minLength'), ('max', 'maxLength')) if s in spec and k not in out})
    if out.get('type') == 'array':
        out.update({k: spec[s] for s, k in (('min', 'minItems'), ('max', 'maxItems')) if s in spec and k not in out})
    if isinstance(spec.get('enum'), list):
        out['enum'] = spec['enum']
    if 'default' in spec:
        out['default'] = spec['default']
    if 'example' in spec:
        out['examples'] = [spec['example']]
    if isinstance(spec.get('properties'), dict):
        out.setdefault('type', 'object')
        out['properties'] = {k: treg_schema(v) for k, v in spec['properties'].items()}
    if isinstance(spec.get('additionalProperties'), bool):
        out['additionalProperties'] = spec['additionalProperties']
    return out


def treg_operation(endpoint):
    source = endpoint.get('input') or {}
    operation = {'summary': endpoint.get('name') or endpoint['id'], **describe(endpoint.get('summary'), source.get('note'))}
    parameters = []
    # Treg's call API receives path placeholders as query parameters.
    for section, default_required in (('pathParams', True), ('queryParams', False)):
        for name, spec in (source.get(section) or {}).items():
            schema = treg_schema(spec)
            parameter = {'name': name, 'in': 'query', 'required': bool(spec.get('required', default_required)) if isinstance(spec, dict) else default_required}
            if 'description' in schema:
                parameter['description'] = schema.pop('description')
            parameter['schema'] = schema
            parameters.append(parameter)
    if parameters:
        operation['parameters'] = parameters
    body = source.get('body')
    if isinstance(body, dict) and source.get('bodyType') in (None, 'json'):
        schema = {'type': 'object', 'properties': {k: treg_schema(v) for k, v in body.items()}}
        required = sorted(k for k, v in body.items() if isinstance(v, dict) and v.get('required') is True)
        if required:
            schema['required'] = required
        operation['requestBody'] = {'required': bool(required), 'content': {'application/json': {'schema': schema}}}
    return operation


def drop_dangling_mappings(node, root):
    """Composio inlines $defs but keeps discriminator mappings to them; a
    mapping is an annotation, so drop one whose target is absent."""
    if isinstance(node, list):
        for value in node:
            drop_dangling_mappings(value, root)
    elif isinstance(node, dict):
        mapping = node.get('discriminator', {}).get('mapping') if isinstance(node.get('discriminator'), dict) else None
        if isinstance(mapping, dict) and any(not isinstance(ref, str) or not ref.startswith('#/') or ref[2:].split('/')[0] not in root for ref in mapping.values()):
            del node['discriminator']['mapping']
        for value in node.values():
            drop_dangling_mappings(value, root)


def composio_operation(tool, slug):
    arguments = copy.deepcopy(tool['input_schema'])
    drop_dangling_mappings(arguments, arguments)
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['account', 'arguments', 'tool_slug'],
              'properties': {'tool_slug': {'type': 'string', 'enum': [slug]}, 'arguments': arguments,
                             'account': {'type': 'string', 'enum': ['instant_account']},
                             'enable_auto_workbench_offload': {'type': 'boolean', 'enum': [False]}}}
    return {'summary': slug, **describe(tool.get('description')),
            'requestBody': {'required': True, 'content': {'application/json': {'schema': schema}}}}


FIRECRAWL_TYPES = {'string': 'string', 'number': 'number', 'boolean': 'boolean', 'object': 'object'}


def firecrawl_option(option):
    kind = option['type']
    out = describe(option.get('about'))
    if kind.endswith('[]'):
        out['type'] = 'array'
        if kind[:-2] in FIRECRAWL_TYPES:
            out['items'] = {'type': FIRECRAWL_TYPES[kind[:-2]]}
        bounds = ('minItems', 'maxItems')
    else:
        if kind in FIRECRAWL_TYPES:
            out['type'] = FIRECRAWL_TYPES[kind]
        bounds = ('minimum', 'maximum') if kind == 'number' else ('minLength', 'maxLength') if kind == 'string' else (None, None)
    for source, target in zip(('min', 'max'), bounds):
        if target and source in option:
            out[target] = option[source]
    if isinstance(option.get('oneOf'), list):
        out['enum'] = option['oneOf']
    if 'default' in option:
        out['default'] = option['default']
    return out


def firecrawl_operation(item):
    options = {o['name']: firecrawl_option(o) for o in item['options']}
    option_schema = {'type': 'object', 'properties': options}
    required = sorted(o['name'] for o in item['options'] if o.get('required') is True)
    if required:
        option_schema['required'] = required
    groups = [g for g in item.get('requiresOneOf') or [] if isinstance(g, list) and g]
    if groups:
        option_schema['allOf'] = [{'anyOf': [{'required': [name]} for name in group]} for group in groups]
    call = {'type': 'object', 'additionalProperties': False, 'required': ['capability', 'provider'] + (['options'] if required or groups else []),
            'properties': {'provider': {'type': 'string', 'enum': [item['provider']]},
                           'capability': {'type': 'string', 'enum': [item['capability']]}, 'options': option_schema}}
    schema = {'type': 'object', 'required': ['alexandria', 'zeroDataRetention'],
              'properties': {'alexandria': call, 'zeroDataRetention': {'type': 'boolean'}}}
    if isinstance(item.get('example'), dict):
        schema['examples'] = [{'alexandria': {'provider': item['provider'], 'capability': item['capability'], 'options': item['example']}, 'zeroDataRetention': False}]
    return {'summary': item.get('name') or item['id'], **describe(item.get('description')),
            'requestBody': {'required': True, 'content': {'application/json': {'schema': schema}}}}


def load_firecrawl(capture_dirs):
    items = {}
    for directory in capture_dirs:
        for path in sorted(glob.glob(str(Path(directory) / '**' / '*.json'), recursive=True)):
            document = json.loads(Path(path).read_text())
            response = document.get('response') if isinstance(document, dict) else None
            if not isinstance(response, dict):
                continue
            for result in response.get('data', {}).get('alexandria', []):
                if (result.get('provider'), result.get('capability'), result.get('creditsCost')) != ('firecrawl', 'find-tools', 0):
                    raise ValueError(f'{path}: not a free find-tools capture')
                for item in (result.get('data') or {}).get('items', []):
                    items[item['provider'] + '#' + item['capability']] = item
    return items


def build(catalog, runtime, sources, fetched_at):
    filename, title, url = SOURCES[catalog]
    paths, used = {}, {}
    for operation_id, (path, method) in sorted(runtime.items()):
        source = sources.get(operation_id)
        if source is None:
            continue
        used[operation_id] = source
        if catalog == 'treg':
            operation = treg_operation(source)
        elif catalog == 'composio':
            operation = composio_operation(source, operation_id)
        else:
            operation = firecrawl_operation(source)
        operation['operationId'] = operation_id
        paths.setdefault(path, {})[method] = operation
    provenance = initial_policy({'kind': 'manual', 'url': url, 'fetched_at': fetched_at, 'content_hash': canonical_hash(used),
                                 'converter': VERSION, 'path_space': 'public'})
    document = {'openapi': '3.1.0', 'info': {'title': title, 'version': fetched_at[:10], 'x-aisa-source': provenance},
                'servers': SERVER, 'paths': paths}
    return filename, document, len(runtime) - len(used)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--facts-dir', type=Path, required=True)
    parser.add_argument('--treg-dir', type=Path, required=True)
    parser.add_argument('--composio-schemas', type=Path, required=True)
    parser.add_argument('--firecrawl-captures', type=Path, nargs='+', required=True)
    parser.add_argument('--fetched-at', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    treg = {}
    for path in sorted(args.treg_dir.glob('*.json')):
        endpoint = json.loads(path.read_text()).get('endpoint')
        if isinstance(endpoint, dict) and endpoint.get('id') == path.stem:
            treg[path.stem] = endpoint
    composio = json.loads(args.composio_schemas.read_text())
    sources = {'treg': treg, 'composio': composio, 'firecrawl_alexandria': load_firecrawl(args.firecrawl_captures)}
    summary = {}
    for catalog in SOURCES:
        filename, document, missing = build(catalog, runtime_operations(args.facts_dir, catalog), sources[catalog], args.fetched_at)
        operations = sum(len(item) for item in document['paths'].values())
        summary[catalog] = {'file': filename, 'operations': operations, 'without_source': missing}
        if args.write:
            (ROOT / 'openapi/upstream' / filename).write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
