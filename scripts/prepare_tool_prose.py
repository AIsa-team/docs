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


def details(operation, document, path_item):
    required, optional = [], []
    for raw in path_item.get('parameters', []) + operation.get('parameters', []):
        parameter = resolve(raw, document)
        if not parameter.get('name'):
            continue
        if parameter.get('in') == 'header' and not parameter.get('required'):
            continue
        text = field_text(parameter['name'], resolve(parameter.get('schema', {}), document), parameter.get('description', ''))
        (required if parameter.get('required') else optional).append((parameter.get('in', 'parameter'), text))
    body = resolve(operation.get('requestBody', {}), document)
    for media, content in body.get('content', {}).items():
        if media != 'application/json':
            continue
        schema = resolve(content.get('schema', {}), document)
        for name, field in schema.get('properties', {}).items():
            # A required property in an optional body is conditional, not a
            # globally required input.
            is_required = name in schema.get('required', [])
            location = 'JSON body' if body.get('required') else 'JSON body, when supplied'
            (required if is_required else optional).append((location, field_text(name, resolve(field, document))))
        break
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
            schema = resolve(content.get('schema', {}), document)
            if schema.get('type') == 'array':
                schema = resolve(schema.get('items', {}), document)
            # Envelope-only properties do not establish domain output content.
            properties = schema.get('properties', {})
            for name in properties:
                if name not in {'code', 'message', 'msg', 'data', 'status', 'success', 'request_id', 'error'}:
                    outputs.append(name)
        if outputs:
            break
    if outputs:
        sections.append('Declared response fields include ' + ', '.join('`' + n + '`' for n in list(dict.fromkeys(outputs))[:12] if n) + '.')
    return '\n\n'.join(sections), bool(required or optional or outputs)


def prepare_text(operation, document, path_item):
    summary = title(operation)
    provider_title = document.get('info', {}).get('title', '').strip()
    if provider_title and ':' not in summary and len(summary.split()) <= 3 and provider_title.casefold() not in summary.casefold():
        summary = provider_title + ': ' + summary
    before = clean(operation.get('description'))
    guidance, has_details = details(operation, document, path_item)
    if not before or before.strip('. ').casefold() == summary.strip('. ').casefold():
        lead = summary.rstrip('. ') + '.'
        if provider_title and provider_title.casefold() not in lead.casefold():
            lead = provider_title + ': ' + lead
        description = lead + ('\n\n' + guidance if guidance else '')
        disposition = 'expanded_from_declared_contract' if has_details else 'bounded_to_declared_purpose'
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


def prepare(root, runtime_dir, services_root, output, docs_ref=None):
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
