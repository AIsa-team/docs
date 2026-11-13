"""Preserve documented JSON filters, echoed request values and response unions."""
import copy

SOURCE_URL = 'https://raw.githubusercontent.com/dataforseo/OpenApiDocumentation/master/openapi_specification.yaml'
VERSION = 'scripts/import_dataforseo_filters.py@3'
VALUE = 'AisaDataforseoFilterJsonValue'
FILTERS = {'filters', 'initial_dataset_filters', 'backlinks_filters', 'relevant_pages_filters'}
SCHEMA_PREFIX = '#/components/schemas/'
# Sibling keywords of the upstream "nullable reference" wrapper. Inline
# properties are kept: they do not constrain null and still apply to objects.
REFERENCE_WRAPPER_KEYS = {'type', 'nullable', 'oneOf', 'description', 'deprecated', 'properties'}
# OpenAPI 3.0.3 null-only schema; composes to {"type": ["object", "null"], "enum": [null]}.
NULL_ONLY = {'type': 'object', 'nullable': True, 'enum': [None]}
NOT_SCHEMA_KEYS = {'example', 'examples', 'default', 'enum', 'const'}


def _single_reference(node):
    one_of = node.get('oneOf')
    if (isinstance(one_of, list) and len(one_of) == 1 and isinstance(one_of[0], dict)
            and set(one_of[0]) == {'$ref'} and isinstance(one_of[0]['$ref'], str)
            and one_of[0]['$ref'].startswith(SCHEMA_PREFIX)):
        return one_of[0]['$ref'][len(SCHEMA_PREFIX):]
    return None


def _nullable_reference(node):
    """Upstream's `{type: object, nullable: true, oneOf: [{$ref}]}` wrapper."""
    return (isinstance(node, dict) and node.get('type') == 'object' and node.get('nullable') is True
            and set(node) <= REFERENCE_WRAPPER_KEYS and _single_reference(node) is not None)


def _schema_nodes(node):
    """Every mapping below `node`, excluding example/default/enum payloads."""
    if isinstance(node, dict):
        yield node
        for key, child in node.items():
            if key not in NOT_SCHEMA_KEYS:
                yield from _schema_nodes(child)
    elif isinstance(node, list):
        for child in node:
            yield from _schema_nodes(child)


def _references(node):
    """Component names reached through `$ref` or a discriminator mapping."""
    for child in _schema_nodes(node):
        refs = [child.get('$ref')]
        mapping = child.get('discriminator', {}).get('mapping') if isinstance(child.get('discriminator'), dict) else None
        if isinstance(mapping, dict):
            refs += list(mapping.values())
        for ref in refs:
            if isinstance(ref, str) and ref.startswith(SCHEMA_PREFIX):
                yield ref[len(SCHEMA_PREFIX):]


def _response_roots(document):
    """Operation response objects and the component schemas only they reach.

    Request and response component graphs are disjoint in the official
    document; a component also reachable from a request is left unchanged so
    request validation never changes as a side effect of a response repair.
    """
    schemas = document.get('components', {}).get('schemas', {})

    def closure(roots):
        seen, stack = set(), list(roots)
        while stack:
            name = stack.pop()
            if name in seen or name not in schemas:
                continue
            seen.add(name)
            stack.extend(_references(schemas[name]))
        return seen

    responses, request_refs, response_refs = [], [], []
    for item in document.get('paths', {}).values():
        for operation in item.values():
            if not isinstance(operation, dict):
                continue
            request_refs += _references([operation.get('requestBody', {}), operation.get('parameters', [])])
            response_refs += _references(operation.get('responses', {}))
            responses.append(operation.get('responses', {}))
    names = closure(response_refs) - closure(request_refs)
    return responses + [schemas[name] for name in sorted(names)], names


def _discriminator_tag(prop, value):
    return {'type': 'object', 'required': [prop], 'properties': {prop: {'type': 'string', 'enum': [value]}}}


def _extension_nodes(schemas):
    """The `allOf[0]` wrapper through which a mapped subtype extends its base."""
    nodes = {}
    for base, schema in schemas.items():
        discriminator = schema.get('discriminator')
        if not isinstance(discriminator, dict) or not isinstance(discriminator.get('mapping'), dict):
            continue
        for ref in discriminator['mapping'].values():
            parts = schemas.get(str(ref)[len(SCHEMA_PREFIX):], {}).get('allOf')
            if isinstance(parts, list) and parts and isinstance(parts[0], dict):
                nodes[id(parts[0])] = base
    return nodes


