"""Prepare complete, evidence-bounded prose changes from published contracts.

No API execution, publication, or schema mutation. Existing substantive prose is
retained. New detail is copied from declared request/response fields; generic
schemas never become invented output fields or account requirements.
"""
import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

from audit_tool_prose import METHODS, SKIP, PRICE
from tool_prose_editorial import editorial_text, english_prose


def resolve(value, document, seen=()):
    if not isinstance(value, dict):
        return {}
    reference = value.get('$ref')
    if not reference:
        return value
    if not reference.startswith('#/') or reference in seen:
        return {}
    target = document
    for part in reference[2:].split('/'):
        if not isinstance(target, dict):
            return {}
        target = target.get(part.replace('~1', '/').replace('~0', '~'))
    return {**resolve(target, document, (*seen, reference)), **{k: v for k, v in value.items() if k != '$ref'}}


def clean(value):
    # Export artifacts must not make invisible-only text look substantive.
    text = re.sub(r'[\u200b-\u200d\ufeff]', '', PRICE.sub('', value or '')).strip()
    return '' if text == '默认价格配置' else text


def retain_runtime_free_statement(description, runtime_operation):
    """Do not replace an explicit Runtime Free statement with projection boilerplate.

    Only reverse this exact known editorial substitution; this does not infer
    pricing or reconcile independently different supplier descriptions.
    """
    original = clean(runtime_operation.get('description'))
    if original and re.sub(r'\bFree\b', 'See the published pricing', original) == description:
        return original
    return description


def title(operation):
    old = clean(operation.get('summary'))
    description = clean(operation.get('description'))
    # Only machine tokens are normalized; readable titles and parameter names
    # inside backticks are left alone.
    if '_' not in old or '`' in old:
        return old
    purpose = re.search(r'###\s*Purpose\s*:\s*\n\s*-\s*([^\n]+)', description)
    if purpose:
        lead = description.splitlines()[0].strip().rstrip('.').replace('_', ' ')
        text = purpose.group(1).strip().rstrip('.')
        if len(lead) <= 65 and len(text) <= 140:
            return f'{lead}: {text}'
    words = re.sub(r'[_/]+', ' ', old)
    words = re.sub(r'\s+', ' ', words).strip()
    words = re.sub(r'\b(api|faq|cve|uid|url|id)\b', lambda m: m.group(0).upper(), words, flags=re.I)
    return words[:1].upper() + words[1:]


def field_text(name, schema, description=''):
    text = f'`{name}`'
    note = clean(description or schema.get('description'))
    # Avoid reproducing lengthy supplier tutorials/examples in the search lead.
    if note and len(note) <= 240 and '\n' not in note:
        text += ': ' + note.rstrip('.')
    elif schema.get('type'):
        text += ' (' + str(schema['type']) + ')'
    enum = schema.get('enum')
    if isinstance(enum, list) and 0 < len(enum) <= 8:
        text += '; allowed values: ' + ', '.join('`' + json.dumps(v, ensure_ascii=False) + '`' for v in enum)
    for key, label in [('maxLength', 'maximum length'), ('minLength', 'minimum length'),
                       ('minimum', 'minimum'), ('maximum', 'maximum')]:
        if key in schema:
            text += f'; {label}: {schema[key]}'
    return text.rstrip('.') + '.'


def summary_only(description, *summaries):
    def normalized(text):
        return re.sub(r'\s+', ' ', clean(text)).strip().rstrip('.。').casefold()
    value = normalized(description)
    if not value or value in {'n/a', 'tbd', 'todo', 'no description', 'no description available'}:
        return True
    return any(normalized(summary) == value or
               any(normalized(summary).endswith(separator + value) for separator in (' - ', ': ', ' / '))
               for summary in summaries)


def unconditional_required(schema, document, depth=0):
    if depth > 5:
        return set()
    schema = resolve(schema, document)
    names = set(schema.get('required', []))
    for branch in schema.get('allOf', []):
        names |= unconditional_required(branch, document, depth + 1)
    return names


def body_fields(schema, document, location, depth=0, inherited_required=()):
    """Read declarations without flattening alternative branches into one contract."""
    if depth > 5:
        return []
    schema = resolve(schema, document)
    required = set(inherited_required) | unconditional_required(schema, document)
    fields = [(name in required, location, field_text(name, resolve(field, document)))
              for name, field in schema.get('properties', {}).items()]
    if schema.get('type') == 'array' or 'items' in schema:
        fields += body_fields(schema.get('items', {}), document, location + ' array item', depth + 1)
    for branch in schema.get('allOf', []):
        fields += body_fields(branch, document, location, depth + 1, required)
    for keyword in ('oneOf', 'anyOf'):
        branches = schema.get(keyword, [])
        for index, branch in enumerate(branches):
            conditional = f'{location}, {keyword} variant {index + 1} of {len(branches)} when selected'
            fields += body_fields(branch, document, conditional, depth + 1, required)
    return list(dict.fromkeys(fields))


