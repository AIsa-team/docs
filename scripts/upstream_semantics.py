"""Compare upstream declarations for review, never infer execution compatibility.

Only local OpenAPI references are resolved. Recursive/external reference scopes
are reported as uncertain rather than fetching or guessing their meaning.
"""
import copy

from compose_openapi import METHODS, digest, resolve

PROSE = {'description', 'summary', 'title', 'example', 'examples', '$comment',
         'externalDocs', 'tags', 'x-aisa-source', 'x-aisa-notes'}
# These objects are maps: names such as "description" are contract field names.
MAPS = {'properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas',
        'headers', 'content', 'encoding', 'links', 'callbacks', 'variables',
        'responses', 'securitySchemes', 'dependentRequired', 'dependencies', 'mapping'}
UNSUPPORTED_SCOPE = {'$dynamicRef', '$recursiveRef', '$dynamicAnchor', '$recursiveAnchor', '$id', '$anchor', '$schema', '$vocabulary'}


def semantic_value(value, map_object=False):
    if isinstance(value, list):
        return [semantic_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    if not map_object and set(value) & UNSUPPORTED_SCOPE:
        raise ValueError('unsupported_schema_reference_scope')
    result = {}
    for key, item in value.items():
        if not map_object and key in PROSE:
            continue
        result[key] = (copy.deepcopy(item) if not map_object and (key in {'default', 'const', 'enum'} or key.startswith('x-'))
                       else semantic_value(item, key in MAPS and not map_object))
        if not map_object and key in {'required', 'enum', 'type', 'allOf', 'anyOf', 'oneOf'} and isinstance(result[key], list):
            result[key] = sorted(result[key], key=digest)
    return result


def parameter_view(parameter):
    result = semantic_value(parameter)
    location = result.get('in')
    if not result.get('name') or location not in {'path', 'query', 'header', 'cookie'}:
        raise ValueError('invalid_parameter_identity')
    if location == 'path' and parameter.get('required') is not True:
        raise ValueError('invalid_path_parameter_requiredness')
    result.setdefault('required', False)
    result.setdefault('deprecated', False)
    result.setdefault('allowEmptyValue', False)
    result.setdefault('allowReserved', False)
    if 'content' not in result:
        result.setdefault('style', 'form' if location in {'query', 'cookie'} else 'simple')
        result.setdefault('explode', result['style'] == 'form')
    return result


def effective_operation(document, path, method, item):
    operation = resolve(item[method], document)
    parameters = {}
    for values in (item.get('parameters', []), operation.get('parameters', [])):
        own_keys = set()
        for raw in values:
            parameter = parameter_view(resolve(raw, document))
            key = (parameter['in'], parameter['name'])
            if key in own_keys:
                raise ValueError('duplicate_parameter_identity')
            own_keys.add(key)
            parameters[key] = parameter
    security = resolve(operation.get('security', document.get('security', [])), document)
    requirements, schemes = [], {}
    for alternative in security:
        if not isinstance(alternative, dict):
            raise ValueError('invalid_security_requirement')
        if any(not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes)
               for scopes in alternative.values()):
            raise ValueError('invalid_security_scopes')
        requirements.append({name: sorted(scopes) for name, scopes in alternative.items()})
        for name in alternative:
            scheme = document.get('components', {}).get('securitySchemes', {}).get(name)
            if scheme is None:
                raise ValueError('missing_security_scheme')
            schemes[name] = semantic_value(resolve(scheme, document))
    body = operation.get('requestBody')
    if body is not None:
        body = semantic_value(body)
        body.setdefault('required', False)
    servers = operation.get('servers', item.get('servers', document.get('servers', [])))
    return {
        'binding': {'method': method.upper(), 'path': path,
                    'servers': semantic_value(resolve(servers or [{'url': '/'}], document))},
        'identity': {'operationId': operation.get('operationId')},
        'operation': {'deprecated': operation.get('deprecated', False),
                      'extensions': {key: copy.deepcopy(value) for key, value in operation.items()
                                     if key.startswith('x-') and key not in PROSE}},
        'request': {'parameters': [parameters[key] for key in sorted(parameters)], 'body': body},
        'authentication': {'requirements': sorted(requirements, key=digest), 'schemes': schemes},
        'responses': semantic_value(operation.get('responses', {}), True),
        'callbacks': semantic_value(operation.get('callbacks', {}), True),
    }


