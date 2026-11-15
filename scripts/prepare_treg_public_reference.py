"""Convert Treg declarations at one captured revision at the actual /call HTTP boundary.

This creates request-source review candidates only. Unsupported or incomplete
DSL stays omitted; no provider calls, response guesses, or review receipts.

Spec #1285 R1: declarations are no longer pinned. The source follows the
upstream main branch through ``refresh_document`` (registered as the
``treg-public`` importer) every 12 hours, and changes reach main only through
the reviewed upstream refresh PR. Upstream ``note`` text is internal guidance:
it is kept in the internal report and never copied into public descriptions.
Retained descriptions must pass the public vocabulary scan.
"""
import copy
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import yaml
from compose_openapi import digest
from source_governance import initial_policy, policy_revision
from capture_treg_declarations import raw_base
from prepare_composio_public_reference import SERVICES_REVISION, ROUTES_PATH, require, runtime_route_index
from internal_publication_snapshot import load_snapshot

# Stable authority URL: the reviewed policy (and its policy_revision) must not
# change with every upstream revision. The revision is source_git_revision.
TREG_CATALOG_URL = 'https://github.com/superdesigndev/treg/tree/main/src/treg/catalog'
REFRESH_INTERVAL_HOURS = 12
CONVERTER = 'scripts/prepare_treg_public_reference.py@2'


def field_schema(spec, notes=None):
    require(isinstance(spec, dict), 'parameter declaration must be an object')
    allowed = {'type', 'required', 'note', 'description', 'example', 'default', 'enum',
               'min', 'max', 'minimum', 'maximum', 'minItems', 'maxItems', 'minLength',
               'maxLength', 'format', 'items', 'properties', 'additionalProperties'}
    require(not set(spec) - allowed, 'unsupported parameter constraints: ' + ','.join(sorted(set(spec)-allowed)))
    kind = spec.get('type')
    require(isinstance(kind, str), 'explicit scalar or typed-array declaration required')
    result = {}
    if kind.startswith('array[') and kind.endswith(']'):
        item_type = kind[6:-1]
        require(item_type in {'string','integer','number','boolean'}, 'array object fields require an explicit item schema')
        result = {'type': 'array', 'items': {'type': item_type}}
        require('items' not in spec, 'ambiguous typed-array items')
    elif kind == 'array':
        require(isinstance(spec.get('items'), dict), 'array items are undeclared')
        result = {'type': 'array', 'items': field_schema(spec['items'], notes)}
    elif kind in {'string','integer','number','boolean','object'}:
        result = {'type': kind}
    else:
        raise ValueError('unsupported declared type: ' + kind)
    if kind == 'object':
        require('properties' in spec or spec.get('additionalProperties') is True,
                'object fields are undeclared; openness is not asserted')
        if 'properties' in spec:
            result.update(object_fields(spec['properties'], notes))
        if 'additionalProperties' in spec:
            require(isinstance(spec['additionalProperties'], bool), 'unsupported additionalProperties')
            result['additionalProperties'] = spec['additionalProperties']
    for key in ('default', 'minLength', 'maxLength', 'format'):
        if key in spec:
            require(key not in {'minLength','maxLength','format'} or kind == 'string', 'string constraint on non-string')
            result[key] = copy.deepcopy(spec[key])
    for old, new in (('min','minimum'),('max','maximum'),('minimum','minimum'),('maximum','maximum')):
        if old in spec:
            target = {'minimum':'minItems','maximum':'maxItems'}[new] if result['type']=='array' else new
            require(result['type'] in {'integer','number','array'}, 'ambiguous non-numeric min/max')
            require(target not in result or result[target] == spec[old], 'contradictory bounds')
            result[target] = spec[old]
    for key in ('minItems', 'maxItems'):
        if key in spec:
            require(result['type']=='array', 'array constraint on non-array')
            require(key not in result or result[key] == spec[key], 'contradictory array bounds')
            result[key] = spec[key]
    if 'enum' in spec:
        require(isinstance(spec['enum'], list) and spec['enum'], 'enum must be a nonempty list')
        # The Treg owning executor validates every array item against enum.
        target = result['items'] if result['type']=='array' else result
        target['enum'] = copy.deepcopy(spec['enum'])
    if spec.get('description'): result['description'] = str(spec['description'])
    if spec.get('note') and notes is not None: notes.append(str(spec['note']))
    if 'example' in spec: result['examples'] = [copy.deepcopy(spec['example'])]
    required = spec.get('required', False)
    require(isinstance(required, bool), 'nested required list needs independent conversion')
    return result