def normalize_polymorphic_responses(document):
    """Let response item unions validate the documented subtype fields.

    Upstream declares each SERP/Labs/Merchant item base as a closed object
    (`additionalProperties: false`, the only such declarations in the source)
    and lists subtypes only in its discriminator mapping; each subtype extends
    the base through `allOf`. In JSON Schema a closed base rejects every
    subtype field, and an `items` that references only the base never
    validates subtype fields at all. For each closed response base whose
    mapped subtypes all extend it: open the base, pin each subtype's mapped
    discriminator value, and make each use site a discriminated union of the
    mapped subtypes (plus null, which its `nullable` wrapper declares). Field
    types, subtype selection and unknown discriminator values stay enforced.
    """
    schemas = document.get('components', {}).get('schemas', {})
    roots, response_names = _response_roots(document)
    extensions = _extension_nodes(schemas)
    bases = {}
    for name in sorted(response_names):
        schema = schemas[name]
        discriminator = schema.get('discriminator')
        if not isinstance(discriminator, dict) or not isinstance(discriminator.get('mapping'), dict):
            continue
        prop, subtypes = discriminator.get('propertyName'), {}
        for value, ref in discriminator['mapping'].items():
            target = str(ref)[len(SCHEMA_PREFIX):] if str(ref).startswith(SCHEMA_PREFIX) else None
            parts = schemas.get(target, {}).get('allOf')
            if not (target in response_names and isinstance(parts, list) and parts
                    and extensions.get(id(parts[0])) == name
                    and (_single_reference(parts[0]) == name or parts[0] == {'$ref': SCHEMA_PREFIX + name})):
                subtypes = None
                break
            subtypes[value] = target
        if not isinstance(prop, str) or not subtypes:
            continue
        tagged = all(_discriminator_tag(prop, v) in schemas[s]['allOf'] for v, s in subtypes.items())
        if schema.get('additionalProperties') is False or tagged:
            bases[name] = (prop, subtypes)
    owners = {}
    for base, (prop, subtypes) in bases.items():
        for value, subtype in subtypes.items():
            if subtype in owners:
                raise ValueError('DataForSEO subtype is mapped by more than one discriminator: ' + subtype)
            owners[subtype] = (prop, value)
    changed = []
    for base in bases:
        if schemas[base].get('additionalProperties') is False:
            del schemas[base]['additionalProperties']
            changed.append(('open_base', base))
    for subtype, (prop, value) in sorted(owners.items()):
        tag = _discriminator_tag(prop, value)
        if tag not in schemas[subtype]['allOf']:
            schemas[subtype]['allOf'].append(tag)
            changed.append(('tag_subtype', subtype))
    for root in roots:
        for node in _schema_nodes(root):
            base = _single_reference(node) if _nullable_reference(node) else None
            if id(node) in extensions or base not in bases:
                continue
            prop, subtypes = bases[base]
            node['oneOf'] = [{'$ref': SCHEMA_PREFIX + s} for s in subtypes.values()] + [copy.deepcopy(NULL_ONLY)]
            node['discriminator'] = {'propertyName': prop,
                                     'mapping': {v: SCHEMA_PREFIX + s for v, s in subtypes.items()}}
            changed.append(('union_site', base))
    return changed


def normalize_nullable_response_refs(document):
    """`nullable` on a single-reference wrapper means "the reference or null".

    OpenAPI 3.0.3 limits `nullable` to the same object's `type`, so the
    wrapper's `oneOf` still rejects null when its target is an object; the
    DataForSEO documentation states these fields can be null (e.g.
    `refinement_chips`, `rectangle` without `calculate_rectangles`). Add an
    explicit null-only branch on response wrappers whose target rejects null.
    Untyped targets already admit null; request schemas are left unchanged.
    """
    schemas = document.get('components', {}).get('schemas', {})
    roots, _ = _response_roots(document)
    extensions = _extension_nodes(schemas)
    changed = []
    for root in roots:
        for node in _schema_nodes(root):
            if id(node) in extensions or not _nullable_reference(node):
                continue
            name = _single_reference(node)
            target = schemas.get(name, {})
            if target.get('type') != 'object' or target.get('nullable') is True:
                continue
            node['oneOf'].append(copy.deepcopy(NULL_ONLY))
            changed.append(name)
    return changed


def normalize_response_echo(document):
    """Task data echoes arbitrary JSON request values, not object-only values.

    The official anchors/live example includes strings, a number and arrays.
    Restrict this correction to the known upstream placeholder on the shared
    task envelope; structured result schemas and request validation stay intact.
    """
    data = document.get('components', {}).get('schemas', {}).get(
        'BaseResponseTaskInfo', {}).get('properties', {}).get('data', {})
    if (data.get('type') != 'object' or data.get('additionalProperties') !=
            {'type': 'object', 'nullable': True}):
        return []
    data['additionalProperties'] = {}
    return [('BaseResponseTaskInfo', 'data')]


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
