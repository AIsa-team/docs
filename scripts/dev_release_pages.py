"""Project a verified dev Runtime release into the dev Mintlify site."""
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from contract_page_links import operations, page_reference
from fetch_runtime_release import decode, sha
from pull_openapi import (existing_page_references, generate_pages, refresh_legacy_page_blocks,
                          refresh_localized_documents)
from readable_contract_notes import strip_generated_block
from regroup_api_reference import index_pages, validate_preserved_navigation
import api_nav_groups
from runtime_contract_artifact import AGGREGATE, NATIVE
from runtime_consolidate_openapi import publication_yaml
from runtime_registry import published_documents

DEV_SITE = 'https://aisa-docs-dev.mintlify.dev/docs'
DEV_API = 'https://dev-api.aisa.one'
ARCHIVE_NOTE = '<Warning>This endpoint is unavailable in the current dev Runtime contract snapshot.</Warning>\n\n'
HISTORIC_NOTES = {
    'en': '<Warning>This existing API reference is preserved. This endpoint has not been verified in the current dev Runtime contract snapshot.</Warning>\n\n',
    'zh': '<Warning>此页面保留原有接口文档。该接口尚未在当前 dev Runtime 合同中验证。</Warning>\n\n',
}
PRODUCTION_NOTES = {
    'en': '<Warning>This reference has not been verified against the current production API contract.</Warning>\n\n',
    'zh': '<Warning>此文档尚未通过当前生产接口契约的核验。</Warning>\n\n',
}
DISABLED_NOTES = {
    'en': '<Warning>This endpoint is disabled. Its historical documentation is retained for reference.</Warning>\n\n',
    'zh': '<Warning>此接口已停用，保留历史文档仅供参考。</Warning>\n\n',
}


def project_openapi(raw):
    document = decode(raw)
    changed = False
    for _, _, op in operations(document):
        link = op.get('x-aisa-docs-url', '')
        if link.startswith('https://aisa.one/docs/api-reference/'):
            op['x-aisa-docs-url'] = DEV_SITE + link.removeprefix('https://aisa.one/docs')
            changed = True
    nodes = [document, *document['paths'].values()]
    nodes.extend(op for _, _, op in operations(document))
    for node in nodes:
        for server in node.get('servers', []):
            url = server['url']
            parsed = urlsplit(url)
            if parsed.scheme == 'https' and parsed.netloc == 'api.aisa.one':
                server['url'] = parsed._replace(netloc='dev-api.aisa.one').geturl()
                changed = True
    if not changed:
        return document, raw
    document['info']['x-aisa-dev-projection'] = {'source_sha256': sha(raw)}
    meta = document['info'].get('x-aisa-document', {})
    for record in [meta, *meta.get('providers', {}).values()]:
        if 'document_hash' in record:
            record['source_document_hash'] = record.pop('document_hash')
    return document, (json.dumps(document, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def project(root, files, release):
    from human_api_retirements import apply_retirements

    original = published_documents(root)
    references = defaultdict(list)
    for ref in existing_page_references(root):
        references[ref[0]].append(ref)
    changes, outputs, native, legacy = {}, {}, {}, {}
    for name, raw in sorted(files.items()):
        if not NATIVE.fullmatch(name):
            continue
        provider = Path(name).stem
        spec = 'openapi/' + provider + '.json'
        document, outputs[spec] = project_openapi(raw)
        native[provider] = document
        meta = document['info'].get('x-aisa-document', {})
        if not (meta.get('document_hash') or meta.get('source_document_hash')):
            legacy[provider] = document
            continue
        # Runtime owns the primary slug, including pages that have moved providers.
        primary = {}
        for _, _, op in operations(document):
            page = op.get('x-aisa-docs-url', '').removeprefix(DEV_SITE + '/')
            if not re.fullmatch(r'api-reference/(?:[\w.-]+/)*[\w.-]+', page) or any(
                    part in {'.', '..'} for part in page.split('/')):
                raise ValueError('Invalid published page for ' + op['operationId'])
            primary[op['operationId']] = page
        generate_pages(root, provider, document, changes, original.get(provider),
                       decorate_links=False, page_references=references[spec], published_pages=primary)

    catalog = json.loads((root / 'translations/openapi-zh.json').read_text())
    refresh_localized_documents(root, native, changes, catalog)
    refresh_legacy_page_blocks(root, legacy, changes, catalog)
    apply_retirements(root, changes)

    # Keep authored historical pages readable when their previous binding no
    # longer exists. Removing the binding also disables the stale playground.
    for prefix, language in (('', 'en'), ('zh/', 'zh')):
        directory = root / (prefix + 'api-reference')
        pages = set(directory.rglob('*.mdx')) | {p for p in changes if p.is_relative_to(directory)}
        for page in pages:
            text = changes[page] if page in changes else page.read_text()
            # A re-enabled operation can reuse an archived page.
            text = text.replace('\nx-aisa-archived-openapi:', '\nopenapi:')
            ref = page_reference(text)
            if ref is None:
                continue
            spec, method, path = ref
            op = native.get(Path(spec).stem, {}).get('paths', {}).get(path, {}).get(method)
            for notice in (ARCHIVE_NOTE, HISTORIC_NOTES[language], PRODUCTION_NOTES[language], DISABLED_NOTES[language]):
                text = re.sub(re.escape(notice.rstrip('\n')) + r'\n{0,2}', '', text)
            if op is None or op.get('x-aisa-status') == 'disabled':
                text = re.sub(r'^openapi:', 'x-aisa-archived-openapi:', text, count=1, flags=re.M)
                notice = DISABLED_NOTES[language] if op else HISTORIC_NOTES[language]
                if op is None:
                    text = strip_generated_block(text)
                text = text.replace('\n---\n', '\n---\n' + notice, 1).rstrip('\n') + '\n'
            # Only the managed download link targets the dev site.
            text = text.replace('](https://aisa.one/docs/' + spec + ')',
                                '](' + DEV_SITE + '/' + spec + ')')
            changes[page] = text

    config_path = root / 'docs.json'
    config = json.loads(changes.get(config_path, config_path.read_text()))
    validate_preserved_navigation(config)
    config['api']['mdx']['server'] = DEV_API + '/v1'
    config['markdown']['instructions'] = (
        '- Documentation and API environment: dev. Use a dev API key.\n'
        f'- API base: {DEV_API}/apis/v1. Follow each operation’s servers.\n'
        f'- Immutable Runtime OpenAPI: {DEV_API}/public/api-contract/releases/{release["artifact_revision"]}/{AGGREGATE}'
    )
    changes[config_path] = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    labels = json.loads((root / 'translations/openapi-nav-zh.json').read_text())
    for name, text in index_pages(config, api_nav_groups.load(root), labels, root).items():
        changes[root / name] = text

    outputs.update({path.relative_to(root).as_posix(): text.encode() for path, text in changes.items()})
    aggregate, outputs['openapi/openapi.json'] = project_openapi(files[AGGREGATE])
    outputs['openapi.yaml'] = publication_yaml(aggregate).encode()
    return outputs
