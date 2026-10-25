"""Import Unipile's official v1 schema and its v2 job-slot OpenAPI fragment."""
import copy
import hashlib
import re

from compose_openapi import digest
from source_json import loads

V1_URL = 'https://api68.unipile.com:19823/api-json'
JOB_SLOTS_URL = 'https://developer.unipile.com/v2.0/reference/getrecruiterjobslotscredits.md'
JOB_SLOTS_PATH = '/v2/{account_id}/linkedin/recruiter/job-slots-credits'
VERSION = 'scripts/import_unipile_reference.py@1'


def convert_reference(raw, url):
    metadata = {'converter': VERSION,
                'raw_content_hash': 'sha256:' + hashlib.sha256(raw).hexdigest()}
    if url == V1_URL:
        document = loads(raw)
        if not isinstance(document, dict) or not isinstance(document.get('paths'), dict):
            raise ValueError('Unipile v1 OpenAPI paths are required')
        original_hash = digest(document)
        document = copy.deepcopy(document)
        old = '/api/v1/users/{identifier}/posts'
        new = '/api/v1/users/{user_id}/posts'
        if old not in document['paths'] or new in document['paths']:
            raise ValueError('Unipile user posts path binding changed')
        item = document['paths'].pop(old)
        renamed = 0
        for container in (item, item.get('get', {})):
            for parameter in container.get('parameters', []):
                if parameter.get('in') == 'path' and parameter.get('name') == 'identifier':
                    parameter['name'] = 'user_id'
                    renamed += 1
        if renamed != 1 or 'get' not in item:
            raise ValueError('Unipile user posts requires one exact path parameter')
        document['paths'][new] = item
        metadata.update(upstream_content_hash=original_hash,
                        path_parameter_binding={'source_path': old, 'runtime_target': new,
                                                'source_name': 'identifier', 'runtime_name': 'user_id'})
    elif url == JOB_SLOTS_URL:
        # The v2 management Swagger omits this LinkedIn operation. Read the
        # actual OpenAPI supplied by the official reference, never page scripts.
        blocks = re.findall(r'^```json\s*\n(.*?)\n```\s*$', raw.decode('utf-8'), re.M | re.S)
        if len(blocks) != 1:
            raise ValueError('One official Unipile OpenAPI JSON block is required')
        document = loads(blocks[0])
        if not isinstance(document, dict) or set(document.get('paths', {})) != {JOB_SLOTS_PATH}:
            raise ValueError('Unipile job slots source path changed')
        item = document['paths'][JOB_SLOTS_PATH]
        if set(item) != {'get'} or item['get'].get('operationId') != 'getRecruiterJobSlotsCredits':
            raise ValueError('Unipile job slots source operation changed')
        metadata['upstream_content_hash'] = digest(document)
    else:
        raise ValueError('Unsupported Unipile reference URL')
    if not str(document.get('openapi', '')).startswith('3.'):
        raise ValueError('Unipile reference must contain OpenAPI 3')
    return document, metadata