def response_fields(schema, document, prefix='', depth=0):
    if depth > 5:
        return []
    schema = resolve(schema, document)
    if schema.get('type') == 'array' or 'items' in schema:
        return response_fields(schema.get('items', {}), document, prefix + '[]', depth + 1)
    result = []
    for name, field in schema.get('properties', {}).items():
        path = (prefix + '.' if prefix else '') + name
        if name in {'data', 'result', 'results'}:
            result += response_fields(field, document, path, depth + 1)
        elif name not in {'code', 'message', 'msg', 'status', 'success', 'request_id', 'error'}:
            result.append(path)
    for keyword in ('allOf', 'oneOf', 'anyOf'):
        for branch in schema.get(keyword, []):
            result += response_fields(branch, document, prefix, depth + 1)
    return list(dict.fromkeys(result))


def details(operation, document, path_item):
    required, optional = [], []
    parameters = {}
    for raw in path_item.get('parameters', []) + operation.get('parameters', []):
        parameter = resolve(raw, document)
        if parameter.get('name'):
            parameters[(parameter.get('in'), parameter['name'])] = parameter
    for parameter in parameters.values():
        if parameter.get('in') == 'header' and not parameter.get('required'):
            continue
        text = field_text(parameter['name'], resolve(parameter.get('schema', {}), document), parameter.get('description', ''))
        (required if parameter.get('required') else optional).append((parameter.get('in', 'parameter'), text))
    body = resolve(operation.get('requestBody', {}), document)
    for media, content in body.get('content', {}).items():
        if media not in {'application/json', 'application/x-www-form-urlencoded', 'multipart/form-data'}:
            continue
        location = 'JSON body' if media == 'application/json' else media + ' body'
        if not body.get('required'):
            location += ', when supplied'
        for is_required, field_location, text in body_fields(content.get('schema', {}), document, location):
            (required if is_required else optional).append((field_location, text))
    sections = []
    for label, fields, limit in [('Required inputs', required, len(required)), ('Key optional inputs', optional, 5)]:
        if fields:
            sections.append(label + ':\n' + '\n'.join('- ' + location + ': ' + text for location, text in fields[:limit]))
    outputs = []
    for status, raw in operation.get('responses', {}).items():
        if not str(status).startswith('2'):
            continue
        response = resolve(raw, document)
        for content in response.get('content', {}).values():
            outputs += response_fields(content.get('schema', {}), document)
        if outputs:
            break
    if outputs:
        sections.append('Declared response fields include ' + ', '.join('`' + n + '`' for n in list(dict.fromkeys(outputs))[:12] if n) + '.')
    return '\n\n'.join(sections), bool(required or optional or outputs)


def prepare_text(operation, document, path_item):
    summary = title(operation)
    provider_title = document.get('info', {}).get('title', '').strip()
    # This document ID describes authorization state, not the public brand.
    provider_title = {'kalshi-unauthorized': 'Kalshi'}.get(provider_title, provider_title)
    if provider_title and ':' not in summary and len(summary.split()) <= 3 and provider_title.casefold() not in summary.casefold():
        summary = provider_title + ': ' + summary
    before = clean(operation.get('description'))
    guidance, has_details = details(operation, document, path_item)
    if summary_only(before, summary, operation.get('summary', '')):
        lead = summary.rstrip('. ') + '.'
        if provider_title and provider_title.casefold() not in lead.casefold():
            lead = provider_title + ': ' + lead
        description = lead + ('\n\n' + guidance if guidance else '')
        disposition = 'expanded_from_declared_contract' if has_details else 'bounded_to_declared_purpose'
    elif guidance and len(before) < 240 and any(
            name.casefold() not in before.casefold()
            for name in re.findall(r'`([^`]+)`', guidance.split('Key optional inputs:')[0].split('Declared response fields')[0])):
        description = before + '\n\n' + guidance
        disposition = 'supplemented_existing_prose'
    elif len(before) > 4000:
        # Retain the complete original; front-load the declared purpose and
        # required inputs for bounded search text, never truncate caveats.
        description = summary.rstrip('. ') + '.'
        if guidance:
            description += '\n\n' + guidance
        description += '\n\n' + before
        disposition = 'front_loaded_existing_detail'
    else:
        description = before
        disposition = 'preserved_existing_prose'
    return summary, description, disposition


