"""Extract the supplier-coauthored historical Full Search OpenAPI from AWS's article."""
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
import re

REFERENCE_URL = 'https://aws.amazon.com/cn/blogs/china/building-enterprise-level-with-bedrock-agentcore-and-strands/'
ARTICLE_DATE = '2025-11-20'
VERSION = 'scripts/wrapper_cloudsway_full_reference.py@1'
EMBEDDED_SHA256 = 'bec33e8ee815b00bcceacf9e4ad6246d7785d22223b3d403a1696fb44e620581'
UPSTREAM_PATH_SHA256 = 'eb38730f21101320f1e6bb71a906895508cfecb1101ded67d70b1a15639e387b'
PUBLIC_PATH = '/apis/v1/search/full'


class CodeBlocks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks, self.block = [], None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1
        if tag == 'pre' and not self.skip:
            if self.block is not None:
                raise ValueError('nested article code blocks')
            self.block = []

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip -= 1
        if tag == 'pre' and self.block is not None:
            self.blocks.append(''.join(self.block))
            self.block = None

    def handle_data(self, value):
        if self.block is not None and not self.skip:
            self.block.append(value)


def convert_reference(raw):
    parser = CodeBlocks()
    parser.feed(raw.decode('utf-8'))
    candidates = []
    for block in parser.blocks:
        if '"openapi"' not in block:
            continue
        try:
            document = json.loads(block[block.index('{'):])
        except (ValueError, TypeError):
            continue
        if document.get('info', {}).get('title') == 'Full Text SearchAPI':
            candidates.append(document)
    if len(candidates) != 1:
        raise ValueError('expected exactly one historical Full Search OpenAPI')
    original = candidates[0]
    encoded = json.dumps(original, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    embedded_hash = hashlib.sha256(encoded).hexdigest()
    if embedded_hash != EMBEDDED_SHA256:
        raise ValueError('historical embedded contract changed; review required')
    paths = original.get('paths', {})
    if len(paths) != 1:
        raise ValueError('historical Full Search path count changed')
    private_path, item = next(iter(paths.items()))
    if not re.fullmatch(r'/search/[^/]+/full', private_path) or set(item) != {'get'}:
        raise ValueError('historical Full Search method or path changed')
    document = deepcopy(original)
    op = deepcopy(item['get'])
    source_operation_id = op.pop('operationId', None)  # Upstream ID is not an established public identity.
    document['paths'] = {PUBLIC_PATH: {'get': op}}
    # Do not leak the article's demo account endpoint in any incidental prose.
    serialized = json.dumps(document, ensure_ascii=False).replace(private_path, '/search/{Endpoint}/full')
    document = json.loads(serialized)
    return document, {
        'kind': 'manual', 'converter': VERSION, 'path_space': 'public', 'lifecycle': 'historical',
        'article_date': ARTICLE_DATE, 'embedded_openapi_sha256': 'sha256:' + embedded_hash,
        'upstream_path_sha256': UPSTREAM_PATH_SHA256, 'original_upstream_path_template': '/search/{Endpoint}/full',
        'upstream_operation_id': source_operation_id,
        'public_path_mapping': 'Reviewed AIsa Cloudsway routing exposes this account-specific Full Search path as /apis/v1/search/full.',
        'note': 'Supplier-coauthored historical contract. No current authenticated availability was verified. The CLI separately records historical HTML 404 failures.',
        'source_pages': [{'url': REFERENCE_URL, 'raw_content_hash': 'sha256:' + hashlib.sha256(raw).hexdigest()}],
    }


def import_reference(fetch):
    return convert_reference(fetch(REFERENCE_URL))
