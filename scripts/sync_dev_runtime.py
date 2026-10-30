"""Generate dev documentation from a stable public dev Runtime facts snapshot.

This is a dev preview consumer, independent of production formal publication.
It never acquires production inputs, approves source receipts, or notifies consumers.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
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
from pull_openapi import stage, update_disabled_indexing
from identity_compatibility import published_history
from runtime_consolidate_openapi import (build_unified_spec, publication_yaml,
                                        inject_x402_annotations, remove_v2_path_mirrors)


DEV_ORIGIN = 'https://dev-api.aisa.one'
ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(r'[a-z0-9][a-z0-9_.-]*')
ARCHIVE_NOTE = '<Warning>This endpoint is unavailable in the current dev Runtime contract snapshot.</Warning>\n\n'


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


def scope_presentation(candidate, aggregate, summary):
    """Keep historic files/identities, but advertise only composed dev contracts."""
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
    aggregate['info']['x-aisa-environment'] = 'dev'
    aggregate['info']['x-aisa-publication-kind'] = 'live_facts_preview'
    documents = {}
    hidden = set()
    for base in ('api-reference', 'zh/api-reference'):
        for page in (candidate / base).rglob('*.mdx'):
            text = page.read_text()
            match = re.search(r"^openapi:\s*['\"]?(openapi/[^\s'\"]+\.json)\s+(\w+)\s+([^\s'\"]+)", text, re.M)
            if not match:
                continue
            name, method, path = match.groups()
            if name not in documents:
                documents[name] = json.loads((candidate / name).read_text())
            provider = Path(name).name.removesuffix('.json').removesuffix('.zh')
            operation = documents[name].get('paths', {}).get(path, {}).get(method.lower())
            disabled = provider not in active or operation is None or operation.get('x-aisa-status') == 'disabled'
            text = update_disabled_indexing(text, disabled).replace(ARCHIVE_NOTE, '')
            if disabled:
                hidden.add(page.relative_to(candidate).with_suffix('').as_posix())
                # Put the notice after frontmatter, preserving endpoint identity.
                end = text.index('\n---\n', 4) + 5
                text = text[:end] + ARCHIVE_NOTE + text[end:]
            page.write_text(text)

    config_path = candidate / 'docs.json'
    config = json.loads(config_path.read_text())
    config['navigation'] = prune_navigation(config.get('navigation', {}), hidden)
    config['name'] = 'AIsa Dev'
    config.setdefault('markdown', {})['instructions'] = (
        '- Environment: dev. Use a dev API key with `Authorization: Bearer $AISA_API_KEY`.\n'
        '- API base: `https://dev-api.aisa.one/apis/v1`. Follow each operation\'s servers.\n'
        '- Dev OpenAPI: https://raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi.yaml.\n'
        '- Call only operations present in the dev contract. Do not make paid calls to test availability.\n'
        '- Never print, log, or commit API keys.'
    )
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n')
    return len(hidden)


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


def dev_urls(text):
    return (text.replace('https://api.aisa.one', DEV_ORIGIN)
            .replace('https://console.aisa.one', 'https://dev-console.aisa.one')
            .replace('https://aisa.one/docs/openapi/',
                     'https://raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi/')
            .replace('https://aisa.one/openapi.yaml',
                     'https://raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi.yaml')
            .replace('https://aisa.one/openapi.json',
                     'https://raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi/openapi.json')
            .replace('https://aisa.one/docs/api-reference/', '/api-reference/')
            .replace('https://aisa.one/docs/zh/api-reference/', '/zh/api-reference/'))


def generate(root, files):
    """Stage with the existing Composer/page generator; never mutate input files."""
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
        changes, summary = stage(candidate, facts, DEV_ORIGIN, True, context,
                                 identity_history=history, reuse_unchanged_documents=False)
        blocked = [key for key, value in summary.items() if value.get('blocked')]
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        pending_path = candidate / 'openapi/pending.json'
        pending = json.loads(pending_path.read_text())
        pending['providers'] = {key: value for key, value in pending['providers'].items() if key in summary}
        pending_path.write_text(json.dumps(pending, indent=2, ensure_ascii=False, sort_keys=True) + '\n')
        aggregate = build_unified_spec(root=candidate)
        hidden = scope_presentation(candidate, aggregate, summary)
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
            outputs[name] = dev_urls(path.read_text()).encode()
        # Scope acquisition/composition in the private candidate while keeping
        # reviewed source configuration for history and future dev catalogs.
        retained_registry['providers'].update(yaml.safe_load(registry_path.read_text())['providers'])
        outputs['openapi/registry.yaml'] = yaml.safe_dump(
            retained_registry, sort_keys=False, allow_unicode=True).encode()
        report = {'schema_version': 1, 'environment': 'dev', 'runtime_origin': DEV_ORIGIN,
                  'kind': 'live_facts_preview', 'formal_publication': False,
                  'status': 'partial' if blocked or any(pending['providers'].values()) else 'generated',
                  'blocked_providers': blocked, 'hidden_historic_pages': hidden,
                  'snapshot_sha256': {name: sha(raw) for name, raw in sorted(files.items())},
                  'providers': {key: {field: value for field, value in row.items() if field != 'changed'}
                                for key, row in summary.items()},
                  'pending': pending}
        # No observation timestamp in committed bytes: unchanged inputs do not
        # create a new commit on each run. The run artifact records observation.
        outputs['docs/dev-runtime.json'] = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode()
        return outputs, report


def sync(root, *, write=False, reader=None):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=root, text=True).strip()
    require(branch == 'dev', 'Dev Runtime sync requires the dev branch')
    reader = reader or PublicReader(DEV_ORIGIN, time.monotonic() + 600)
    files = acquire(reader)
    print('Acquired stable dev Runtime facts: ' + str(len(files) - 2) + ' providers', flush=True)
    # Private diagnostic inputs. The CLI never reuses these as fresh evidence.
    cache = root / '.cache/dev-runtime-inputs'
    cache.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        (cache / name).write_bytes(raw)
    outputs, report = generate(root, files)
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
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = sync(args.root, write=args.write)
        result = 0
    except Exception as exc:
        report = {'environment': 'dev', 'runtime_origin': DEV_ORIGIN,
                  'status': 'failed', 'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
        result = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: report[key] for key in ('environment', 'status', 'error') if key in report}))
    return result


if __name__ == '__main__':
    raise SystemExit(main())
