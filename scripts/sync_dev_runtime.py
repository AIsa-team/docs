"""Generate dev documentation from verified dev or production Runtime facts.

This is a dev preview consumer, independent of production formal publication.
Production preview reads public immutable releases but never publishes to main,
approves source receipts, or notifies production consumers.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

from fetch_runtime_release import PublicReader, decode, require, sha, category_content
from fetch_runtime_release import acquire as acquire_release, validate_current, ACQUISITION_SECONDS
from pull_openapi import stage, update_disabled_indexing
from check_nav_integrity import nav_pages
from pricing_prose import clean_page, remove_price_summary
from readable_contract_notes import update_readable_block
from runtime_localize_openapi_zh import translation
from identity_compatibility import published_history
from regroup_api_reference import write_index_pages
from runtime_consolidate_openapi import (build_unified_spec, publication_yaml,
                                        inject_x402_annotations, remove_v2_path_mirrors)


DEV_ORIGIN = 'https://dev-api.aisa.one'
PROD_ORIGIN = 'https://api.aisa.one'
ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(r'[a-z0-9][a-z0-9_.-]*')
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


def source_origin(source):
    require(source in {'dev', 'production'}, 'Unsupported Runtime source')
    return PROD_ORIGIN if source == 'production' else DEV_ORIGIN


def acquire_production(reader):
    """Reuse the production release reader; do not fall back to mixed live facts."""
    current = decode(reader('/public/api-contract/current')[0])
    revision, compiler = current.get('artifact_revision'), current.get('compiler_revision')
    validate_current(current, revision, compiler)
    contents, category, _, _, receipt = acquire_release(revision, compiler, reader)
    files = {'index.json': contents['index.json'], 'category.json': category}
    files.update({Path(name).name: raw for name, raw in contents.items() if name.startswith('providers/')})
    provenance = {key: receipt[key] for key in (
        'artifact_revision', 'compiler_revision', 'source_digest', 'generation',
        'fresh_before_and_after', 'provider_count')}
    return files, provenance


def prune_navigation(node, hidden):
    if isinstance(node, dict):
        return {key: prune_navigation(value, hidden) for key, value in node.items()}
    if isinstance(node, list):
        result = []
        for value in node:
            if isinstance(value, str) and value in hidden:
                continue
            value = prune_navigation(value, hidden)
            if isinstance(value, dict):
                children = [key for key in ('pages', 'groups', 'tabs') if key in value]
                if children and not any(value[key] for key in children):
                    continue
            result.append(value)
        return result
    return node


def preserve_navigation(previous, current):
    """Keep the existing hierarchy and add new generated pages exactly once."""
    additions = prune_navigation(current, set(nav_pages(previous)))

    def merge(left, right):
        result = copy.deepcopy(left)
        if isinstance(left, dict) and isinstance(right, dict):
            for key, value in right.items():
                result[key] = merge(result[key], value) if key in result else copy.deepcopy(value)
        elif isinstance(left, list) and isinstance(right, list):
            for item in right:
                key = next((key for key in ('language', 'tab', 'group')
                            if isinstance(item, dict) and key in item), None)
                matching = next((i for i, old in enumerate(result)
                                 if key and isinstance(old, dict) and old.get(key) == item[key]), None)
                if matching is not None:
                    result[matching] = merge(result[matching], item)
                elif item not in result:
                    result.append(copy.deepcopy(item))
        return result

    return merge(previous, additions)


def scope_presentation(candidate, aggregate, summary, *, source='dev'):
    """Preserve reference navigation; aggregate only verified dev contracts."""
    config_path = candidate / 'docs.json'
    config = json.loads(config_path.read_text())
    listed = set(nav_pages(config.get('navigation', {})))
    active = {key for key, value in summary.items() if not value.get('blocked')}
    for path, item in list(aggregate['paths'].items()):
        for method, operation in list(item.items()):
            if isinstance(operation, dict) and (operation.get('x-aisa-provider') not in active or
                    operation.get('x-aisa-status') == 'disabled'):
                del item[method]
        if not item:
            del aggregate['paths'][path]
    metadata = aggregate['info'].get('x-aisa-document', {})
    if 'providers' in metadata:
        metadata['providers'] = {key: value for key, value in metadata['providers'].items() if key in active}
    aggregate['info']['title'] = 'AIsa Dev API'
    aggregate['info']['x-aisa-environment'] = source
    aggregate['info']['x-aisa-docs-environment'] = 'dev'
    aggregate['info']['x-aisa-publication-kind'] = 'production_release_preview' if source == 'production' else 'live_facts_preview'
    documents = {}
    catalog_path = candidate / 'translations/openapi-zh.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {'entries': {}}

    def translated_note(note):
        try:
            return translation(catalog, note)
        except KeyError:
            return note

    hidden, preserved = set(), set()
    for base in ('api-reference', 'zh/api-reference'):
        for page in (candidate / base).rglob('*.mdx'):
            text = page.read_text()
            match = re.search(r"^openapi:\s*['\"]?(openapi/[^\s'\"]+\.json)\s+(\w+)\s+([^\s'\"]+)", text, re.M)
            if not match:
                continue
            name, method, path = match.groups()
            if name not in documents:
                document = json.loads((candidate / name).read_text())
                original = copy.deepcopy(document)
                # Retained/blocked operations bypass composition. Dev is a
                # presentation preview: clean their displayed descriptions too,
                # without changing contract prices, status or provenance.
                for item in document.get('paths', {}).values():
                    for verb in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'):
                        if isinstance(item.get(verb), dict):
                            remove_price_summary(item[verb])
                documents[name] = document
                if document != original:
                    (candidate / name).write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
            provider = Path(name).name.removesuffix('.json').removesuffix('.zh')
            operation = documents[name].get('paths', {}).get(path, {}).get(method.lower())
            unverified = provider not in active or operation is None or operation.get('x-aisa-status') == 'disabled'
            reference = page.relative_to(candidate).with_suffix('').as_posix()
            unlisted = unverified and reference not in listed
            text = update_disabled_indexing(text, unlisted).replace(ARCHIVE_NOTE, '')
            for note in (*HISTORIC_NOTES.values(), *PRODUCTION_NOTES.values(), *DISABLED_NOTES.values()):
                text = text.replace(note, '')
            if unverified:
                language = 'zh' if base.startswith('zh/') else 'en'
                text = clean_page(text, language)
                # A retained operation without a Runtime pricing declaration
                # is still a historical archive. The readable presentation
                # layer supplies the archive status while the OpenAPI
                # operation and metadata remain unchanged.
                presentation_operation = copy.deepcopy(operation) if operation is not None else {}
                presentation_operation.setdefault('x-aisa-status', 'disabled')
                if operation is not None:
                    text = update_readable_block(text, presentation_operation, language, translated_note,
                        document=documents[name], method=method.lower(), path=path, spec_path=name)
                else:
                    text = update_readable_block(text, presentation_operation, language)
                if unlisted:
                    hidden.add(reference)
                    notice = ARCHIVE_NOTE
                else:
                    preserved.add(reference)
                    notice = HISTORIC_NOTES['zh' if base.startswith('zh/') else 'en']
                if source == 'production':
                    notes = DISABLED_NOTES if operation is not None and operation.get('x-aisa-status') == 'disabled' else PRODUCTION_NOTES
                    notice = notes[language]
                # Put the notice after frontmatter, preserving endpoint identity.
                end = text.index('\n---\n', 4) + 5
                text = text[:end] + notice + text[end:]
            page.write_text(text)

    config['name'] = 'AIsa Dev'
    config.setdefault('markdown', {})['instructions'] = (
        f'- Documentation environment: dev. API environment: {source}. Use an API key for that environment.\n'
        f'- API base: `{source_origin(source)}/apis/v1`. Follow each operation\'s servers.\n'
        '- Dev OpenAPI: https://raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi.yaml.\n'
        '- Call only operations present in the selected contract. Do not make paid calls to test availability.\n'
        '- Never print, log, or commit API keys.'
    )
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n')
    return {'preserved_historic_pages': len(preserved), 'hidden_historic_pages': len(hidden)}


def acquire(reader):
    """Read each provider twice and bracket it with an unchanged full index."""
    before, _ = reader('/info/openapi.json')
    index = decode(before)
    providers = index.get('providers')
    require(isinstance(providers, list) and 0 < len(providers) <= 512,
            'Dev Runtime provider index is unavailable')
    require(not index.get('pending_providers') and not index.get('pending_endpoints'),
            'Dev Runtime has pending contract projections')
    keys = [row.get('id') for row in providers]
    require(all(isinstance(key, str) and KEY.fullmatch(key) and key not in
                {'index', 'category', 'acquisition-receipt'} for key in keys) and
            len(set(keys)) == len(keys), 'Invalid dev provider identity')
    category, _ = reader('/info/apis/category')

    def provider(row):
        key = row['id']
        # Never follow URLs supplied by the server, redirects, or credentials.
        path = '/info/openapi/' + key + '.json'
        raw, _ = reader(path)
        document = decode(raw)
        expected = row.get('facts_hash')
        require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected) and
                document.get('info', {}).get('x-aisa-document', {}).get('facts_hash') == expected,
                'Dev provider facts differ from index: ' + key)
        repeated, _ = reader(path)
        require(raw == repeated, 'Dev provider changed during acquisition: ' + key)
        return key + '.json', raw

    with ThreadPoolExecutor(max_workers=4) as pool:
        files = dict(pool.map(provider, providers))
    require(sum(map(len, files.values())) <= 64 << 20, 'Dev snapshot exceeds byte limit')
    after, _ = reader('/info/openapi.json')
    category_after, _ = reader('/info/apis/category')
    require(before == after and category_content(category) == category_content(category_after),
            'Dev Runtime index or category changed during acquisition')
    files.update({'index.json': before, 'category.json': category})
    return files


def dev_urls(text, source='dev'):
    # Switch only the known first-party API/console origins when previewing
    # another source; schema links always point to this dev documentation build.
    if source == 'production':
        text = text.replace(DEV_ORIGIN, PROD_ORIGIN).replace('https://dev-console.aisa.one', 'https://console.aisa.one')
    else:
        text = text.replace(PROD_ORIGIN, DEV_ORIGIN).replace('https://console.aisa.one', 'https://dev-console.aisa.one')
    return (text
            .replace('https://aisa.one/docs/openapi/',
                     'https://raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi/')
            .replace('https://aisa.one/openapi.yaml',
                     'https://raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi.yaml')
            .replace('https://aisa.one/openapi.json',
                     'https://raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi/openapi.json')
            .replace('https://aisa.one/docs/api-reference/', '/api-reference/')
            .replace('https://aisa.one/docs/zh/api-reference/', '/zh/api-reference/'))


def snapshot_hashes(files):
    """Ignore only the catalog cache timestamp when detecting Runtime changes."""
    return {name: sha(category_content(raw) if name == 'category.json' else raw)
            for name, raw in sorted(files.items())}


def inputs_sha256(files):
    return sha(json.dumps(snapshot_hashes(files), sort_keys=True, separators=(',', ':')).encode())


def generate(root, files, *, source='dev', source_release=None):
    """Stage with the existing Composer/page generator; never mutate input files."""
    origin = source_origin(source)
    previous_navigation = json.loads((root / 'docs.json').read_text()).get('navigation', {})
    with tempfile.TemporaryDirectory(prefix='dev-docs-') as folder:
        candidate = Path(folder) / 'site'
        shutil.copytree(root, candidate, ignore=shutil.ignore_patterns('.git', '.cache', 'node_modules', '__pycache__'))
        facts = Path(folder) / 'facts'
        facts.mkdir()
        for name, raw in files.items():
            (facts / name).write_bytes(raw)
        # Only dev-indexed catalogs may be composed. Retain existing source/group
        # configuration when its whole group exists in this dev snapshot.
        ids = {row['id'] for row in decode(files['index.json'])['providers']}
        registry_path = candidate / 'openapi/registry.yaml'
        registry = yaml.safe_load(registry_path.read_text())
        retained_registry = yaml.safe_load(registry_path.read_text())
        registry['providers'] = {key: value for key, value in registry['providers'].items()
            if set((value or {}).get('group', [key])) <= ids}
        registry_path.write_text(yaml.safe_dump(registry, sort_keys=False, allow_unicode=True))
        context = {'offline': True}
        history = published_history(root)
        changes, summary = stage(candidate, facts, origin, True, context,
                                 identity_history=history, reuse_unchanged_documents=False)
        blocked = [key for key, value in summary.items() if value.get('blocked')]
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        pending_path = candidate / 'openapi/pending.json'
        pending = json.loads(pending_path.read_text())
        pending['providers'] = {key: value for key, value in pending['providers'].items() if key in summary}
        pending_path.write_text(json.dumps(pending, indent=2, ensure_ascii=False, sort_keys=True) + '\n')
        config_path = candidate / 'docs.json'
        config = json.loads(config_path.read_text())
        config['navigation'] = preserve_navigation(previous_navigation, config.get('navigation', {}))
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n')
        # The platform index lists every platform group, including new ones.
        write_index_pages(candidate)
        aggregate = build_unified_spec(root=candidate)
        presentation = scope_presentation(candidate, aggregate, summary, source=source)
        inject_x402_annotations(aggregate)
        remove_v2_path_mirrors(aggregate)
        (candidate / 'openapi/openapi.json').write_text(json.dumps(aggregate, ensure_ascii=False, separators=(',', ':')) + '\n')
        (candidate / 'openapi.yaml').write_text(publication_yaml(aggregate))
        outputs = {}
        paths = [candidate / 'docs.json', candidate / 'openapi.yaml']
        paths += list((candidate / 'openapi').glob('*.json'))
        paths += list((candidate / 'openapi/zh').glob('*.json'))
        paths += list(candidate.rglob('*.mdx'))
        for path in paths:
            name = path.relative_to(candidate).as_posix()
            if name.startswith(('scripts/', 'snippets/', 'zh/snippets/')):
                continue
            outputs[name] = dev_urls(path.read_text(), source).encode()
        # Scope acquisition/composition in the private candidate while keeping
        # reviewed source configuration for history and future dev catalogs.
        retained_registry['providers'].update(yaml.safe_load(registry_path.read_text())['providers'])
        outputs['openapi/registry.yaml'] = yaml.safe_dump(
            retained_registry, sort_keys=False, allow_unicode=True).encode()
        report = {'schema_version': 1, 'environment': 'dev', 'runtime_origin': origin,
                  'source_environment': source, 'source_release': source_release,
                  'kind': 'production_release_preview' if source == 'production' else 'live_facts_preview',
                  'formal_publication': False,
                  'status': 'partial' if blocked or any(pending['providers'].values()) else 'generated',
                  'blocked_providers': blocked, **presentation,
                  'inputs_sha256': inputs_sha256(files),
                  'snapshot_sha256': snapshot_hashes(files),
                  'providers': {key: {field: value for field, value in row.items() if field != 'changed'}
                                for key, row in summary.items()},
                  'pending': pending}
        # No observation timestamp in committed bytes: unchanged inputs do not
        # create a new commit on each run. The run artifact records observation.
        outputs['docs/dev-runtime.json'] = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode()
        return outputs, report


def sync(root, *, write=False, if_changed=False, reader=None, source='dev'):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=root, text=True).strip()
    require(branch == 'dev', 'Dev Runtime sync requires the dev branch')
    origin = source_origin(source)
    reader = reader or PublicReader(origin, time.monotonic() + ACQUISITION_SECONDS)
    files, source_release = acquire_production(reader) if source == 'production' else (acquire(reader), None)
    print('Acquired verified ' + source + ' Runtime facts: ' + str(len(files) - 2) + ' providers', flush=True)
    previous_path = root / 'docs/dev-runtime.json'
    if if_changed and previous_path.exists():
        previous = json.loads(previous_path.read_text())
        if (previous.get('environment') == 'dev' and previous.get('runtime_origin') == origin
                and previous.get('source_release') == source_release
                and previous.get('formal_publication') is False
                and previous.get('status') in {'generated', 'partial'}
                and previous.get('inputs_sha256') == inputs_sha256(files)):
            return {**previous, 'generation_status': previous['status'], 'status': 'unchanged',
                    'observed_at': datetime.now(timezone.utc).isoformat(),
                    'written': False, 'changed_files': []}
    # Private diagnostic inputs. The CLI never reuses these as fresh evidence.
    cache = root / '.cache/dev-runtime-inputs'
    cache.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        (cache / name).write_bytes(raw)
    outputs, report = generate(root, files, source=source, source_release=source_release)
    changed = {name: raw for name, raw in outputs.items()
               if not (root / name).exists() or (root / name).read_bytes() != raw}
    # Reuse presentation validation against a complete private candidate before
    # applying any generated files to the checkout.
    with tempfile.TemporaryDirectory(prefix='dev-docs-check-') as folder:
        candidate = Path(folder) / 'site'
        shutil.copytree(root, candidate, ignore=shutil.ignore_patterns('.git', '.cache', 'node_modules', '__pycache__'))
        for name, raw in outputs.items():
            target = candidate / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        subprocess.run([sys.executable, str(root / 'scripts/check_nav_integrity.py'), '--root', str(candidate)], check=True)
        subprocess.run([sys.executable, str(root / 'scripts/validate_runtime_api_reference_slugs.py'),
                        '--root', str(candidate), '--generated-only'], check=True)
    if write:
        for name, raw in changed.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return {**report, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'written': write, 'changed_files': sorted(changed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--source', choices=('dev', 'production'), default='dev',
                        help='API contract source; output and publication always remain on dev')
    parser.add_argument('--if-changed', action='store_true',
                        help='Skip generation when verified dev Runtime inputs are unchanged')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = sync(args.root, write=args.write, if_changed=args.if_changed, source=args.source)
        result = 0
    except Exception as exc:
        report = {'environment': 'dev', 'runtime_origin': source_origin(args.source),
                  'status': 'failed', 'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
        result = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: report[key] for key in ('environment', 'status', 'error') if key in report}))
    return result


if __name__ == '__main__':
    raise SystemExit(main())
