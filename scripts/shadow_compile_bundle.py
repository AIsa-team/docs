"""Offline native-graph shadow compilation; never a formal publication receipt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from contract_page_links import historical_link_index, require_historical_primary_links
from fetch_runtime_release import (MAX_FILE, MAX_TOTAL, category_content,
                                   validate_current, validate_release_files)
from pull_openapi import stage
from runtime_registry import published_documents
from schema_input_bundle import (HEX40, HEX64, canonical, load_bundle, regular_read,
                                 require, sha, strict_json)


def load_runtime(root, *, artifact_revision, compiler_revision, receipt_sha256):
    """Verify a previously acquired snapshot against caller pins, without I/O to Runtime."""
    require(HEX64.fullmatch(artifact_revision) and HEX40.fullmatch(compiler_revision)
            and HEX64.fullmatch(receipt_sha256), 'Independent full Runtime pins are required')
    root = Path(root)
    receipt_raw = regular_read(root, 'acquisition-receipt.json')
    require(sha(receipt_raw) == receipt_sha256, 'Runtime receipt differs from caller pin')
    receipt = strict_json(receipt_raw)
    before = strict_json(regular_read(root, 'current-before.json'))
    after = strict_json(regular_read(root, 'current-after.json'))
    validate_current(before, artifact_revision, compiler_revision)
    validate_current(after, artifact_revision, compiler_revision)
    require(canonical(before) == canonical(after), 'Historical Runtime acquisition was not stable')
    require(type(receipt.get('schema_version')) is int and receipt['schema_version'] == 1 and
            receipt.get('fresh_before_and_after') is True, 'Unsupported original Runtime receipt')
    for field in ('artifact_revision', 'compiler_revision', 'source_digest', 'generation'):
        require(canonical(receipt.get(field)) == canonical(before[field]), 'Runtime receipt identity differs')
    require(canonical(receipt.get('manifest_files')) == canonical(before['files']),
            'Runtime receipt manifest differs')
    contents, total = {}, 0
    for row in before['files']:
        raw = regular_read(root, row['name'])
        total += len(raw)
        require(len(raw) <= MAX_FILE and total <= MAX_TOTAL, 'Runtime byte limit exceeded')
        require(sha(raw) == row['sha256'], 'Runtime member differs from immutable manifest')
        strict_json(raw)
        contents[row['name']] = raw
    validate_release_files(contents)
    category = regular_read(root, 'category.json')
    require(len(category) <= MAX_FILE and total + len(category) <= MAX_TOTAL,
            'Runtime category byte limit exceeded')
    require(sha(category) == receipt.get('category_sha256') and
            sha(category_content(category)) == receipt.get('category_content_sha256'),
            'Unversioned category differs from pinned original acquisition')
    facts = {Path(name).name: raw for name, raw in contents.items()}
    facts['category.json'] = category
    return facts, {'artifact_revision': artifact_revision, 'compiler_revision': compiler_revision,
                   'acquisition_receipt_sha256': receipt_sha256, 'generation': before['generation'],
                   'freshness': 'historical_acquisition_only_not_current_freshness'}


def compile_shadow(bundle_root, runtime_root, *, bundle_sha256, docs_ref,
                   artifact_revision, compiler_revision, runtime_receipt_sha256, output):
    """Compile through the existing Composer using only verified private inputs."""
    bundle = load_bundle(bundle_root, expected_manifest_sha256=bundle_sha256, expected_docs_ref=docs_ref)
    facts, runtime = load_runtime(runtime_root, artifact_revision=artifact_revision,
        compiler_revision=compiler_revision, receipt_sha256=runtime_receipt_sha256)
    output = Path(output)
    require(not output.exists() and not output.is_symlink() and output.parent.is_dir(),
            'Shadow output must be a new directory with an existing parent')
    with tempfile.TemporaryDirectory(prefix='offline-contract-shadow-') as folder:
        private = Path(folder)
        inputs, facts_dir = private / 'input', private / 'facts'
        facts_dir.mkdir()
        for name, raw in bundle.contents.items():
            if name.startswith('input/'):
                target = inputs / name.removeprefix('input/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        for name, raw in facts.items():
            (facts_dir / name).write_bytes(raw)
        original = published_documents(inputs)
        links = historical_link_index(original)
        context = {'offline': True,
                   'baseline_coverage': strict_json(bundle.contents['baseline/openapi/coverage.json'])}
        _, summary = stage(inputs, facts_dir, 'https://api.aisa.one', with_pages=False,
            readiness_context=context, identity_history=bundle.history, page_link_index=links,
            reuse_unchanged_documents=False)
        report = context['report']
        require(report['status'] == 'passed' and not report.get('global_errors') and
                not report.get('missing_inputs') and not report.get('blocked_providers') and
                not any(row.get('blocked') for row in summary.values()),
                'Offline native graph did not pass existing readiness gates')
        documents = context['documents']
        require_historical_primary_links(original, {name: documents[name] for name in summary})
        require(set(summary) <= set(context['recomposed_documents']) and set(original) <= set(documents),
                'Shadow did not independently compose every provider and retain the native graph')
        payload = {'native/' + name + '.json': canonical(document)
                   for name, document in sorted(documents.items())}
        payload['readiness.json'] = canonical(report)
        manifest = {'schema_version': 1, 'kind': 'aisa-offline-shadow-native-graph',
            'scope': 'existing_composer_offline_shadow_only_not_formal_publication',
            'bundle': bundle.validation, 'runtime': runtime,
            'pages_generated': False, 'aggregate_generated': False,
            'aggregate_gap': 'complete MDX page-reference inventory is not in schema bundle v1',
            'providers_recomposed': sorted(context['recomposed_documents']),
            'files': [{'path': name, 'sha256': sha(raw), 'bytes': len(raw)}
                      for name, raw in sorted(payload.items())]}
        payload['manifest.json'] = canonical(manifest)
        temporary = Path(tempfile.mkdtemp(prefix='.shadow-output-', dir=output.parent))
        try:
            for name, raw in payload.items():
                target = temporary / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            require(not output.exists() and not output.is_symlink(), 'Shadow destination appeared during compile')
            temporary.rename(output)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {'status': 'passed', 'scope': manifest['scope'], 'native_documents': len(documents),
            'providers_recomposed': len(context['recomposed_documents']),
            'manifest_sha256': sha(payload['manifest.json'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--bundle-sha256', required=True)
    parser.add_argument('--docs-ref', required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--artifact-revision', required=True)
    parser.add_argument('--compiler-revision', required=True)
    parser.add_argument('--runtime-receipt-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compile_shadow(args.bundle, args.runtime, bundle_sha256=args.bundle_sha256,
            docs_ref=args.docs_ref, artifact_revision=args.artifact_revision,
            compiler_revision=args.compiler_revision, runtime_receipt_sha256=args.runtime_receipt_sha256,
            output=args.output)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(1, 'Offline shadow rejected: ' + str(exc) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
