"""Convert pinned Treg declarations at the actual /call HTTP boundary.

This creates request-source review candidates only. Unsupported or incomplete
DSL stays omitted; no provider calls, response guesses, or review receipts.
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
from source_governance import initial_policy
from prepare_composio_public_reference import SERVICES_REVISION, ROUTES_PATH, require, runtime_route_index
from internal_publication_snapshot import load_snapshot

TREG_REVISION = '95670bbae5561fce0ea55c1e0ee4216eb34cbf18'
BASE = 'https://raw.githubusercontent.com/superdesigndev/treg/' + TREG_REVISION + '/'


def field_schema(spec):
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
        result = {'type': 'array', 'items': field_schema(spec['items'])}
    elif kind in {'string','integer','number','boolean','object'}:
        result = {'type': kind}
    else:
        raise ValueError('unsupported declared type: ' + kind)
    if kind == 'object':
        require('properties' in spec or spec.get('additionalProperties') is True,
                'object fields are undeclared; openness is not asserted')
        if 'properties' in spec:
            result.update(object_fields(spec['properties']))
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
    descriptions = [str(spec[k]) for k in ('description','note') if spec.get(k)]
    if descriptions: result['description'] = '\n\n'.join(descriptions)
    if 'example' in spec: result['examples'] = [copy.deepcopy(spec['example'])]
    required = spec.get('required', False)
    require(isinstance(required, bool), 'nested required list needs independent conversion')
    return result


def object_fields(fields):
    require(isinstance(fields, dict), 'body field map required')
    result = {'type':'object', 'properties':{}, 'required':[]}
    for name, spec in fields.items():
        result['properties'][name] = field_schema(spec)
        if spec.get('required', False): result['required'].append(name)
    if not result['required']: result.pop('required')
    return result


def public_request(source):
    # A field-level DSL is not the whole contract: the owning executor also
    # interprets operation-level admission/credential restrictions. Unknown
    # behavior is never silently flattened into a permissive request schema.
    metadata = {'id','platform','method','path','name','summary','docs_url','input','added',
                'capability','test_request','cost','example_response','verified','scope','domain',
                'tier','price','observed_time','miss','untestable','cache','expect','unverified',
                'host','skipped','status','status_note','kind','observed_from','not_found'}
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
            schema = field_schema(spec)
            require(schema['type'] in {'string','integer','number','boolean'}, 'query array/object serialization needs explicit review')
            # /call/{operation-id} consumes its upstream placeholders from query.
            required = name in placeholders or spec.get('required', False)
            operation['parameters'].append({'name':name,'in':'query','required':required,'schema':schema})
    if not operation['parameters']: operation.pop('parameters')
    if 'body' in inp:
        body = inp['body']
        require(isinstance(body,dict) and all(isinstance(v,dict) for v in body.values()), 'whole-body declaration needs independent conversion')
        schema = object_fields(body)
        if source.get('body_allowlist'):
            schema['additionalProperties'] = False
            for name in schema.get('required',[]):
                field = schema['properties'][name]
                if field['type'] == 'string':
                    field['minLength'] = max(1,field.get('minLength',0))
        operation['requestBody'] = {'required':bool(source.get('body_allowlist') or schema.get('required')), 'content':{'application/json':{'schema':schema}}}
    require(operation, 'no declared request surface')
    if inp.get('note'): operation['description'] = inp['note']
    return operation


def prepare(vendors, facts, capture, selected, *, capture_sha256):
    require(capture['revision'] == TREG_REVISION, 'unreviewed Treg revision')
    require(re.fullmatch('[0-9a-f]{64}',capture_sha256), 'pinned capture hash required')
    paths, omitted, evidence = {}, [], []
    runtime_index = runtime_route_index(facts)
    for vendor in vendors['vendors']:
        if vendor.get('provider_key') != 'treg': continue
        provider = vendor['group']
        for slug, route in sorted(vendor.get('routes',{}).items()):
            if route not in selected: continue
            require(slug in vendor.get('operations',[]), 'route outside pinned operation inventory')
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
            try:
                require(op['id']==slug and op['method'].lower()==method, 'source and Runtime method or identity differs')
                require(not op.get('status') or op['status'] in {'active','enabled'}, 'source status needs review: '+str(op.get('status')))
                converted = public_request(op)
            except ValueError as error:
                omitted.append({**identity,'reason':str(error)});continue
            require(route not in paths, 'duplicate public route')
            converted['operationId']=fact['operationId']
            converted['summary']=fact.get('summary',op.get('name',slug))
            paths[route]={method:converted}
            evidence.append({**identity,'source_url':source['source']['url'],'source_blob':source['source']['git_blob'],
                             'source_sha256':source['source']['sha256']})
    document={'openapi':'3.1.0','info':{'title':'Treg public request definitions','version':TREG_REVISION},'paths':paths}
    source={'kind':'manual','url':BASE+'src/treg/catalog/','fetched_at':capture['acquired_at'],
            'content_hash':digest(document),'raw_content_hash':'sha256:'+capture_sha256,
            'converter':'scripts/prepare_treg_public_reference.py@1','path_space':'public',
            'refresh_policy':'pinned','refresh_reason':'Review immutable provider declarations and both gateway HTTP boundaries together.',
            'source_git_revision':TREG_REVISION,
            'source_pages':[{'url':BASE+p,'scope':s}for p,s in [
                ('src/treg/application/call/resolve.py','pathParams arrive as query; array enum and numeric bounds semantics'),
                ('src/treg/domain/catalog/schema/common.py','Parameter declaration vocabulary and optional required flag')]],
            'qualification':'Request-only source review candidate. Exact declarations retained; unsupported shapes remain pending. No formal approval or response schema asserted.'}
    document['info']['x-aisa-source']=initial_policy(source)
    return document,{'request_operations':len(paths),'formal_publication':False,'response_operations_added':0,
                    'treg_revision':TREG_REVISION,'services_revision':SERVICES_REVISION,'evidence':evidence,'omitted':omitted}


def validate_capture(capture, directory):
    """Bind every captured operation back to its immutable upstream file bytes."""
    require(capture.get('revision') == TREG_REVISION, 'unreviewed source revision')
    operations = {}
    for entry in capture['files']:
        raw = (directory / Path(entry['path']).name).read_bytes()
        require(hashlib.sha256(raw).hexdigest()==entry['sha256'], 'source file SHA256 differs')
        blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        require(blob==entry['git_blob'] and entry['url']==BASE+entry['path'], 'source blob or immutable URL differs')
        if not entry['path'].endswith('.yaml'): continue
        document = yaml.safe_load(raw)
        for op in document.get('endpoints',[]):
            require(op['id'] not in operations, 'duplicate upstream operation ID')
            operations[op['id']] = json.loads(json.dumps(op,default=str))
    require(set(operations)==set(capture['operations']), 'capture operation inventory differs')
    for identity, operation in operations.items():
        require(capture['operations'][identity]['operation']==operation, 'capture operation differs from pinned YAML')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('services-repository','snapshot','snapshot-proof','pending-pages-receipt',
                 'capture','source-directory','output','report'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--capture-sha256',required=True)
    args=parser.parse_args()
    require(not args.output.exists() and not args.report.exists(), 'output and report must be new files')
    raw=args.capture.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==args.capture_sha256,'capture differs from caller hash')
    capture=json.loads(raw); validate_capture(capture,args.source_directory)
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