def object_fields(fields, notes=None):
    require(isinstance(fields, dict), 'body field map required')
    result = {'type':'object', 'properties':{}, 'required':[]}
    for name, spec in fields.items():
        result['properties'][name] = field_schema(spec, notes)
        if spec.get('required', False): result['required'].append(name)
    if not result['required']: result.pop('required')
    return result


def public_request(source, notes=None):
    # A field-level DSL is not the whole contract: the owning executor also
    # interprets operation-level admission/credential restrictions. Unknown
    # behavior is never silently flattened into a permissive request schema.
    metadata = {'id','platform','method','path','name','summary','docs_url','input','added',
                'capability','test_request','cost','example_response','verified','scope','domain',
                'tier','price','observed_time','miss','untestable','cache','expect','unverified',
                'host','skipped','status','status_note','kind','observed_from','not_found','note',
                # Billing, settlement and error-mapping rules of the owning executor
                # (gateway-internal). They do not change the public request surface.
                'bill','reserve','settle','error','provenance'}
    interpreted = {'body_allowlist','strict_query','platform_request','async','managed_resource',
                   'team_label','caller_email','platform_auth','resource_ownership','required_resource',
                   'strict_body','authorization_capability','authorization_paths','body_required_any'}
    require(not set(source)-metadata-interpreted,
            'unknown operation-level semantics: '+','.join(sorted(set(source)-metadata-interpreted)))
    for key in sorted(interpreted-{'body_allowlist'}):
        require(not source.get(key), 'operation-level constraint requires separate review: '+key)
    require(isinstance(source.get('body_allowlist',False), bool), 'invalid body_allowlist')
    provider = source.get('id','').split('.')[0]
    require(provider not in {'oceanio','octen','enrichlayer','openmart','tavily','sumble','leadocean','theirstack','apify'},
            'provider-specific admission requires separate review: '+provider)
    require(source.get('id') not in {'contactout.people.search.reveal','apollo.people.enrich'},
            'operation-specific admission requires separate review')
    require('price' not in source, 'v2 rate/admission rules require separate review')
    cost = source.get('cost') or {}
    require(not cost.get('quantity'), 'cost quantity is an admission constraint')
    require(not any(str(key).startswith('body.') for row in cost.get('table',[]) for key in row.get('when',{})),
            'cost table body selectors require separate review')
    inp = source.get('input')
    require(isinstance(inp, dict), 'explicit input declaration required')
    require(not set(inp)-{'body','bodyType','queryParams','pathParams','note'}, 'unsupported input location or encoding')
    require(inp.get('bodyType','json') == 'json', 'form or multipart needs separate transport review')
    operation = {'parameters': []}
    seen = set()
    placeholders = set(re.findall(r'\{(\w+)\}', source.get('path','')))
    require(placeholders <= set(inp.get('pathParams',{})), 'upstream path placeholder declaration missing')
    for location in ('pathParams','queryParams'):
        for name, spec in inp.get(location,{}).items():
            require(name not in seen, 'ambiguous path/query parameter overlap')
            seen.add(name)
            schema = field_schema(spec, notes)
            require(schema['type'] in {'string','integer','number','boolean'}, 'query array/object serialization needs explicit review')
            # /call/{operation-id} consumes its upstream placeholders from query.
            required = name in placeholders or spec.get('required', False)
            operation['parameters'].append({'name':name,'in':'query','required':required,'schema':schema})
    if not operation['parameters']: operation.pop('parameters')
    if 'body' in inp:
        body = inp['body']
        require(isinstance(body,dict) and all(isinstance(v,dict) for v in body.values()), 'whole-body declaration needs independent conversion')
        schema = object_fields(body, notes)
        if source.get('body_allowlist'):
            schema['additionalProperties'] = False
            for name in schema.get('required',[]):
                field = schema['properties'][name]
                if field['type'] == 'string':
                    field['minLength'] = max(1,field.get('minLength',0))
        operation['requestBody'] = {'required':bool(source.get('body_allowlist') or schema.get('required')), 'content':{'application/json':{'schema':schema}}}
    require(operation, 'no declared request surface')
    # Operation-level notes are upstream operator guidance: internal only.
    if source.get('note') and notes is not None: notes.append(str(source['note']))
    if inp.get('note') and notes is not None: notes.append(str(inp['note']))
    return operation


