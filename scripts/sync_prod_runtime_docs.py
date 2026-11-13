"""Generate production reference pages from a pinned Runtime facts snapshot.

Adapted from dev sync_dev_runtime.py at 61be6bbce8f3f3b535334029097cb1d6f41dc1be.
Reuse Composer/page generation and honest partial presentation without replacing
formal machine exports, approving source receipts or notifying consumers.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

from fetch_runtime_release import decode, require, sha, category_content
from pull_openapi import stage, update_disabled_indexing
from check_nav_integrity import nav_pages
from identity_compatibility import published_history
from internal_publication_snapshot import load_snapshot
from validate_prod_reference_pages import validate_reference_pages
from readable_contract_notes import clean_reference_notices


PROD_ORIGIN = 'https://api.aisa.one'
REFERENCE_DIR = 'reference-contracts'
ROOT = Path(__file__).resolve().parents[1]


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


def scope_presentation(candidate, summary):
    """Preserve reference navigation and report incomplete catalog coverage."""
    config_path = candidate / 'docs.json'
    config = json.loads(config_path.read_text())
    listed = set(nav_pages(config.get('navigation', {})))
    active = {key for key, value in summary.items() if not value.get('blocked')}
    documents = {}
    hidden, preserved = set(), set()
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
            unverified = provider not in active or operation is None or operation.get('x-aisa-status') == 'disabled'
            reference = page.relative_to(candidate).with_suffix('').as_posix()
            unlisted = unverified and reference not in listed
            text = update_disabled_indexing(text, unlisted)
            text = clean_reference_notices(text)
            if unverified:
                if unlisted:
                    hidden.add(reference)
                else:
                    preserved.add(reference)
            page.write_text(text)

    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n')
    return {'preserved_historic_pages': len(preserved), 'hidden_historic_pages': len(hidden)}


def reference_text(text):
    """Move provider schema links while preserving formal aggregate identities."""
    text = re.sub(r'https://aisa\.one/docs/openapi/((?:zh/)?[A-Za-z0-9_.-]+\.json)',
                  lambda m: m[0] if m[1] == 'openapi.json' else
                  'https://aisa.one/docs/' + REFERENCE_DIR + '/' + m[1], text)
    return re.sub(r'(?<![A-Za-z0-9_:/.-])openapi/(zh/)?([A-Za-z0-9_.-]+\.json)',
                  lambda m: m[0] if not m[1] and m[2] == 'openapi.json' else
                  REFERENCE_DIR + '/' + (m[1] or '') + m[2], text)


def publication_outputs(outputs):
    """Keep formal exports and receipts outside this page producer's write set."""
    selected = {}
    for name, raw in outputs.items():
        if name == 'docs.json' or name.startswith(('api-reference/', 'zh/api-reference/')) and name.endswith('.mdx'):
            selected[name] = reference_text(raw.decode()).encode()
        elif name != 'openapi/openapi.json' and re.fullmatch(r'openapi/(?:zh/)?[A-Za-z0-9_.-]+\.json', name):
            document = json.loads(raw)
            if isinstance(document,dict) and 'openapi' in document and 'paths' in document:
                selected[REFERENCE_DIR + '/' + name.removeprefix('openapi/')] = raw
        elif name == 'docs/prod-runtime.json':
            selected[name] = raw
    return selected



def restore_reference_history(candidate):
    """Use the previous reference release as history inside the private workspace."""
    for path in (candidate / REFERENCE_DIR).rglob('*.json'):
        relative = path.relative_to(candidate / REFERENCE_DIR).as_posix()
        require(re.fullmatch(r'(?:zh/)?[A-Za-z0-9_.-]+\.json', relative),
                'Unsafe prior reference schema path')
        document = json.loads(path.read_text())
        require(isinstance(document, dict) and 'openapi' in document and 'paths' in document,
                'Prior reference schema is not an OpenAPI document')
        target = candidate / 'openapi' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    for prefix in ('api-reference', 'zh/api-reference'):
        for page in (candidate / prefix).rglob('*.mdx'):
            text = page.read_text()
            restored = re.sub(r'(?<![A-Za-z0-9_:/.-])reference-contracts/(zh/)?([A-Za-z0-9_.-]+\.json)',
                              lambda m: 'openapi/' + (m[1] or '') + m[2], text)
            if restored != text:
                page.write_text(restored)