def path_item(raw, document, stack=()):
    if not isinstance(raw, dict):
        raise ValueError('invalid_path_item')
    if '$ref' not in raw:
        return raw
    ref = raw['$ref']
    if not isinstance(ref, str) or not ref.startswith('#/') or ref in stack:
        raise ValueError('unresolved_path_item_reference')
    target = document
    for part in ref[2:].split('/'):
        target = target[part.replace('~1', '/').replace('~0', '~')]
    if set(raw) - {'$ref', 'summary', 'description'}:
        raise ValueError('ambiguous_path_item_reference_siblings')
    return path_item(target, document, stack + (ref,))


def operations(document):
    result, uncertain = {}, {}
    for path, raw in document.get('paths', {}).items():
        try:
            item = path_item(raw, document)
        except (ValueError, KeyError, TypeError) as exc:
            uncertain[(path, '*')] = type(exc).__name__ + ': path_item_reference_unresolved'
            continue
        for method in sorted(METHODS & item.keys()):
            key = (path, method)
            try:
                result[key] = effective_operation(document, path, method, item)
            except (ValueError, KeyError, TypeError) as exc:
                # Do not echo external ref URLs or arbitrary source text.
                message = str(exc) if isinstance(exc, ValueError) else 'invalid_or_missing_local_declaration'
                uncertain[key] = type(exc).__name__ + ': ' + message
    return result, uncertain


def field_changes(previous, updated, pointer=''):
    if previous == updated:
        return []
    if isinstance(previous, dict) and isinstance(updated, dict):
        changes = []
        for key in sorted(previous.keys() | updated.keys()):
            field = pointer + '/' + str(key).replace('~', '~0').replace('/', '~1')
            if key not in previous:
                changes.append({'field': field, 'change': 'added', 'after': updated[key]})
            elif key not in updated:
                changes.append({'field': field, 'change': 'removed', 'before': previous[key]})
            else:
                changes.extend(field_changes(previous[key], updated[key], field))
        return changes
    return [{'field': pointer, 'change': 'changed', 'before': previous, 'after': updated}]


def compare_contracts(previous, updated):
    before, before_uncertain = operations(previous)
    after, after_uncertain = operations(updated)
    report = {'status': 'declarations_unchanged', 'compatibility': 'not_assessed',
              'added': [], 'removed': [], 'changed': [], 'uncertain': []}
    uncertain_keys = before_uncertain.keys() | after_uncertain.keys()
    uncertain_paths = {path for path, method in uncertain_keys if method == '*'}
    for path, method in sorted(uncertain_keys):
        report['uncertain'].append({'operation': f'{method.upper()} {path}',
                                    'before': before_uncertain.get((path, method)),
                                    'after': after_uncertain.get((path, method))})
    for key in sorted(before.keys() | after.keys()):
        path, method = key
        if key in uncertain_keys or path in uncertain_paths:
            continue
        operation = f'{method.upper()} {path}'
        if key not in before:
            report['added'].append({'operation': operation, 'declaration_hash': digest(after[key])})
        elif key not in after:
            report['removed'].append({'operation': operation, 'declaration_hash': digest(before[key])})
        elif before[key] != after[key]:
            report['changed'].append({'operation': operation, 'before_hash': digest(before[key]),
                                      'after_hash': digest(after[key]),
                                      'changes': field_changes(before[key], after[key])})
    if any(report[key] for key in ('added', 'removed', 'changed')):
        report['status'] = 'review_required'
    elif report['uncertain']:
        report['status'] = 'uncertain'
    # JSON Schema dialect/version changes cannot be proved equivalent by this
    # declaration normalizer, even when operation signatures happen to match.
    for key in ('openapi', 'jsonSchemaDialect'):
        if previous.get(key) != updated.get(key):
            report['uncertain'].append({'scope': key, 'reason': 'declaration_dialect_changed',
                                        'before': previous.get(key), 'after': updated.get(key)})
            if report['status'] == 'declarations_unchanged':
                report['status'] = 'uncertain'
    return report