def source_metadata(document, *, revision, acquired_at, capture_sha256, operation_map):
    """Reviewed automatic source policy; the authority URL is revision-free."""
    base = raw_base(revision)
    source={'kind':'manual','url':TREG_CATALOG_URL,'fetched_at':acquired_at,
            'content_hash':digest(document),'raw_content_hash':'sha256:'+capture_sha256,
            'converter':CONVERTER,'path_space':'public','refresh_policy':'automatic',
            'source_git_revision':revision,
            'operation_map':dict(sorted(operation_map.items())),
            'source_pages':[{'url':base+p,'scope':s}for p,s in [
                ('src/treg/application/call/resolve.py','pathParams arrive as query; array enum and numeric bounds semantics'),
                ('src/treg/domain/catalog/schema/common.py','Parameter declaration vocabulary and optional required flag')]],
            'qualification':'Request-only source review candidate. Exact declarations retained; unsupported shapes remain pending. No formal approval or response schema asserted.'}
    value = initial_policy(source)
    value['refresh_interval_hours'] = REFRESH_INTERVAL_HOURS
    value['policy_revision'] = policy_revision(value)
    return value


def vocabulary_rules(document):
    """Public rules plus the optional secret supplier list (vocab_scan)."""
    from vocab_scan import load_rules, load_terms
    catalogs = {path.split('/')[3] for path in document.get('paths', {}) if path.count('/') >= 3}
    return load_rules(terms=load_terms(), public_names=catalogs)


def scrub_descriptions(document, rules):
    """Drop retained descriptions that fail the public vocabulary scan.

    Returns [(operationId, JSON pointer)] marked description_pending.
    """
    from vocab_scan import scan_text, escape_pointer
    pending = []
    def walk(node, pointer, operation_id):
        if isinstance(node, dict):
            for key in list(node):
                value = node[key]
                if key == 'description' and isinstance(value, str) and scan_text(value, rules):
                    node.pop(key)
                    pending.append((operation_id, pointer + '/description'))
                elif key not in {'examples', 'example', 'default', 'enum'}:
                    walk(value, pointer + '/' + escape_pointer(key), operation_id)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, pointer + '/' + str(index), operation_id)
    for path, item in document.get('paths', {}).items():
        for method, operation in item.items():
            walk(operation, '/paths/' + escape_pointer(path) + '/' + method, operation.get('operationId'))
    return pending