def snapshot_hashes(files):
    """Ignore only the catalog cache timestamp when detecting Runtime changes."""
    return {name: sha(category_content(raw) if name == 'category.json' else raw)
            for name, raw in sorted(files.items())}


def inputs_sha256(files):
    return sha(json.dumps(snapshot_hashes(files), sort_keys=True, separators=(',', ':')).encode())


def generate(root, files):
    """Stage with the existing Composer/page generator; never mutate input files."""
    previous_navigation = json.loads((root / 'docs.json').read_text()).get('navigation', {})
    with tempfile.TemporaryDirectory(prefix='prod-reference-') as folder:
        candidate = Path(folder) / 'site'
        shutil.copytree(root, candidate, ignore=shutil.ignore_patterns('.git', '.cache', 'node_modules', '__pycache__'))
        restore_reference_history(candidate)
        facts = Path(folder) / 'facts'
        facts.mkdir()
        for name, raw in files.items():
            (facts / name).write_bytes(raw)
        # Only snapshot-indexed catalogs may be composed. Retain existing source/group
        # configuration when its whole group exists in this snapshot.
        ids = {row['id'] for row in decode(files['index.json'])['providers']}
        registry_path = candidate / 'openapi/registry.yaml'
        registry = yaml.safe_load(registry_path.read_text())
        retained_registry = yaml.safe_load(registry_path.read_text())
        registry['providers'] = {key: value for key, value in registry['providers'].items()
            if set((value or {}).get('group', [key])) <= ids}
        registry_path.write_text(yaml.safe_dump(registry, sort_keys=False, allow_unicode=True))
        context = {'offline': True}
        history = published_history(root)
        changes, summary = stage(candidate, facts, PROD_ORIGIN, True, context,
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
        presentation = scope_presentation(candidate, summary)
        # Navigation preservation must not restore editorially retired routes.
        from human_api_retirements import apply_retirements
        retirement_changes = {}
        apply_retirements(candidate, retirement_changes)
        for path, text in retirement_changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        outputs = {}
        paths = [candidate / 'docs.json']
        paths += list((candidate / 'openapi').glob('*.json'))
        paths += list((candidate / 'openapi/zh').glob('*.json'))
        paths += list(candidate.rglob('*.mdx'))
        for path in paths:
            name = path.relative_to(candidate).as_posix()
            if name.startswith(('scripts/', 'snippets/', 'zh/snippets/')):
                continue
            outputs[name] = path.read_bytes()
        # Scope acquisition/composition in the private candidate while keeping
        # reviewed source configuration for history and future catalogs.
        retained_registry['providers'].update(yaml.safe_load(registry_path.read_text())['providers'])
        outputs['openapi/registry.yaml'] = yaml.safe_dump(
            retained_registry, sort_keys=False, allow_unicode=True).encode()
        report = {'schema_version': 1, 'environment': 'prod', 'runtime_origin': PROD_ORIGIN,
                  'kind': 'production_facts_reference', 'formal_publication': False,
                  'status': 'partial' if blocked or any(pending['providers'].values()) else 'generated',
                  'blocked_providers': blocked, **presentation,
                  'inputs_sha256': inputs_sha256(files),
                  'snapshot_sha256': snapshot_hashes(files),
                  'providers': {key: {field: value for field, value in row.items() if field != 'changed'}
                                for key, row in summary.items()},
                  'pending': pending}
        # No observation timestamp in committed bytes: unchanged inputs do not
        # create a new commit on each run. The run artifact records observation.
        outputs['docs/prod-runtime.json'] = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode()
        return publication_outputs(outputs), report


def read_acquisition_receipt(path, *, snapshot_sha256, generation, source_digest, compiler_revision):
    """Attach the operator-verified export observation without upgrading its scope."""
    require(path.stat().st_size <= 65536, 'Acquisition receipt is too large')
    record = json.loads(path.read_text())
    require(isinstance(record, dict), 'Acquisition receipt must be an object')
    for key, expected in {'snapshot_sha256': snapshot_sha256, 'generation': generation,
                          'source_digest': source_digest, 'compiler_revision': compiler_revision,
                          'environment': 'prod', 'formal_publication': False,
                          'kind': 'verified_private_runtime_export'}.items():
        require(record.get(key) == expected, 'Acquisition receipt differs: ' + key)
    allowed = {'schema_version', 'environment', 'kind', 'formal_publication',
               'snapshot_sha256', 'generation', 'source_digest', 'compiler_revision',
               'repository', 'workflow', 'run_id', 'run_attempt', 'run_url', 'infra_source',
               'build_window_utc', 'transport_artifact_sha256', 'files', 'qualification',
               'SQL_mutations', 'Kubernetes_mutations', 'provider_credentials_exported'}
    require(set(record) <= allowed, 'Unexpected acquisition receipt fields')
    return record


def sync(root, *, snapshot_dir, snapshot_sha256, generation, source_digest,
         compiler_revision, write=False, acquisition_receipt=None):
    # Private inputs are pinned independently by the operator/export receipt.
    # Production's /info/openapi currently serves the old formal publication;
    # reading it here would falsely present historical facts as current.
    files, binding = load_snapshot(snapshot_dir, snapshot_sha256=snapshot_sha256,
        generation=generation, source_digest=source_digest, compiler_revision=compiler_revision)
    acquisition = read_acquisition_receipt(acquisition_receipt, snapshot_sha256=snapshot_sha256,
        generation=generation, source_digest=source_digest, compiler_revision=compiler_revision) if acquisition_receipt else None
    outputs, report = generate(root, files)
    report['source'] = binding
    if acquisition is not None:
        report['acquisition'] = acquisition
    report['kind'] = 'production_facts_reference'
    report['formal_publication'] = False
    report['formal_exports_modified'] = False
    outputs['docs/prod-runtime.json'] = (json.dumps(report,indent=2,sort_keys=True)+'\n').encode()
    for name, raw in outputs.items():
        require(not any(origin.encode() in raw for origin in ('https://dev-api.aisa.one', 'https://dev-console.aisa.one', 'refs/heads/dev/openapi')),
                'Development environment reference in production output: ' + name)
    changed = {name:raw for name,raw in outputs.items()
               if not (root/name).exists() or (root/name).read_bytes()!=raw}
    with tempfile.TemporaryDirectory(prefix='prod-reference-check-') as folder:
        candidate=Path(folder)/'site'
        shutil.copytree(root,candidate,ignore=shutil.ignore_patterns('.git','.cache','node_modules','__pycache__'))
        for name,raw in outputs.items():
            target=candidate/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        checked=validate_reference_pages(candidate)
        require(checked > 0, 'No generated reference pages were validated')
        subprocess.run([sys.executable,str(root/'scripts/check_nav_integrity.py'),'--root',str(candidate)],check=True)
    if write:
        for name,raw in changed.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    return {**report,'validated_reference_pages':checked,'written':write,'changed_files':sorted(changed)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--snapshot-dir',type=Path,required=True)
    parser.add_argument('--snapshot-sha256',required=True)
    parser.add_argument('--generation',type=int,required=True)
    parser.add_argument('--source-digest',required=True)
    parser.add_argument('--compiler-revision',required=True)
    parser.add_argument('--acquisition-receipt',type=Path,help='Verified read-only export observation; independent from formal publication')
    parser.add_argument('--write',action='store_true')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    try:
        report=sync(args.root,snapshot_dir=args.snapshot_dir,snapshot_sha256=args.snapshot_sha256,
                    generation=args.generation,source_digest=args.source_digest,
                    compiler_revision=args.compiler_revision,write=args.write,acquisition_receipt=args.acquisition_receipt)
        result=0
    except Exception as exc:
        report={'environment':'prod','status':'failed','error_type':type(exc).__name__}
        result=1
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({key:report[key]for key in ('environment','status','error_type','validated_reference_pages')if key in report}))
    return result


if __name__=='__main__':
    raise SystemExit(main())
