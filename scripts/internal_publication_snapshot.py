"""Offline shadow adapter for pinned, private PublicationSnapshot transport bytes.

This is integrity validation, not evidence that Go ValidatePublicationSnapshot
ran. A future trusted Go materializer must call that validator inside its own
function before exporting original Content bytes. No public receipt is created.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat

from fetch_runtime_release import MAX_FILE, MAX_TOTAL, validate_release_files
from schema_input_bundle import HEX40, HEX64, canonical, load_bundle, require, sha, strict_json
from shadow_compile_bundle import compile_verified_inputs

MAX_METADATA = 1 << 20
MAX_FILES = 512
FIELDS = {'schema_version', 'generation', 'source_digest', 'compiler_revision', 'files'}
MEMBER = re.compile(r'(?:index\.json|providers/[a-z0-9][a-z0-9_.-]{0,119}\.json)')


def bounded_read(root, name, limit):
    """Read once; only the resulting hash-verified bytes are later consumed."""
    path = root
    for part in name.split('/'):
        path = path / part
        require(not path.is_symlink(), 'Snapshot symlink is forbidden')
    require(stat.S_ISREG(path.stat(follow_symlinks=False).st_mode),
            'Snapshot member must be a regular file')
    # Nonblocking/open-no-follow also rejects a final-file FIFO/symlink race.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit,
                'Snapshot member is not a bounded regular file')
        raw = handle.read(limit + 1)
    require(0 < len(raw) <= limit, 'Snapshot byte limit exceeded')
    return raw


def exact_members(root, expected):
    found = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            path = Path(directory) / name
            require(not path.is_symlink() and path.relative_to(root).as_posix() == 'providers',
                    'Unexpected snapshot directory')
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            require(not path.is_symlink() and relative in expected and relative not in found,
                    'Unexpected snapshot member')
            found.add(relative)
    require(found == expected, 'Missing snapshot member')


def load_snapshot(root, *, snapshot_sha256, generation, source_digest, compiler_revision):
    """Check an externally pinned private envelope, without public current or receipts.

    The supported provider namespace intentionally matches the existing Docs
    public loader. This does not replace Go's full projected-field validation.
    """
    require(isinstance(snapshot_sha256, str) and HEX64.fullmatch(snapshot_sha256) and
            isinstance(source_digest, str) and HEX64.fullmatch(source_digest) and
            isinstance(compiler_revision, str) and HEX40.fullmatch(compiler_revision) and
            type(generation) is int and 0 <= generation < 1 << 64,
            'Independent full snapshot pins are required')
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'Snapshot root must be a real directory')
    raw = bounded_read(root, 'snapshot.json', MAX_METADATA)
    require(sha(raw) == snapshot_sha256, 'Snapshot envelope differs from caller pin')
    metadata = strict_json(raw)
    require(isinstance(metadata, dict) and set(metadata) == FIELDS and
            metadata['schema_version'] == '1', 'Unsupported private snapshot envelope')
    require(type(metadata['generation']) is int and metadata['generation'] == generation and
            metadata['source_digest'] == source_digest and metadata['compiler_revision'] == compiler_revision,
            'Snapshot identity differs from caller pins')
    rows = metadata['files']
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_FILES, 'Invalid snapshot member count')
    names = []
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'name', 'media_type', 'sha256'} and
                isinstance(row['name'], str) and MEMBER.fullmatch(row['name']) and
                row['media_type'] == 'application/json' and
                isinstance(row['sha256'], str) and HEX64.fullmatch(row['sha256']),
                'Unsupported snapshot member')
        names.append(row['name'])
    require(names == sorted(set(names)) and 'index.json' in names,
            'Snapshot members must be sorted, unique, and include index')
    exact_members(root, {'snapshot.json', *names})
    contents, total = {}, 0
    for row in rows:
        content = bounded_read(root, row['name'], MAX_FILE)
        total += len(content)
        require(total <= MAX_TOTAL, 'Snapshot total byte limit exceeded')
        require(sha(content) == row['sha256'], 'Snapshot member differs from original Content hash')
        value = strict_json(content)
        require(isinstance(value, dict), 'Snapshot JSON document must be an object')
        contents[row['name']] = content
    try:
        _, providers, _ = validate_release_files(contents)
    except (AttributeError, KeyError, TypeError):
        raise ValueError('Invalid closed snapshot graph structure') from None
    # Discovery only: these IDs are already closed over the verified index.
    # No unversioned marketing endpoint or published-current receipt is needed.
    category = canonical({'apis': [{'id': row['id']} for row in providers]})
    facts = {Path(name).name: content for name, content in contents.items()}
    facts['category.json'] = category
    return facts, {
        'kind': 'private_publication_snapshot_transport',
        'schema_version': metadata['schema_version'], 'snapshot_sha256': snapshot_sha256,
        'generation': generation, 'source_digest': source_digest, 'compiler_revision': compiler_revision,
        'category_source': 'verified_closed_index_provider_ids',
        'freshness': 'pending_or_historical_input_not_current_freshness',
        'validation': 'pinned_transport_integrity_not_go_validation_attestation',
        'source_governance': 'bundle_historical_replay_only_not_current_authorization',
    }


def compile_snapshot(bundle_root, snapshot_root, *, bundle_sha256, docs_ref,
                     snapshot_sha256, generation, source_digest, compiler_revision, output):
    bundle = load_bundle(bundle_root, expected_manifest_sha256=bundle_sha256, expected_docs_ref=docs_ref)
    facts, binding = load_snapshot(snapshot_root, snapshot_sha256=snapshot_sha256,
        generation=generation, source_digest=source_digest, compiler_revision=compiler_revision)
    return compile_verified_inputs(bundle, facts, binding, output=output,
                                   input_kind='internal_publication_snapshot')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--bundle-sha256', required=True)
    parser.add_argument('--docs-ref', required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--snapshot-sha256', required=True)
    parser.add_argument('--generation', type=int, required=True)
    parser.add_argument('--source-digest', required=True)
    parser.add_argument('--compiler-revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compile_snapshot(args.bundle, args.snapshot, bundle_sha256=args.bundle_sha256,
            docs_ref=args.docs_ref, snapshot_sha256=args.snapshot_sha256, generation=args.generation,
            source_digest=args.source_digest, compiler_revision=args.compiler_revision, output=args.output)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        # Private adapter diagnostics never echo paths, JSON values or payloads.
        parser.exit(1, 'Internal snapshot shadow rejected: ' + type(exc).__name__ + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