def enrich_purpose(operation, path, method, description, disposition, evidence):
    """Use an exact, captured source binding only for otherwise purpose-only text.

    These excerpts describe capability, not a new public request/response schema.
    Never overwrite independently maintained caveats or infer wire parameters.
    """
    key = (path, method.upper(), operation.get('operationId'))
    source = evidence.get(key)
    if (disposition != 'bounded_to_declared_purpose' or not source or
            operation.get('summary', '') != source['before_summary']):
        return description, disposition, None
    purpose = source['description'].strip()
    if not purpose or purpose.startswith('$'):
        raise ValueError('Unresolved source prose: ' + str(key))
    return description + '\n\n' + purpose, 'expanded_from_bound_source', source


def prepare(root, runtime_dir, services_root, output, docs_ref=None):
    evidence_path = root / 'scripts/data/tool-prose-purpose-evidence.json'
    source_rows = json.loads(evidence_path.read_text()) if evidence_path.exists() else []
    purpose_evidence = {(r['path'], r['method'], r['operation_id']): r for r in source_rows}
    if len(purpose_evidence) != len(source_rows):
        raise ValueError('Duplicate source prose identity')
    runtime = {}
    for file in sorted(runtime_dir.glob('*.json')):
        if file.name == 'receipt.json':
            continue
        raw = file.read_bytes(); document = json.loads(raw)
        for path, item in document.get('paths', {}).items():
            for method, operation in item.items():
                if method not in METHODS | {'x-aisa-any'}:
                    continue
                key = (path, method, operation.get('operationId'))
                if key in runtime:
                    raise ValueError('Duplicate Runtime public identity: ' + str(key))
                runtime[key] = (operation, document, hashlib.sha256(raw).hexdigest())
    # Keep the already individually drafted entries as explicit prose choices,
    # while rebinding their old values and structure to this full snapshot.
    previous = json.loads((services_root / 'packages/apicontract/reviewed_prose.json').read_text())
    curated = {r['operation_id']: r for r in previous if r.get('evidence', {}).get('manual_draft', True)}
    entries, coverage, changes = [], [], []
    used_runtime = set()
    entries_by_key = {}
    for file in sorted((root / 'openapi').glob('*.json')):
        if file.stem in SKIP:
            continue
        raw = (subprocess.check_output(['git', 'show', docs_ref + ':' + str(file.relative_to(root))], cwd=root)
               if docs_ref else file.read_bytes())
        document = json.loads(raw)
        for path, item in document.get('paths', {}).items():
            for method, operation in item.items():
                if method not in METHODS:
                    continue
                operation_id = operation.get('operationId')
                summary, description, disposition = prepare_text(operation, document, item)
                if not operation.get('x-aisa-runtime-operation') and clean(operation.get('description')):
                    # These retained/manual operations already have substantive prose.
                    # Keep their independently maintained text instead of cosmetic renaming.
                    summary = operation.get('summary', '')
                    description = clean(operation.get('description'))
                    disposition = 'preserved_static_prose'
                if operation_id in curated:
                    summary = curated[operation_id]['summary']; description = curated[operation_id]['description']
                    disposition = 'individual_draft'
                description, disposition, purpose_source = enrich_purpose(
                    operation, path, method, description, disposition, purpose_evidence)
                key = (path, method, operation_id)
                fact = runtime.get(key)
                binding = operation.get('x-aisa-runtime-operation', {})
                if not fact and binding:
                    bound_method = binding.get('method', '').lower()
                    if bound_method == 'any':
                        bound_method = 'x-aisa-any'
                    key = (binding.get('path'), bound_method, binding.get('operation_id'))
                    fact = runtime.get(key)
                if fact:
                    used_runtime.add(key)
                    description = retain_runtime_free_statement(description, fact[0])
                summary = english_prose(summary)
                description = editorial_text(description, native=path.startswith(('/apis/v1/social/', '/apis/v1/ads/')), notice=True)
                before = {'summary': operation.get('summary', ''), 'description': clean(operation.get('description'))}
                after = {'summary': summary, 'description': description}
                changed = before != after
                row = {'provider': file.stem, 'operation_id': operation_id, 'method': method.upper(), 'path': path,
                       'disposition': disposition, 'published_text_changed': changed,
                       'source_file': str(file.relative_to(root)), 'source_sha256': hashlib.sha256(raw).hexdigest()}
                # Existing useful published prose is preserved, even if supplied
                # by a mirror; only changed text needs a new Runtime entry.
                if changed and fact:
                    current, runtime_document, runtime_hash = fact
                    entry = {'operation_id': key[2], 'method': key[1].upper(), 'path': key[0],
                             'before_summary': current.get('summary', ''),
                             'before_description': current.get('description', ''),
                             'summary': summary, 'description': description,
                             'contract': {k: copy.deepcopy(current[k]) for k in ('parameters', 'requestBody', 'responses') if k in current},
                             'components': runtime_document.get('components', {}).get('schemas', {}),
                             'evidence': {'file': str(file.relative_to(root)), 'sha256': row['source_sha256'],
                                          'runtime_document_sha256': runtime_hash,
                                          'public_method': method.upper(),
                                          'manual_draft': disposition == 'individual_draft'}}
                    if purpose_source:
                        entry['evidence']['purpose_source'] = purpose_source
                    if key in entries_by_key:
                        previous_entry = entries_by_key[key]
                        if (entry['summary'], entry['description']) != (previous_entry['summary'], previous_entry['description']):
                            if entry['summary'] != previous_entry['summary']:
                                raise ValueError('Shared Runtime identity has different proposed titles: ' + str(key))
                            # Keep both explicitly declared method contracts. A shared ANY
                            # operation must not present GET inputs as the POST contract.
                            first_method = previous_entry['evidence']['public_method']
                            if not previous_entry.get('method_sections'):
                                previous_entry['description'] = first_method + ' request:\n' + previous_entry['description']
                                previous_entry['method_sections'] = [first_method]
                            if method.upper() not in previous_entry['method_sections']:
                                previous_entry['description'] += '\n\n' + method.upper() + ' request:\n' + entry['description']
                                previous_entry['method_sections'].append(method.upper())
                            row['delivery'] = 'AIsaServices generated contract'
                        else:
                            row['delivery'] = 'AIsaServices generated contract'
                    else:
                        entries.append(entry); entries_by_key[key] = entry
                        row['delivery'] = 'AIsaServices generated contract'
                elif changed:
                    row['delivery'] = 'Docs static contract' if file.stem == 'gemini-openapi' else 'static_source_required'
                else:
                    row['delivery'] = 'preserve'
                if changed:
                    changes.append({**row, 'before': before, 'after': after})
                coverage.append(row)
    # Include Runtime tools added since the checked-in Docs publication.
    published_identities = {(r['path'], r['method'].lower(), r['operation_id']) for r in coverage}
    for (path, method, operation_id), (operation, document, runtime_hash) in sorted(runtime.items()):
        if (path, method, operation_id) in used_runtime:
            continue
        summary, description, disposition = prepare_text(operation, document, document['paths'][path])
        summary = english_prose(summary)
        description = editorial_text(description, native=path.startswith(('/apis/v1/social/', '/apis/v1/ads/')), notice=True)
        before = {'summary': operation.get('summary', ''), 'description': clean(operation.get('description'))}
        after = {'summary': summary, 'description': description}
        changed = before != after
        row = {'provider': document.get('info', {}).get('x-aisa-provider', 'runtime-only'),
               'operation_id': operation_id, 'method': method.upper(), 'path': path,
               'disposition': disposition, 'published_text_changed': changed,
               'source_file': 'Runtime public facts', 'source_sha256': runtime_hash,
               'delivery': 'AIsaServices generated contract' if changed else 'preserve'}
        if changed:
            entries.append({'operation_id': operation_id, 'method': method.upper(), 'path': path,
                'before_summary': operation.get('summary', ''), 'before_description': operation.get('description', ''),
                'summary': summary, 'description': description,
                'contract': {k: copy.deepcopy(operation[k]) for k in ('parameters', 'requestBody', 'responses') if k in operation},
                'components': document.get('components', {}).get('schemas', {}),
                'evidence': {'runtime_document_sha256': runtime_hash, 'manual_draft': False}})
            changes.append({**row, 'before': before, 'after': after})
        coverage.append(row)
    for entry in entries:
        if entry.pop('method_sections', None):
            for change in changes:
                if change['path'] == entry['path']:
                    change['after']['description'] = entry['description']
    if any(not entry['summary'].strip() or not entry['description'].strip() for entry in entries):
        raise ValueError('Empty proposed prose')
    output.mkdir(parents=True, exist_ok=True)
    for filename, value in [('runtime-prose-input.json', entries), ('coverage.json', coverage), ('changes.json', changes)]:
        (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    summary = {'tools': len(coverage), 'providers': len({r['provider'] for r in coverage}),
               'published_text_changed': len(changes), 'runtime_entries': len(entries),
               'delivery': dict(collections.Counter(r['delivery'] for r in coverage)),
               'dispositions': dict(collections.Counter(r['disposition'] for r in coverage))}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--docs-ref', help='Immutable Docs revision used for reproducible source prose')
    parser.add_argument('--services-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.runtime_dir, args.services_root, args.output, args.docs_ref), indent=2))
