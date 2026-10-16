"""Export original schema inputs from a fixed, independently reviewed Git tree.

No network, Runtime snapshot, current price calculation, or receipt renewal is
performed. Git ancestry is checked here, not authenticated by the offline reader.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml

from identity_compatibility import PublishedHistory
from presentation_page_bindings import MEMBER as PRESENTATION_MEMBER, export_bindings
from schema_input_bundle import (AUTHORITY, HEX40, REVIEWED_BASELINE, SINGLETONS, MAX_FILE,
                                 INPUT_CONTEXT_PATH, INPUT_RECEIPTS_PATH, INPUT_CONTEXT_MEMBER,
                                 INPUT_ROLES, reviewed_context,
                                 regular_read, formal_input_paths,
                                 canonical, require, role_for, safe_name, sha, UniqueLoader,
                                 reject_unimplemented_inputs,
                                 strict_json, validate_bundle)


class GitSource:
    def __init__(self, root, ref):
        self.root, self.ref = Path(root), ref
        require(isinstance(ref, str) and HEX40.fullmatch(ref), 'A full immutable Docs SHA is required')
        actual = self.git('rev-parse', '--verify', ref + '^{commit}').strip().decode()
        require(actual == ref, 'Docs ref is not an exact commit')
        self.trees = {}

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.PIPE)

    def ancestor(self, ref):
        require(isinstance(ref, str) and HEX40.fullmatch(ref), 'Invalid ancestry ref')
        require(subprocess.run(['git', 'merge-base', '--is-ancestor', ref, self.ref],
                               cwd=self.root, capture_output=True).returncode == 0,
                'Input ref is not an ancestor of the frozen Docs source')

    def read(self, ref, name):
        safe_name(name)
        if ref not in self.trees:
            entries = {}
            for row in self.git('ls-tree', '-rz', ref).split(b'\0'):
                if row:
                    metadata, path = row.split(b'\t', 1)
                    entries[path.decode()] = metadata.split()
            self.trees[ref] = entries
        metadata = self.trees[ref].get(name)
        require(metadata and metadata[0] in (b'100644', b'100755') and metadata[1] == b'blob',
                'Missing or non-regular Git input: ' + name)
        require(int(self.git('cat-file', '-s', metadata[2].decode())) <= MAX_FILE,
                'Git input exceeds member size limit')
        return self.git('cat-file', 'blob', metadata[2].decode())


def export_bundle(repo, docs_ref, baseline_ref, source_receipts, output, *, bundle_version=1):
    require(type(bundle_version) is int and bundle_version in (1, 2), 'Unsupported bundle version')
    require(baseline_ref == REVIEWED_BASELINE and docs_ref != baseline_ref,
            'An independent, code-pinned reviewed baseline is required')
    source = GitSource(repo, docs_ref)
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'Output must not already exist')
    require(output.parent.is_dir(), 'Output parent must exist')
    pointer_raw = source.read(docs_ref, 'docs/publication/current.json')
    pointer = strict_json(pointer_raw)
    registry = yaml.load(source.read(docs_ref, 'openapi/registry.yaml'), Loader=UniqueLoader)
    require(INPUT_CONTEXT_PATH not in source.trees[docs_ref], 'Reviewed input refs require bundle v3')
    reject_unimplemented_inputs(registry, pointer_paths=source.trees[docs_ref])
    files = {}
    for name in formal_input_paths(pointer['files_sha256']):
        files['input/' + name] = source.read(docs_ref, name)
    for member in SINGLETONS:
        if member.startswith('input/'):
            files[member] = source.read(docs_ref, member.removeprefix('input/'))
    files['baseline/openapi/coverage.json'] = source.read(baseline_ref, 'openapi/coverage.json')
    receipt_path = Path(source_receipts)
    require(receipt_path.is_file() and not receipt_path.is_symlink(), 'Original receipt file is required')
    files['evidence/source-receipts.json'] = regular_read(receipt_path.parent, receipt_path.name)
    history = PublishedHistory(repo, docs_ref).collect()
    files['identity/aliases.json'] = canonical({'canonical_ids': sorted(history.canonical_ids),
                                               'aliases': history.aliases})
    ancestors = set()
    for proofs in history.aliases.values():
        for proof in proofs:
            ref = proof['published_ref']
            source.ancestor(ref)
            ancestors.add(ref)
            for key in ('source_file', 'canonical_source_file'):
                name = proof[key]
                files['proofs/' + ref + '/' + name] = source.read(ref, name)
    files['evidence/git-validation.json'] = canonical({
        'kind': 'exporter_checked_git_ancestry_not_offline_authentication',
        'docs_ref': docs_ref, 'ancestors': sorted(ancestors),
        'independently_pinned_baseline': {'ref': baseline_ref, 'path': 'openapi/coverage.json',
            'sha256': sha(files['baseline/openapi/coverage.json'])}})
    if bundle_version == 2:
        documents = {Path(name).stem: strict_json(raw) for name, raw in files.items()
                     if role_for(name) == 'historical_compatibility_document'}
        files[PRESENTATION_MEMBER] = canonical(export_bindings(
            docs_ref, pointer['files_sha256'], documents,
            lambda name: source.read(docs_ref, name), sha))
    manifest = {'schema_version': bundle_version, 'kind': 'aisa-schema-input-bundle',
                'docs_ref': docs_ref, 'baseline_ref': baseline_ref, 'authority': AUTHORITY,
                'files': [{'path': name, 'role': role_for(name), 'sha256': sha(raw), 'bytes': len(raw)}
                          for name, raw in sorted(files.items())]}
    return write_bundle(files, manifest, output)


def write_bundle(files, manifest, output):
    """One atomic output path shared by historical and reviewed input exports."""
    output = Path(output)
    manifest_raw = canonical(manifest)
    temporary = Path(tempfile.mkdtemp(prefix='.schema-bundle-', dir=output.parent))
    try:
        for name, raw in {**files, 'manifest.json': manifest_raw}.items():
            target = temporary / safe_name(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        result = validate_bundle(temporary, expected_manifest_sha256=sha(manifest_raw),
                                 expected_docs_ref=manifest['docs_ref'],
                                 expected_baseline_ref=manifest['baseline_ref'])
        # No overwrite: callers must name a new artifact destination.
        require(not output.exists() and not output.is_symlink(), 'Output appeared during export')
        temporary.rename(output)
        return result
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def export_reviewed_bundle(repo, docs_ref, output):
    """Rebuild a non-formal input candidate from independently pinned Git bytes.

    No Actions API, current Runtime, source acquisition, review, or clock renewal
    occurs. The caller's reviewed build lock must authorize the returned digest.
    """
    source = GitSource(repo, docs_ref)
    output = Path(output)
    require(output.parent.is_dir() and not output.exists() and not output.is_symlink(),
            'Output must be a new directory with an existing parent')
    recipe_raw = source.read(docs_ref, INPUT_CONTEXT_PATH)
    recipe = reviewed_context(recipe_raw)
    history_ref = recipe['historical_formal_ref']
    source.ancestor(history_ref)
    require(history_ref != docs_ref, 'Reviewed input must be distinct from historical context')
    source.ancestor(docs_ref)
    pointer_raw = source.read(history_ref, 'docs/publication/current.json')
    pointer = strict_json(pointer_raw)
    registry_raw = source.read(docs_ref, 'openapi/registry.yaml')
    registry = yaml.load(registry_raw, Loader=UniqueLoader)
    reject_unimplemented_inputs(registry, pointer_paths=source.trees[docs_ref])
    files = {}
    # Current source authority comes only from R, not from F's formal pointer.
    for name in formal_input_paths(source.trees[docs_ref]):
        if role_for('input/' + name) in INPUT_ROLES:
            files['input/' + name] = source.read(docs_ref, name)
    # Native compatibility, old gaps, pages and identity history stay bound to F.
    for name in formal_input_paths(pointer['files_sha256']):
        if role_for('input/' + name) not in INPUT_ROLES:
            raw = source.read(history_ref, name)
            require(sha(raw) == pointer['files_sha256'][name], 'Historical context input differs')
            files['input/' + name] = raw
    for member in SINGLETONS:
        if member.startswith('input/') and role_for(member) not in INPUT_ROLES:
            files[member] = source.read(history_ref, member.removeprefix('input/'))
    files['baseline/openapi/coverage.json'] = source.read(REVIEWED_BASELINE, 'openapi/coverage.json')
    files['evidence/source-receipts.json'] = source.read(docs_ref, INPUT_RECEIPTS_PATH)
    require(sha(files['evidence/source-receipts.json']) == recipe['source_receipts_sha256'],
            'Reviewed input receipt bytes differ')
    files[INPUT_CONTEXT_MEMBER] = recipe_raw
    history = PublishedHistory(repo, history_ref).collect()
    files['identity/aliases.json'] = canonical({'canonical_ids': sorted(history.canonical_ids),
                                               'aliases': history.aliases})
    ancestors = set()
    for proofs in history.aliases.values():
        for proof in proofs:
            ref = proof['published_ref']
            source.ancestor(ref)
            ancestors.add(ref)
            for key in ('source_file', 'canonical_source_file'):
                name = proof[key]
                files['proofs/' + ref + '/' + name] = source.read(ref, name)
    files['evidence/git-validation.json'] = canonical({
        'kind': 'exporter_checked_git_ancestry_not_offline_authentication',
        'docs_ref': docs_ref, 'historical_formal_ref': history_ref, 'ancestors': sorted(ancestors),
        'input_files_sha256': {name.removeprefix('input/'): sha(raw) for name, raw in files.items()
                              if role_for(name) in INPUT_ROLES},
        'independently_pinned_baseline': {'ref': REVIEWED_BASELINE, 'path': 'openapi/coverage.json',
            'sha256': sha(files['baseline/openapi/coverage.json'])}})
    documents = {Path(name).stem: strict_json(raw) for name, raw in files.items()
                 if role_for(name) == 'historical_compatibility_document'}
    files[PRESENTATION_MEMBER] = canonical(export_bindings(history_ref, pointer['files_sha256'], documents,
        lambda name: source.read(history_ref, name), sha))
    manifest = {'schema_version': 3, 'kind': 'aisa-schema-input-bundle', 'docs_ref': docs_ref,
        'baseline_ref': REVIEWED_BASELINE, 'authority': AUTHORITY,
        'context': {'historical_formal_ref': history_ref},
        'files': [{'path': name, 'role': role_for(name), 'sha256': sha(raw), 'bytes': len(raw)}
                  for name, raw in sorted(files.items())]}
    return write_bundle(files, manifest, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--docs-ref', required=True)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--source-receipts', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bundle-version', type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    try:
        require(args.baseline_ref == REVIEWED_BASELINE, 'Independent reviewed baseline differs')
        if args.bundle_version == 3:
            require(args.source_receipts is None, 'Reviewed Git input receipts cannot be overridden')
            result = export_reviewed_bundle(args.repo, args.docs_ref, args.output)
        else:
            require(args.source_receipts is not None, 'Original receipt file is required')
            result = export_bundle(args.repo, args.docs_ref, args.baseline_ref, args.source_receipts, args.output,
                                   bundle_version=args.bundle_version)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, 'Schema input export rejected: ' + str(exc) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
