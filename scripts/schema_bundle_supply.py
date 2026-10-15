"""Package pinned schema inputs for CI transport; no publication or review authority."""
from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

from export_schema_input_bundle import GitSource, export_bundle
from publication_origin import ORIGIN, REPOSITORY, WORKFLOW
from schema_input_bundle import (HEX40, HEX64, MAX_FILE, MAX_FILES, MAX_TOTAL,
                                 REVIEWED_BASELINE, canonical, load_bundle,
                                 regular_read, require, role_for, sha, strict_json)

SCOPE = 'verified_build_input_not_publication_or_current_source_authorization'
KIND = 'aisa-schema-bundle-supply-candidate'
ARCHIVE = 'bundle.tar.gz'
MAX_ARCHIVE = MAX_TOTAL + (1 << 20)


def pack_bundle(root, destination):
    """Stable transport bytes; original JSON/schema/receipt bytes stay untouched."""
    manifest_raw = regular_read(root, 'manifest.json')
    manifest = strict_json(manifest_raw)
    names = ['manifest.json'] + [row['path'] for row in manifest['files']]
    require(len(names) == len(set(names)) <= MAX_FILES + 1, 'Invalid archive membership')
    with destination.open('xb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
                for name in sorted(names):
                    if name != 'manifest.json':
                        role_for(name)
                    raw = regular_read(root, name)
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = len(raw), 0o644, 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    archive.addfile(info, io.BytesIO(raw))


def unpack_bundle(raw, destination):
    """Bound streaming expansion; never use tar extract/extractall."""
    require(len(raw) <= MAX_ARCHIVE, 'Archive exceeds compressed byte limit')
    destination.mkdir()
    seen, total = set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r|gz') as archive:
        for member in archive:
            name = member.name
            require(member.isfile() and not member.pax_headers and name not in seen,
                    'Archive contains a non-file, duplicate or unsupported metadata')
            if name != 'manifest.json':
                role_for(name)
            require(0 < member.size <= MAX_FILE and len(seen) < MAX_FILES + 1,
                    'Archive member limit exceeded')
            total += member.size
            require(total <= MAX_TOTAL + MAX_FILE, 'Archive expanded byte limit exceeded')
            handle = archive.extractfile(member)
            require(handle is not None, 'Missing archive member bytes')
            content = handle.read(member.size + 1)
            require(len(content) == member.size, 'Archive member size differs')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            seen.add(name)
    require('manifest.json' in seen, 'Archive manifest missing')


def read_archive(root):
    path = root / ARCHIVE
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_ARCHIVE,
            'Missing or oversized regular archive')
    with path.open('rb') as handle:
        raw = handle.read(MAX_ARCHIVE + 1)
    require(len(raw) <= MAX_ARCHIVE, 'Archive compressed byte limit exceeded')
    return raw


def verify_supply(root, *, bundle_sha256, archive_sha256, docs_ref, run_id, run_attempt, output=None):
    """Verify transport against external pins; GitHub origin authentication is separate."""
    root = Path(root)
    output = Path(output) if output is not None else None
    if output is not None:
        require(output.parent.is_dir() and not output.exists() and not output.is_symlink(),
                'Verified bundle output must be a new directory')
    require(root.is_dir() and not root.is_symlink() and
            {p.name for p in root.iterdir()} == {'supply.json', ARCHIVE}, 'Unexpected supply members')
    require(all(isinstance(value, str) and HEX64.fullmatch(value) for value in (bundle_sha256, archive_sha256))
            and isinstance(docs_ref, str) and HEX40.fullmatch(docs_ref), 'Independent supply pins required')
    require(isinstance(run_id, str) and run_id.isascii() and run_id.isdigit() and
            type(run_attempt) is int and run_attempt > 0, 'Invalid producer pins')
    raw_packet = regular_read(root, 'supply.json')
    require(len(raw_packet) <= 1 << 20, 'Supply metadata exceeds limit')
    packet = strict_json(raw_packet)
    require(isinstance(packet, dict) and set(packet) == {'schema_version', 'kind', 'scope', 'bundle', 'producer'}
            and type(packet['schema_version']) is int and packet['schema_version'] == 1
            and packet['kind'] == KIND and packet['scope'] == SCOPE, 'Unsupported supply envelope')
    bundle, producer = packet['bundle'], packet['producer']
    require(isinstance(bundle, dict) and set(bundle) == {'schema_version', 'manifest_sha256', 'docs_ref',
            'baseline_ref', 'source_receipts_sha256', 'source_checked_at', 'archive'} and
            type(bundle['schema_version']) is int and bundle['schema_version'] == 2 and
            bundle['manifest_sha256'] == bundle_sha256 and bundle['docs_ref'] == docs_ref and
            bundle['baseline_ref'] == REVIEWED_BASELINE, 'Bundle trust pins differ')
    require(isinstance(producer, dict) and set(producer) == {'repository', 'workflow', 'run_id',
            'run_attempt', 'assessed_base', 'origin_sha256'} and producer['repository'] == REPOSITORY
            and producer['workflow'] == WORKFLOW and producer['run_id'] == run_id and
            type(producer['run_attempt']) is int and producer['run_attempt'] == run_attempt and
            isinstance(producer['assessed_base'], str) and HEX40.fullmatch(producer['assessed_base']) and
            isinstance(producer['origin_sha256'], str) and HEX64.fullmatch(producer['origin_sha256']),
            'Producer binding differs; metadata is not authentication')
    archive = bundle['archive']
    raw = read_archive(root)
    require(isinstance(archive, dict) and set(archive) == {'path', 'sha256', 'bytes'} and
            archive['path'] == ARCHIVE and archive['sha256'] == archive_sha256 == sha(raw) and
            type(archive['bytes']) is int and archive['bytes'] == len(raw), 'Archive bytes or pin differ')
    with tempfile.TemporaryDirectory(prefix='verify-schema-supply-',
                                     dir=output.parent if output is not None else None) as folder:
        unpacked = Path(folder) / 'bundle'
        unpack_bundle(raw, unpacked)
        verified = load_bundle(unpacked, expected_manifest_sha256=bundle_sha256, expected_docs_ref=docs_ref)
        require(bundle['source_receipts_sha256'] == sha(verified.contents['evidence/source-receipts.json']) and
                bundle['source_checked_at'] == verified.validation['source_checked_at'],
                'Original source receipt or assessment clock differs')
        if output is not None:
            require(not output.exists() and not output.is_symlink(), 'Verified destination appeared')
            unpacked.rename(output)
    return {'status': 'passed', 'scope': SCOPE, 'bundle': verified.validation,
            'archive_sha256': archive_sha256,
            'producer_authentication': 'external_successful_formal_origin_and_main_ancestry_required'}


