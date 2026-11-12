"""Prepare request-only public mirrors from pinned Connect metadata and routing.

Offline review candidate only. The owning HTTP entry wraps the caller's root
argument object internally; Composio owns that public argument schema. This importer creates no source-review
receipt, response schema, runtime configuration, or publication approval.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
from jsonschema import Draft202012Validator

from compose_openapi import digest
from internal_publication_snapshot import load_snapshot
from source_governance import initial_policy

SERVICES_REVISION = '3c55acbef31c1aae0648aaa48b0bc92184594500'
ROUTES_PATH = 'packages/integrationcatalog/vendors.json'
ENVELOPE_PATH = 'services/api-service/internal/httpapi/integration_gateway_body.go'
RESPONSE_PATH = 'packages/composioconnect/workbench.go'
SOURCE_URL = 'https://connect.composio.dev/mcp'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def schema_components(schema, name):
    """Hoist local schema targets to component roots without flattening recursion."""
    def resolve(reference):
        require(isinstance(reference, str) and (reference == '#' or reference.startswith('#/')),
                'Only root-local schema references are supported')
        target = schema
        for part in reference[2:].split('/') if reference.startswith('#/') else []:
            part = part.replace('~1', '/').replace('~0', '~')
            if isinstance(target, list):
                require(part.isdigit() and int(part) < len(target), 'Unresolved schema reference')
                target = target[int(part)]
            else:
                require(isinstance(target, dict) and part in target, 'Unresolved schema reference')
                target = target[part]
        return target

    def preserve_inline_discriminator(value, discriminator):
        # OAS 3.1.1 section 4.8.25: discriminator MUST NOT change validation.
        # Some captures inline every oneOf branch but retain obsolete $defs
        # hints. Preserve those hints as source annotation, never fabricate
        # definitions or discard the actual oneOf/const/required constraints.
        branches = value.get('oneOf')
        field = discriminator.get('propertyName')
        mapping = discriminator.get('mapping')
        require(isinstance(branches, list) and branches and isinstance(field, str)
                and set(discriminator) == {'propertyName', 'mapping'},
                'Unresolved discriminator requires complete inline oneOf')
        require('x-aisa-source-discriminator' not in value, 'Source annotation collision')
        seen = set()
        for branch in branches:
            require(isinstance(branch, dict) and branch.get('type') == 'object'
                    and field in branch.get('required', []), 'Inline discriminator field must be required')
            literal = branch.get('properties', {}).get(field, {}).get('const')
            require(isinstance(literal, str) and literal not in seen and literal in mapping,
                    'Inline discriminator alternatives must have distinct matching const values')
            require(mapping[literal] == '#/$defs/' + branch.get('title', ''),
                    'Unresolved discriminator does not identify the inline titled branch')
            seen.add(literal)
        require(seen == set(mapping), 'Incomplete inline discriminator alternatives')
        value['x-aisa-source-discriminator'] = value.pop('discriminator')

    pending = [('#', name)]
    names = {'#': name}
    components = {}
    while pending:
        reference, target_name = pending.pop(0)
        target = copy.deepcopy(resolve(reference))
        def register(ref):
            require(isinstance(ref, str) and (ref == '#' or ref.startswith('#/')),
                    'Only root-local schema references are supported')
            if ref not in names:
                generated = name + '__' + hashlib.sha256(ref.encode()).hexdigest()[:16]
                require(generated not in names.values(), 'Schema component name collision')
                names[ref] = generated
                pending.append((ref, generated))
            return '#/components/schemas/' + names[ref]
        def visit(value):
            if isinstance(value, dict):
                require(not any(k in value for k in ('$id', '$anchor', '$dynamicAnchor', '$dynamicRef', '$recursiveRef')),
                        'Schema identifier or dynamic reference needs independent conversion')
                if '$ref' in value:
                    value['$ref'] = register(value['$ref'])
                discriminator = value.get('discriminator')
                if isinstance(discriminator, dict) and 'mapping' in discriminator:
                    require(isinstance(discriminator['mapping'], dict), 'Invalid discriminator mapping')
                    try:
                        for ref in discriminator['mapping'].values():
                            resolve(ref)
                    except ValueError:
                        preserve_inline_discriminator(value, discriminator)
                    else:
                        discriminator['mapping'] = {key: register(ref) for key, ref in discriminator['mapping'].items()}
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(target)
        components[target_name] = target
    return components


def schema_digest(schema):
    """Match the deployed Go JSON hash for the captured input representation.

    Go uses sorted keys, UTF-8 and HTML escaping. Expected production pins are
    still mandatory; any numeric-spelling difference fails closed. The complete
    retained capture was also independently checked using Go UseNumber.
    """
    raw = json.dumps(schema, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    for character, escaped in [('<', r'\u003c'), ('>', r'\u003e'), ('&', r'\u0026'),
                               ('\u2028', r'\u2028'), ('\u2029', r'\u2029')]:
        raw = raw.replace(character, escaped)
    return hashlib.sha256(raw.encode()).hexdigest()


def runtime_route_index(facts):
    routes = {}
    for provider, document in facts.items():
        for route, item in document.get('paths', {}).items():
            for method, operation in item.items():
                if method not in {'get','post','put','patch','delete','head','options'}:
                    continue
                key = (route, method)
                require(key not in routes, 'Ambiguous Runtime public route')
                routes[key] = (provider, operation)
    return routes


def prepare(vendors, metadata, facts, *, metadata_sha256, routes_sha256, fetched_at, bindings, selected_paths=None, include_responses=False):
    require(isinstance(vendors, dict) and isinstance(vendors.get('vendors'), list), 'Exact Services vendor routing required')
    require(isinstance(metadata, dict), 'Connect metadata index required')
    require(re.fullmatch('[0-9a-f]{64}', metadata_sha256) and re.fullmatch('[0-9a-f]{64}', routes_sha256), 'Pinned original source hashes required')
    paths, components, omitted, identities = {}, {}, [], set()
    runtime = runtime_route_index(facts)
    response_count, response_omitted = 0, []
    for vendor in vendors['vendors']:
        if vendor.get('provider_key') != 'composio':
            continue
        for slug, route in sorted(vendor.get('routes', {}).items()):
            if selected_paths is not None and route not in selected_paths:
                continue
            require(slug in vendor.get('operations', []), 'Route is outside vendor operation inventory')
            group, operation = runtime.get((route, 'post'), (vendor['group'], None))
            if not operation or operation.get('x-aisa-status') != 'enabled':
                continue
            identity = operation.get('operationId')
            require(isinstance(identity, str) and identity and route not in paths and identity not in identities,
                    'Duplicate or missing Runtime public identity')
            identities.add(identity)
            source = metadata.get(slug)
            if not source:
                omitted.append({'provider': group, 'path': route, 'tool_slug': slug, 'reason': 'metadata_missing'})
                continue
            require(source.get('tool_slug') == slug, 'Metadata tool identity differs')
            schema = source.get('input_schema')
            if not isinstance(schema, dict) or schema.get('type') != 'object' or not isinstance(schema.get('properties'), dict):
                omitted.append({'provider': group, 'path': route, 'tool_slug': slug, 'reason': 'complete_object_input_schema_missing'})
                continue
            applied = bindings.get(slug)
            if not applied or applied.get('tool_slug') != slug:
                omitted.append({'provider': group, 'path': route, 'tool_slug': slug, 'reason': 'applied_schema_pin_missing'})
                continue
            if schema_digest(schema) != applied.get('input_schema_sha256'):
                omitted.append({'provider': group, 'path': route, 'tool_slug': slug, 'reason': 'applied_input_schema_pin_differs'})
                continue
            name = 'connect_' + slug
            try:
                converted = schema_components(schema, name)
            except ValueError as error:
                omitted.append({'provider': group, 'path': route, 'tool_slug': slug,
                                'reason': 'schema_conversion_requires_review', 'detail': str(error)})
                continue
            components.update(converted)
            paths[route] = {'post': {
                'operationId': identity,
                'summary': operation.get('summary', slug),
                # Empty HTTP input is wrapped as arguments={}; it is usable
                # only if the provider's actual input schema accepts {}.
                'requestBody': {'required': not Draft202012Validator(schema).is_valid({}), 'content': {'application/json': {
                    'schema': {'$ref': '#/components/schemas/' + name}}}},
            }}
            # Preserve captured operation prose independently of input/output schemas.
            # Runtime summary remains authoritative; do not derive capabilities from a slug.
            description = source.get('description')
            require(description is None or isinstance(description, str),
                    'Captured tool description must be text')
            if description and description.strip():
                paths[route]['post']['description'] = description
            if include_responses:
                try:
                    output = source.get('output_schema')
                    require(isinstance(output,dict) and schema_digest(output) == applied.get('output_schema_sha256'),
                            'applied output schema pin differs or is absent')
                    require(output.get('type')=='object' and not set(output)-{
                        'type','properties','required','$defs','definitions','additionalProperties','title','description'},
                        'output envelope has unreviewed cross-field constraints')
                    data = output.get('properties',{}).get('data')
                    require(isinstance(data,dict) and any(k in data for k in ('type','$ref','oneOf','anyOf','allOf')),
                            'tool data response schema is absent or undeclared')
                    output_name = name + '__output'
                    output_components = schema_components(output, output_name)
                    public_name = output_name + '__public_data'
                    output_components[public_name] = output_components[output_name]['properties']['data']
                    components.update(output_components)
                    paths[route]['post']['responses'] = {'200':{
                        'description':'Tool result data', 'content':{'application/json':{
                            'schema':{'$ref':'#/components/schemas/'+public_name}}}}}
                    response_count += 1
                except ValueError as error:
                    response_omitted.append({'provider':group,'path':route,'tool_slug':slug,'reason':str(error)})
    require(paths, 'No enabled exact public routes have complete captured metadata')
    result = {'openapi': '3.1.0', 'info': {'title': 'Composio Connect public request definitions',
              'version': SERVICES_REVISION}, 'paths': paths, 'components': {'schemas': components}}
    base = 'https://raw.githubusercontent.com/AIsa-team/AIsaServices/' + SERVICES_REVISION + '/'
    source = {'kind': 'manual', 'url': SOURCE_URL, 'fetched_at': fetched_at,
              'content_hash': digest(result), 'converter': 'scripts/prepare_composio_public_reference.py@2',
              'path_space': 'public', 'refresh_policy': 'pinned',
              'refresh_reason': 'Review captured provider argument schemas and the pinned owning HTTP request adapter together before replacement.',
              'source_git_revision': SERVICES_REVISION,
              'raw_content_hash': 'sha256:' + metadata_sha256,
              'routes_content_hash': 'sha256:' + routes_sha256,
              'source_pages': [{'url': SOURCE_URL, 'scope': 'Captured input schemas and tool descriptions; no current-source review asserted'},
                               {'url': base + ROUTES_PATH, 'scope': 'Exact provider tool slug to public route mapping'},
                               {'url': base + ENVELOPE_PATH, 'scope': 'wrapGatewayBody: caller root arguments are wrapped internally; the internal envelope is not a public input'}],
              'qualification': 'Historical metadata conversion requiring independent source review. No live acquisition, successful response schema, or formal publication approval is asserted.'}
    result['info']['x-aisa-source'] = initial_policy(source)
    if include_responses:
        result['info']['x-aisa-source']['source_pages'].append({'url':base+RESPONSE_PATH,
            'scope':'PublicResponse returns only the one completed tool response data as HTTP 200'})
        result['info']['x-aisa-source']['qualification'] = 'Historical pinned metadata conversion requiring independent source review. Public responses project the declared data property through the fixed HTTP adapter. No live acquisition or formal approval asserted.'
    return result, {'scope': 'request_source_review_candidate_only', 'formal_publication': False,
                    'services_revision': SERVICES_REVISION, 'request_operations': len(paths),
                    'response_operations_added': response_count, 'response_omitted':response_omitted,
                    'source_review_receipts_created': 0, 'omitted': omitted}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--services-repository', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--metadata-sha256', required=True)
    parser.add_argument('--fetched-at', required=True, help='Original acquisition time, or explicit unknown for a historical capture; never substitute local import time')
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--snapshot-proof', type=Path, required=True)
    parser.add_argument('--production-schema-pins', type=Path, required=True, help='Credential-free pin audit from the verified applied production plan')
    parser.add_argument('--production-schema-pins-sha256', required=True)
    parser.add_argument('--pending-pages-receipt', type=Path, required=True, help='Same-snapshot pending inventory; limits output to missing definitions')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--include-responses', action='store_true', help='Project independently pinned output.data through the reviewed PublicResponse adapter')
    args = parser.parse_args()
    require(not args.output.exists() and not args.report.exists(), 'Output and report must be new files')
    raw = args.metadata.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == args.metadata_sha256, 'Metadata differs from caller hash')
    pins = json.loads(args.snapshot_proof.read_text()); pins.pop('files', None)
    require(pins['compiler_revision'] == SERVICES_REVISION, 'Snapshot does not use the reviewed envelope implementation')
    facts, binding = load_snapshot(args.snapshot, **pins)
    pending = json.loads(args.pending_pages_receipt.read_text())
    require(all(pending.get('source', {}).get(k) == v for k, v in pins.items()), 'Pending inventory differs from verified snapshot')
    selected_paths = {row['path'] for rows in pending['pending']['providers'].values() for row in rows
                      if row.get('reason') == 'upstream operation missing'}
    require(selected_paths, 'No missing request definitions selected')
    routes_raw = subprocess.check_output(['git', 'show', SERVICES_REVISION + ':' + ROUTES_PATH], cwd=args.services_repository)
    # Verify that the independently reviewed owning source exists at the same
    # revision. Dynamic reinterpretation of newer envelope code is forbidden.
    subprocess.check_output(['git', 'cat-file', '-e', SERVICES_REVISION + ':' + ENVELOPE_PATH], cwd=args.services_repository)
    pins_raw = args.production_schema_pins.read_bytes()
    require(hashlib.sha256(pins_raw).hexdigest() == args.production_schema_pins_sha256, 'Production pin evidence differs from caller hash')
    pin_evidence = json.loads(pins_raw)
    bindings = {row['tool_slug']: row for row in pin_evidence['operations']}
    require(len(bindings) == len(pin_evidence['operations']), 'Ambiguous applied tool pin')
    result, report = prepare(json.loads(routes_raw), json.loads(raw),
        {Path(name).stem: json.loads(content) for name, content in facts.items()},
        metadata_sha256=args.metadata_sha256, routes_sha256=hashlib.sha256(routes_raw).hexdigest(), fetched_at=args.fetched_at, bindings=bindings, selected_paths=selected_paths, include_responses=args.include_responses)
    report['snapshot'] = binding
    report['applied_schema_pin_evidence_sha256'] = args.production_schema_pins_sha256
    report['production_apply_run_id'] = pin_evidence['production_apply_run_id']
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: report[k] for k in ('request_operations', 'response_operations_added', 'formal_publication')}))


if __name__ == '__main__':
    main()