def prepare(vendors, facts, capture, selected, *, capture_sha256, rules=None):
    revision = capture['revision']
    require(re.fullmatch('[0-9a-f]{64}',capture_sha256), 'capture hash required')
    paths, omitted, evidence, notes, operation_map = {}, [], [], {}, {}
    runtime_index = runtime_route_index(facts)
    for vendor in vendors['vendors']:
        if vendor.get('provider_key') != 'treg': continue
        provider = vendor['group']
        for slug, route in sorted(vendor.get('routes',{}).items()):
            if route not in selected: continue
            require(slug in vendor.get('operations',[]), 'route outside captured operation inventory')
            matches = [(m,p,op)for (r,m),(p,op)in runtime_index.items()if r==route]
            require(len(matches)==1, 'ambiguous Runtime operation')
            method, provider, fact = matches[0]
            identity={'provider':provider,'path':route,'method':method,'tool_slug':slug}
            if fact.get('x-aisa-status') != 'enabled':
                omitted.append({**identity,'reason':'runtime_not_enabled'});continue
            source = capture['operations'].get(slug)
            if source is None:
                omitted.append({**identity,'reason':'exact_source_missing'});continue
            op = source['operation']
            operation_notes = []
            try:
                require(op['id']==slug and op['method'].lower()==method, 'source and Runtime method or identity differs')
                require(not op.get('status') or op['status'] in {'active','enabled'}, 'source status needs review: '+str(op.get('status')))
                converted = public_request(op, operation_notes)
            except ValueError as error:
                omitted.append({**identity,'reason':str(error)});continue
            require(route not in paths, 'duplicate public route')
            converted['operationId']=fact['operationId']
            converted['summary']=fact.get('summary',op.get('name',slug))
            paths[route]={method:converted}
            operation_map[route]=slug
            if operation_notes: notes[fact['operationId']]=operation_notes
            evidence.append({**identity,'source_url':source['source']['url'],'source_blob':source['source']['git_blob'],
                             'source_sha256':source['source']['sha256']})
    return finish(paths, capture, capture_sha256, operation_map, notes, rules,
                  {'services_revision':SERVICES_REVISION,'evidence':evidence,'omitted':omitted})


def finish(paths, capture, capture_sha256, operation_map, notes, rules, report):
    revision = capture['revision']
    document={'openapi':'3.1.0','info':{'title':'Treg public request definitions','version':revision},'paths':paths}
    pending = scrub_descriptions(document, rules if rules is not None else vocabulary_rules(document))
    document['info']['x-aisa-source']=source_metadata(document, revision=revision, acquired_at=capture['acquired_at'],
        capture_sha256=capture_sha256, operation_map=operation_map)
    # Internal report only: upstream notes and dropped descriptions never
    # enter the published declaration.
    report.update({'request_operations':len(paths),'formal_publication':False,'response_operations_added':0,
                   'treg_revision':revision,'internal_notes':notes,
                   'description_pending':[{'operation_id':o,'pointer':p} for o,p in pending]})
    return document, report


def refresh_document(previous, capture, *, capture_sha256, rules=None):
    """Re-convert every previously reviewed route at a new captured revision.

    Routes and public identities come from the reviewed previous document
    (its operation_map); only declarations change. A route whose upstream
    operation disappeared or no longer converts is omitted here, and the
    upstream refresh retains the previous declaration for review.
    """
    source = previous.get('info', {}).get('x-aisa-source', {})
    operation_map = source.get('operation_map')
    require(isinstance(operation_map, dict) and operation_map, 'previous declaration has no operation map')
    paths, omitted, notes, kept = {}, [], {}, {}
    for route, item in sorted(previous.get('paths', {}).items()):
        slug = operation_map.get(route)
        for method, published in item.items():
            identity = {'path': route, 'method': method}
            upstream = capture['operations'].get(slug) if slug else None
            if upstream is None:
                omitted.append({**identity, 'reason': 'exact_source_missing'}); continue
            operation_notes = []
            try:
                op = upstream['operation']
                require(op['id'] == slug and op['method'].lower() == method, 'source and published method or identity differs')
                require(not op.get('status') or op['status'] in {'active','enabled'}, 'source status needs review: '+str(op.get('status')))
                converted = public_request(op, operation_notes)
            except (ValueError, KeyError) as error:
                omitted.append({**identity, 'reason': str(error)}); continue
            converted['operationId'] = published['operationId']
            converted['summary'] = published.get('summary', op.get('name', slug))
            paths.setdefault(route, {})[method] = converted
            kept[route] = slug
            if operation_notes: notes[published['operationId']] = operation_notes
    # Keep the map for retained routes too, so a later revision can restore them.
    return finish(paths, capture, capture_sha256, {**operation_map, **kept}, notes, rules, {'omitted': omitted})