def build_supply(repo, docs_ref, source_receipts, output, *, run_id, run_attempt):
    output = Path(output)
    require(output.parent.is_dir() and not output.exists() and not output.is_symlink(),
            'Supply output must be a new directory')
    source = GitSource(repo, docs_ref)
    origin_raw = source.read(docs_ref, ORIGIN)
    origin = strict_json(origin_raw)
    parents = source.git('show', '-s', '--format=%P', docs_ref).decode().split()
    require(origin.get('repository') == REPOSITORY and origin.get('workflow') == WORKFLOW and
            origin.get('run_id') == run_id and type(origin.get('run_attempt')) is int and
            origin['run_attempt'] == run_attempt and parents == [origin.get('assessed_base')],
            'Local commit is not bound to this original producer attempt')
    with tempfile.TemporaryDirectory(prefix='.schema-supply-build-', dir=output.parent) as folder:
        temporary = Path(folder)
        bundle_dir, packet_dir = temporary / 'bundle', temporary / 'packet'
        result = export_bundle(repo, docs_ref, REVIEWED_BASELINE, source_receipts, bundle_dir, bundle_version=2)
        pointer_raw = regular_read(bundle_dir, 'input/docs/publication/current.json')
        require(origin.get('current_sha256') == sha(pointer_raw) and
                origin.get('contract_release') == strict_json(pointer_raw)['contract_release'],
                'Origin differs from exported formal pointer')
        packet_dir.mkdir()
        pack_bundle(bundle_dir, packet_dir / ARCHIVE)
        raw = read_archive(packet_dir)
        packet = {'schema_version': 1, 'kind': KIND, 'scope': SCOPE,
            'bundle': {'schema_version': 2, 'manifest_sha256': result['manifest_sha256'],
                'docs_ref': docs_ref, 'baseline_ref': REVIEWED_BASELINE,
                'source_receipts_sha256': sha(regular_read(bundle_dir, 'evidence/source-receipts.json')),
                'source_checked_at': result['source_checked_at'],
                'archive': {'path': ARCHIVE, 'sha256': sha(raw), 'bytes': len(raw)}},
            'producer': {'repository': REPOSITORY, 'workflow': WORKFLOW, 'run_id': run_id,
                'run_attempt': run_attempt, 'assessed_base': parents[0], 'origin_sha256': sha(origin_raw)}}
        (packet_dir / 'supply.json').write_bytes(canonical(packet))
        verify_supply(packet_dir, bundle_sha256=result['manifest_sha256'], archive_sha256=sha(raw),
                      docs_ref=docs_ref, run_id=run_id, run_attempt=run_attempt)
        require(not output.exists() and not output.is_symlink(), 'Supply destination appeared during build')
        packet_dir.rename(output)
    return packet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build')
    build.add_argument('--repo', type=Path, required=True)
    build.add_argument('--source-receipts', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('--input', type=Path, required=True)
    verify.add_argument('--bundle-sha256', required=True)
    verify.add_argument('--archive-sha256', required=True)
    verify.add_argument('--output', type=Path, help='Optional new directory for the verified original bundle')
    for command in (build, verify):
        command.add_argument('--docs-ref', required=True)
        command.add_argument('--run-id', required=True)
        command.add_argument('--run-attempt', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            result = build_supply(args.repo, args.docs_ref, args.source_receipts, args.output,
                                  run_id=args.run_id, run_attempt=args.run_attempt)
        else:
            result = verify_supply(args.input, bundle_sha256=args.bundle_sha256,
                archive_sha256=args.archive_sha256, docs_ref=args.docs_ref,
                run_id=args.run_id, run_attempt=args.run_attempt, output=args.output)
    except (ValueError, TypeError, KeyError, OSError, tarfile.TarError, subprocess.SubprocessError) as exc:
        parser.exit(1, 'Schema supply rejected: ' + str(exc) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
