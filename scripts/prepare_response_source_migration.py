"""Plan and prepare pinned public-response source migrations without approval.

A plan is reviewable data, never permission to carry historical schemas across
an upstream binding change. Preparation requires an explicit per-route decision
whose old bytes/schema and current transport/request pins still match.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from compose_openapi import METHODS, digest, effective_public_operation, has_response_contract, referenced_components, response_object
from contract_readiness import binding_hash
from source_json import loads

VERSION = 'scripts/prepare_response_source_migration.py@1'
DECISION = 'accept_existing_public_response'


def normalized(document):
    value=copy.deepcopy(document)
    server=urlsplit((value.get('servers') or [{'url':'https://api.aisa.one'}])[0]['url'])
    if server.scheme!='https' or server.netloc!='api.aisa.one' or server.query or server.fragment:
        raise ValueError('published and Runtime documents must use the public AIsa server')
    value['paths']={server.path.rstrip('/')+path:item for path,item in value.get('paths',{}).items()}
    value['servers']=[{'url':'https://api.aisa.one'}]
    return value


def raw_hash(raw):
    return hashlib.sha256(raw).hexdigest()


def success_contract(operation, document):
    responses = {}
    for status, raw in operation.get('responses', {}).items():
        if not re.fullmatch(r'2(?:[0-9]{2}|XX)', str(status)):
            continue
        value = response_object(raw, document)
        if not has_response_contract(value) and not (str(status) in {'204', '205'} and not value.get('content')):
            raise ValueError('historical success response lacks complete declared schema: '+str(status))
        responses[str(status)] = {key:copy.deepcopy(value[key]) for key in ('description','content','x-aisa-no-content') if key in value}
    if not responses:
        raise ValueError('historical success response is absent')
    operation = {'responses': responses}
    components = referenced_components(operation, document)
    return operation, components


def current_operation(facts, path, method):
    item = facts.get('paths', {}).get(path, {})
    current = item.get(method, item.get('x-aisa-any'))
    if not isinstance(current, dict):
        raise ValueError('current public route/method absent')
    value = effective_public_operation(item, current, facts)
    if value.get('x-aisa-response-passthrough') is not True:
        raise ValueError('current Runtime does not attest unchanged response transport')
    for key in ('x-aisa-response-upstream-path-sha256','x-aisa-response-upstream-origin-sha256'):
        if not isinstance(value.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', value[key]):
            raise ValueError('current Runtime response binding pin absent or invalid')
    return value


def plan(published_raw, facts, source_url, source_revision):
    if not source_url.startswith('https://') or not re.fullmatch(r'[0-9a-f]{40}', source_revision):
        raise ValueError('pinned HTTPS owning-source URL and full Git revision required')
    published=normalized(loads(published_raw));facts=normalized(facts)
    rows=[]
    for path,item in sorted(published.get('paths',{}).items()):
        for method,old in sorted(item.items()):
            if method not in METHODS:
                continue
            row={'path':path,'method':method.upper(),'operation_id':old.get('operationId'),
                 'review_decision':'pending','review_evidence':None}
            try:
                if not isinstance(old.get('operationId'),str) or not old['operationId']:
                    raise ValueError('published immutable operation identity absent')
                current=current_operation(facts,path,method)
                if current.get('operationId')!=old['operationId']:
                    raise ValueError('published and current operation identities differ')
                response,components=success_contract(old,published)
                row.update(status='review_required',success_contract_sha256=digest({'operation':response,'components':components}),
                    current_request_binding_sha256=binding_hash(current,facts),
                    upstream_path_sha256=current['x-aisa-response-upstream-path-sha256'],
                    upstream_origin_sha256=current['x-aisa-response-upstream-origin-sha256'])
            except (ValueError,KeyError,TypeError) as exc:
                row.update(status='blocked',reason=str(exc))
            rows.append(row)
    return {'schema_version':1,'source_document_sha256':raw_hash(published_raw),
            'source_url':source_url,'source_revision':source_revision,'source_approved':False,
            'scope':'Per-route response migration proposal. Review source semantics and unchanged binding before accepting each row.',
            'rows':rows}


def prepare(published_raw, facts, review):
    if review.get('schema_version')!=1 or review.get('source_approved') is not False:
        raise ValueError('migration input must remain an unapproved review proposal')
    computed=plan(published_raw,facts,review.get('source_url',''),review.get('source_revision',''))
    if review.get('source_document_sha256')!=computed['source_document_sha256']:
        raise ValueError('published source bytes changed')
    expected={(r['path'],r['method']):r for r in computed['rows']}
    published=normalized(loads(published_raw));result={};seen=set()
    for row in review.get('rows',[]):
        key=(row.get('path'),row.get('method'))
        if key in seen:raise ValueError('duplicate review route')
        seen.add(key)
        if row.get('review_decision')=='pending':continue
        if row.get('review_decision')!=DECISION or not isinstance(row.get('review_evidence'),str) or not row['review_evidence'].strip():
            raise ValueError('explicit per-route review decision and evidence required')
        current=expected.get(key)
        pins=('operation_id','status','success_contract_sha256','current_request_binding_sha256','upstream_path_sha256','upstream_origin_sha256')
        if not current or current.get('status')!='review_required' or any(row.get(k)!=current.get(k) for k in pins):
            raise ValueError('reviewed response or current request/transport binding changed')
        path,method=key;operation,components=success_contract(published['paths'][path][method.lower()],published)
        metadata={'kind':'manual','url':computed['source_url'],'source_revision':computed['source_revision'],
            'converter':VERSION,'refresh_policy':'pinned','refresh_reason':'Public response migration requires per-route binding and semantic review.',
            'response_only':True,'path_space':'public','upstream_path_sha256':row['upstream_path_sha256'],
            'upstream_origin_sha256':row['upstream_origin_sha256'],'content_hash':row['success_contract_sha256'],
            'source_document_sha256':computed['source_document_sha256'],'review_evidence':row['review_evidence']}
        # Caller must provide the original acquisition/verification timestamp;
        # migration execution time is not falsely presented as a source fetch.
        if not isinstance(review.get('source_verified_at'),str) or not review['source_verified_at']:
            raise ValueError('verified source timestamp required')
        metadata['fetched_at']=review['source_verified_at']
        doc={'openapi':published.get('openapi','3.1.0'),'info':{'title':'Reviewed public response '+row['operation_id'],
            'version':computed['source_revision'],'x-aisa-source':metadata},'servers':[{'url':'https://api.aisa.one'}],
            'paths':{path:{method.lower():operation}},'components':components}
        result[method.lower()+'-'+hashlib.sha256(path.encode()).hexdigest()[:16]+'.json']=doc
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['plan','prepare']);parser.add_argument('--published',required=True,type=Path)
    parser.add_argument('--facts',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--source-url');parser.add_argument('--source-revision');parser.add_argument('--review',type=Path)
    args=parser.parse_args();raw=args.published.read_bytes();facts=loads(args.facts.read_bytes())
    if args.mode=='plan':
        value=plan(raw,facts,args.source_url or '',args.source_revision or '')
        args.output.write_text(json.dumps(value,indent=2)+'\n')
    else:
        if not args.review:parser.error('--review is required for prepare')
        documents=prepare(raw,facts,loads(args.review.read_bytes()));args.output.mkdir(parents=True,exist_ok=True)
        if any(args.output.iterdir()):raise ValueError('candidate output directory must be empty')
        for filename,document in documents.items():(args.output/filename).write_text(json.dumps(document,indent=2)+'\n')
    print('Unapproved response migration prepared; no source registration, production mutation or publication performed.')

if __name__=='__main__':main()