def validate_capture(capture, directory):
    """Bind every captured operation back to its immutable upstream file bytes."""
    base = raw_base(capture.get('revision'))
    operations = {}
    for entry in capture['files']:
        raw = (directory / Path(entry['path']).name).read_bytes()
        require(hashlib.sha256(raw).hexdigest()==entry['sha256'], 'source file SHA256 differs')
        blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        require(blob==entry['git_blob'] and entry['url']==base+entry['path'], 'source blob or immutable URL differs')
        if not entry['path'].endswith('.yaml'): continue
        document = yaml.safe_load(raw)
        if not isinstance(document, dict): continue
        for op in document.get('endpoints') or []:
            require(op['id'] not in operations, 'duplicate upstream operation ID')
            operations[op['id']] = json.loads(json.dumps(op,default=str))
    require(set(operations)==set(capture['operations']), 'capture operation inventory differs')
    for identity, operation in operations.items():
        require(capture['operations'][identity]['operation']==operation, 'capture operation differs from captured YAML')


def import_treg_public(root=None, *, revision=None, get=None):
    """Upstream importer for openapi/upstream/treg-public.json (refresh_upstream)."""
    from capture_treg_declarations import capture as take_capture, encode, http_get, resolve_revision
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    previous = json.loads((root / 'openapi/upstream/treg-public.json').read_text())
    captured, _ = take_capture(revision or resolve_revision(), get or http_get)
    document, _ = refresh_document(previous, captured, capture_sha256=hashlib.sha256(encode(captured)).hexdigest())
    return document


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('services-repository','snapshot','snapshot-proof','pending-pages-receipt',
                 'capture','source-directory','output','report'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--capture-sha256',required=True)
    parser.add_argument('--revision',required=True,help='Reviewed upstream revision the capture must bind')
    args=parser.parse_args()
    require(not args.output.exists() and not args.report.exists(), 'output and report must be new files')
    raw=args.capture.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==args.capture_sha256,'capture differs from caller hash')
    capture=json.loads(raw)
    require(capture.get('revision')==args.revision,'capture revision differs from the reviewed revision')
    validate_capture(capture,args.source_directory)
    proof=json.loads(args.snapshot_proof.read_text());proof.pop('files',None)
    require(proof['compiler_revision']==SERVICES_REVISION,'unreviewed Runtime revision')
    documents,binding=load_snapshot(args.snapshot,**proof)
    facts={Path(name).stem:json.loads(raw)for name,raw in documents.items()}
    pending=json.loads(args.pending_pages_receipt.read_text())
    require(all(pending['source'].get(k)==v for k,v in proof.items()),'pending inventory differs from snapshot')
    selected={row['path']for rows in pending['pending']['providers'].values()for row in rows
              if row.get('reason')=='upstream operation missing'}
    routes=subprocess.check_output(['git','show',SERVICES_REVISION+':'+ROUTES_PATH],cwd=args.services_repository)
    document,report=prepare(json.loads(routes),facts,capture,selected,capture_sha256=args.capture_sha256)
    report['snapshot']=binding;report['routes_sha256']=hashlib.sha256(routes).hexdigest()
    args.output.write_text(json.dumps(document,indent=2,ensure_ascii=False)+'\n')
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key]for key in ('request_operations','response_operations_added','formal_publication')}))


if __name__=='__main__':main()
