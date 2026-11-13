"""Reproduce canonical output with the independently deployed Composer pins."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from export_schema_input_bundle import GitSource, export_reviewed_bundle
from runtime_contract_artifact import AGGREGATE, NATIVE, READINESS, file_limit
from schema_input_bundle import regular_read, require, sha


def stage_composer(repository, pins, target):
    """Match Services' source-manifest format; never execute current PR code."""
    source = GitSource(repository, pins['composer_revision'])
    require(source.git('merge-base', '--is-ancestor', source.ref, 'HEAD') == b'',
            'Replay Composer is not on current main history')
    source.read(source.ref, 'scripts/shadow_compile_bundle.py')
    hashes, total = {}, 0
    for name in sorted(source.trees[source.ref]):
        if not re.fullmatch(r'scripts/[A-Za-z0-9_]+\.py', name):
            continue
        raw = source.read(source.ref, name)
        total += len(raw)
        require(0 < len(raw) <= 4 << 20 and total <= 32 << 20 and len(hashes) < 256,
                'Replay Composer source exceeds bound')
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        hashes[name] = sha(raw)
    # Services hashes this manifest without the JSON-line trailing newline.
    manifest = json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()
    require(sha(manifest) == pins['source_manifest_sha256'],
            'Replay Composer source manifest differs from live pin')


def verify_outputs(output, members):
    expected = {}
    for name, raw in members.items():
        if NATIVE.fullmatch(name) or name == READINESS:
            expected[name.removeprefix('contracts/')] = (name, raw)
        elif name == AGGREGATE:
            expected['aggregate/openapi.json'] = (name, raw)
    actual = {path.relative_to(output).as_posix() for path in output.rglob('*') if path.is_file()}
    require(actual == set(expected) | {'manifest.json'}, 'Canonical replay output membership differs')
    for name, (member, raw) in expected.items():
        require(regular_read(output, name, limit=file_limit(member)) == raw,
                'Canonical replay output differs: ' + member)
    return len(expected)


def replay_canonical_output(repository, acquired, assessment, members):
    """Called only after input/acquisition verification, for draft discrepancies.

    The existing locked compiler independently checks the original acquisition
    and bundle. Compare every native, aggregate and readiness byte, not just the
    differing draft or a selection of fields. No generated draft enters inputs.
    """
    pins = assessment['compiler_inputs']
    runtime = assessment['runtime']
    with tempfile.TemporaryDirectory(prefix='canonical-pinned-replay-') as directory:
        root = Path(directory)
        stage_composer(repository, pins, root / 'composer')
        bundle = root / 'bundle'
        exported = export_reviewed_bundle(repository, pins['docs_ref'], bundle)
        require(exported['manifest_sha256'] == pins['bundle_manifest_sha256'],
                'Replay schema bundle differs from live pin')
        output = root / 'output'
        command = [sys.executable, str(root / 'composer/scripts/shadow_compile_bundle.py'),
            '--bundle', str(bundle), '--bundle-sha256', pins['bundle_manifest_sha256'],
            '--docs-ref', pins['docs_ref'], '--runtime', str(Path(acquired).resolve()),
            '--artifact-revision', runtime['artifact_revision'],
            '--compiler-revision', runtime['compiler_revision'],
            '--runtime-receipt-sha256', assessment['runtime_acquisition_sha256'],
            '--output', str(output)]
        # No GitHub/API credentials or import overrides reach the offline child.
        environment = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT') if key in os.environ}
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run(command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        require(result.returncode == 0, 'Pinned canonical replay failed')
        compared = verify_outputs(output, members)
    return {'status': 'passed', 'compared_files': compared,
            'compiler_revision': pins['composer_revision'],
            'source_manifest_sha256': pins['source_manifest_sha256'],
            'bundle_manifest_sha256': pins['bundle_manifest_sha256']}
