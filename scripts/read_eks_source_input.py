"""Authenticate an exact EKS capture and assess only a reviewed source-input PR.

The operator binding lives in a protected repository variable, never in R.
Run this file and its sibling modules from the independently checked out B=Q.
A matched typed rejection is input-diagnostic compatibility, NOT readiness.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import io
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from contract_change_scope import is_reviewed_input_change
from export_schema_input_bundle import export_reviewed_bundle
from internal_publication_snapshot import compile_snapshot, load_snapshot
from readiness_rejection import NORMALIZATION, SnapshotReadinessRejected
from schema_input_bundle import canonical, load_bundle, require, sha, strict_json
from source_governance import source_report

DOCS = 'AIsa-team/docs'
INFRA = 'AIsa-team/aisa-infra'
WORKFLOW = '.github/workflows/integration-catalog-export.yml'
SCOPE = 'eks_source_input_diagnostic_compatibility_only_not_formal_readiness'
BINDING_ENV = 'CONTRACT_EKS_INPUT_DIAGNOSTIC_BINDING'
MEMBERS = {'dispatch.json', 'build.json', 'observation.json', 'publication-snapshot.json.gz'}
MAX_ARCHIVE = 20 << 20
MAX_RAW = 65 << 20


def closed(value, fields):
    require(type(value) is dict and set(value) == set(fields), 'Unexpected binding fields')
    return value


def pin(value, size=64):
    require(type(value) is str and re.fullmatch('[0-9a-f]{%d}' % size, value)
            and value != '0' * size, 'Invalid immutable pin')


def positive(value):
    require(type(value) is int and 0 < value < 1 << 63, 'Invalid positive identity')


def timestamp(value):
    require(type(value) is str and len(value) <= 40, 'Invalid UTC time')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0, 'UTC required')
    return parsed


def lease(binding, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    start, end = timestamp(binding['issued_at']), timestamp(binding['expires_at'])
    require(start <= now < end and 0 < (end-start).total_seconds() <= 3600,
            'Operator selection is expired or invalid')


def validate_binding(binding):
    closed(binding, ('schema_version', 'scope', 'docs_pr', 'base_revision', 'head_revision',
        'trusted_code_revision', 'changed_paths_sha256', 'bundle_manifest_sha256',
        'infra_source', 'workflow_sha256', 'run_id', 'run_attempt', 'jobs', 'artifact_id',
        'artifact_zip_sha256', 'artifact_gzip_sha256', 'snapshot_pins', 'diagnostic_expectation',
        'issued_at', 'expires_at'))
    require(type(binding['schema_version']) is int and binding['schema_version'] == 1
            and binding['scope'] == SCOPE, 'Wrong binding scope')
    for field in ('base_revision', 'head_revision', 'trusted_code_revision', 'infra_source'):
        pin(binding[field], 40)
    require(binding['trusted_code_revision'] == binding['base_revision'] != binding['head_revision'],
            'This reader requires exact B=Q and a distinct source R')
    for field in ('changed_paths_sha256', 'bundle_manifest_sha256', 'workflow_sha256',
                  'artifact_zip_sha256', 'artifact_gzip_sha256'):
        pin(binding[field])
    for field in ('docs_pr', 'run_id', 'run_attempt', 'artifact_id'):
        positive(binding[field])
    jobs = binding['jobs']
    require(type(jobs) is list and len(jobs) == 2, 'Exact producer jobs required')
    for job in jobs:
        closed(job, ('name', 'id')); positive(job['id'])
    require({j['name'] for j in jobs} == {'tests', 'collect'} and len({j['id'] for j in jobs}) == 2,
            'Producer prerequisite jobs differ')
    pins = closed(binding['snapshot_pins'], ('snapshot_sha256', 'generation', 'source_digest', 'compiler_revision'))
    for field in ('snapshot_sha256', 'source_digest'): pin(pins[field])
    pin(pins['compiler_revision'], 40)
    require(type(pins['generation']) is int and 0 <= pins['generation'] < 1 << 64, 'Invalid generation')
    diagnostic = closed(binding['diagnostic_expectation'], ('normalization', 'diagnostic_sha256',
        'provider_count', 'blocked_provider_count', 'diagnostic_entry_count'))
    require(diagnostic['normalization'] == NORMALIZATION, 'Unknown diagnostic normalization')
    pin(diagnostic['diagnostic_sha256'])
    for field in ('provider_count', 'blocked_provider_count', 'diagnostic_entry_count'):
        require(type(diagnostic[field]) is int and 0 <= diagnostic[field] < 1 << 32, 'Invalid diagnostic count')
    lease(binding)
    return binding


def git(repo, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=repo,
        env={'PATH': os.environ['PATH'], 'HOME': '/nonexistent', 'GIT_CONFIG_NOSYSTEM': '1',
             'GIT_CONFIG_GLOBAL': '/dev/null'}, timeout=30)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHub:
    """No token forwarded to artifact storage, no arbitrary authenticated hosts."""
    def __init__(self, token):
        require(token and '\r' not in token and '\n' not in token, 'Missing metadata credential')
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, limit=8 << 20):
        require(path.startswith('/repos/AIsa-team/') and '?' not in path.split('/repos/AIsa-team/', 1)[0],
                'Unsupported GitHub path')
        request = urllib.request.Request('https://api.github.com' + path, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(limit + 1)
                require(response.status == 200 and len(raw) <= limit, 'GitHub response exceeds bounds')
                return raw
        except urllib.error.HTTPError as error:
            if error.code != 302 or not path.endswith('/zip'):
                raise ValueError('GitHub metadata unavailable') from None
            location = error.headers.get('Location', '')
            parsed = urllib.parse.urlsplit(location)
            host = parsed.hostname or ''
            require(parsed.scheme == 'https' and parsed.port in (None, 443) and not parsed.username
                    and not parsed.password and not parsed.fragment and
                    (host.endswith('.blob.core.windows.net') or host.endswith('.actions.githubusercontent.com')),
                    'Untrusted artifact redirect')
            # New unauthenticated request: the GitHub token never leaves api.github.com.
            with self.opener.open(urllib.request.Request(location), timeout=45) as response:
                raw = response.read(limit + 1)
                require(response.status == 200 and len(raw) <= limit, 'Artifact exceeds bounds')
                return raw

    def json(self, path):
        return strict_json(self.request(path))


def same_pr(pr, binding):
    require(pr.get('number') == binding['docs_pr'] and pr.get('state') == 'open'
            and pr.get('merged') is False and pr.get('base', {}).get('ref') == 'main', 'PR is no longer open')
    for side, key in (('base', 'base_revision'), ('head', 'head_revision')):
        require(pr.get(side, {}).get('sha') == binding[key] and
                pr.get(side, {}).get('repo', {}).get('full_name') == DOCS, 'PR identity changed')


def source_only(paths):
    # The older classifier also permits regression tests and deferral policies.
    # This diagnostic lane cannot grant either executable or policy changes.
    forbidden = {'openapi/policies/deferred-enabled-20261010.json',
                 'docs/deferred-age-response-rebinding-20261012.json'}
    return is_reviewed_input_change(paths) and not any(
        name.startswith('scripts/') or name in forbidden for name in paths)


def authenticate_docs(api, binding, repo, trusted_root):
    same_pr(api.json('/repos/' + DOCS + '/pulls/' + str(binding['docs_pr'])), binding)
    require(api.json('/repos/' + DOCS + '/branches/main')['commit']['sha'] == binding['base_revision'],
            'Docs main changed')
    require(git(trusted_root, 'rev-parse', 'HEAD').decode().strip() == binding['trusted_code_revision'],
            'Reader must execute from exact trusted B=Q checkout')
    require(not git(trusted_root, 'status', '--porcelain', '--untracked-files=no').strip(),
            'Trusted checkout changed')
    require(Path(__file__).resolve() == (trusted_root / 'scripts/read_eks_source_input.py').resolve(),
            'Reader is not executing the trusted checkout')
    git(repo, 'merge-base', '--is-ancestor', binding['base_revision'], binding['head_revision'])
    paths = sorted(git(repo, 'diff', '--name-only', binding['base_revision'], binding['head_revision']).decode().splitlines())
    require(source_only(paths) and sha(canonical(paths)) == binding['changed_paths_sha256'],
            'Not the bound closed source-only diff')
    # No source PR may modify executable/compiler inputs; classifier remains B's.
    lease(binding)
    return paths


def authenticate_producer(api, binding):
    root = '/repos/' + INFRA
    branch = api.json(root + '/branches/main')
    require(branch.get('protected') is True and branch['commit']['sha'] == binding['infra_source'],
            'Producer is not the independently bound protected infra main')
    workflow = api.json(root + '/contents/' + WORKFLOW + '?ref=' + binding['infra_source'])
    require(workflow.get('type') == 'file' and workflow.get('encoding') == 'base64'
            and sha(base64.b64decode(workflow['content'])) == binding['workflow_sha256'],
            'Producer workflow bytes differ')
    run = api.json(root + '/actions/runs/' + str(binding['run_id']))
    require(run.get('id') == binding['run_id'] and run.get('run_attempt') == binding['run_attempt']
            and run.get('head_sha') == binding['infra_source'] and run.get('head_branch') == 'main'
            and run.get('event') == 'workflow_dispatch' and run.get('path') == WORKFLOW
            and run.get('status') == 'completed' and run.get('conclusion') == 'success'
            and run.get('repository', {}).get('full_name') == INFRA, 'Producer run identity differs')
    jobs = api.json(root + '/actions/runs/' + str(binding['run_id']) + '/attempts/' +
                    str(binding['run_attempt']) + '/jobs?per_page=100')
    rows = jobs.get('jobs', [])
    require(jobs.get('total_count') == len(rows) == len(binding['jobs']) and
            sorted((j['id'], j['name']) for j in rows) == sorted((j['id'], j['name']) for j in binding['jobs'])
            and all(j.get('status') == 'completed' and j.get('conclusion') == 'success'
                    and j.get('run_id') == binding['run_id'] and j.get('head_sha') == binding['infra_source']
                    and j.get('run_attempt') == binding['run_attempt'] for j in rows), 'Producer jobs differ')
    artifact = api.json(root + '/actions/artifacts/' + str(binding['artifact_id']))
    require(artifact.get('id') == binding['artifact_id'] and artifact.get('expired') is False
            and artifact.get('name') == 'integration-catalog-export-' + str(binding['run_id'])
            and artifact.get('digest') == 'sha256:' + binding['artifact_zip_sha256']
            and artifact.get('workflow_run', {}).get('id') == binding['run_id']
            and artifact.get('workflow_run', {}).get('head_sha') == binding['infra_source'],
            'Producer artifact differs')
    lease(binding)
    return {'run_created_at': run['created_at'], 'run_updated_at': run['updated_at'],
            'artifact_created_at': artifact['created_at']}


def unpack_capture(raw, binding):
    require(0 < len(raw) <= MAX_ARCHIVE and sha(raw) == binding['artifact_zip_sha256'], 'Artifact bytes differ')
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows = archive.infolist()
        require(len(rows) == len(MEMBERS) and {i.filename for i in rows} == MEMBERS,
                'Capture inventory differs')
        for item in rows:
            mode = item.external_attr >> 16
            require(not item.is_dir() and (stat.S_IFMT(mode) in (0, stat.S_IFREG))
                    and not item.flag_bits & 1, 'Capture members must be regular unencrypted files')
            limit = 16 << 20 if item.filename.endswith('.gz') else 1 << 20
            require(0 < item.file_size <= limit, 'Capture member exceeds bounds')
            with archive.open(item) as handle:
                content = handle.read(limit + 1)
            require(len(content) == item.file_size, 'Capture member size differs')
            files[item.filename] = content
    dispatch, build, observation = (strict_json(files[name]) for name in
        ('dispatch.json', 'build.json', 'observation.json'))
    identity = str(binding['run_id']) + '-' + str(binding['run_attempt'])
    require(dispatch['infra_source'] == observation['infra_source'] == binding['infra_source']
            and dispatch['identity'] == observation['identity'] == identity
            and dispatch['operation'] == observation['operation'] == 'export-integration-catalog'
            and dispatch['build_id'] == observation['build_id'] == build['id']
            and build['buildStatus'] == 'SUCCEEDED' and build['sourceVersion'] == dispatch['source_version'],
            'CodeBuild capture provenance differs')
    pins = binding['snapshot_pins']
    require(observation['status'] == 'collected' and observation['kind'] == 'publication'
            and observation['executor'] == 'codebuild' and observation['SQL_mutations'] == 0
            and observation['Kubernetes_mutations'] == 0 and observation['provider_credentials_exported'] == 0
            and observation['sources'] == {'prod': pins['compiler_revision']}
            and observation['generation'] == pins['generation'] and observation['source_digest'] == pins['source_digest'],
            'Capture is not the bound read-only production snapshot')
    packed = files['publication-snapshot.json.gz']
    require(observation['artifact']['name'] == 'publication-snapshot.json.gz'
            and len(packed) == observation['artifact']['bytes']
            and sha(packed) == observation['artifact']['sha256'] == binding['artifact_gzip_sha256'],
            'Snapshot transport differs')
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as handle:
        decoded = handle.read(MAX_RAW + 1)
    require(0 < len(decoded) <= MAX_RAW, 'Snapshot transport expansion exceeds bounds')
    value = strict_json(decoded)
    require(value['compiler_revision'] == pins['compiler_revision'] and value['generation'] == pins['generation']
            and value['source_digest'] == pins['source_digest'], 'Raw snapshot identity differs')
    return decoded


def assess_source(repo, binding, workspace):
    exported = export_reviewed_bundle(repo, binding['head_revision'], workspace / 'bundle')
    require(exported['manifest_sha256'] == binding['bundle_manifest_sha256'], 'Exact R bundle differs')
    bundle = load_bundle(workspace / 'bundle', expected_manifest_sha256=binding['bundle_manifest_sha256'],
                         expected_docs_ref=binding['head_revision'])
    inputs = workspace / 'governance'; inputs.mkdir()
    for name, data in bundle.contents.items():
        if name.startswith('input/'):
            target = inputs / name.removeprefix('input/'); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    receipts = strict_json(bundle.contents['evidence/source-receipts.json'])
    governance = check_governance(inputs, receipts)
    return governance


def check_governance(inputs, receipts):
    governance = source_report(inputs, receipts['receipts'], attempts=receipts.get('attempts', {}))
    require(governance['status'] == 'passed' and not governance['policy_errors'], 'Current source governance failed')
    return governance


def check_rejection(proof, binding):
    expected = {'schema_version': 1, 'scope': 'aisa-internal-snapshot-readiness-rejection',
        'status': 'readiness_rejected', 'bundle_manifest_sha256': binding['bundle_manifest_sha256'],
        'docs_ref': binding['head_revision'], **binding['snapshot_pins'], **binding['diagnostic_expectation']}
    require(proof == expected, 'Complete typed readiness diagnostic differs from operator expectation')


def run(binding, *, api, repo, trusted_root, services, output):
    start = time.monotonic()
    require(not output.exists() and output.parent.is_dir(), 'Fresh output required')
    paths = authenticate_docs(api, binding, repo, trusted_root)
    capture = authenticate_producer(api, binding)
    raw = api.request('/repos/' + INFRA + '/actions/artifacts/' + str(binding['artifact_id']) + '/zip', MAX_ARCHIVE)
    decoded = unpack_capture(raw, binding)
    require(git(services, 'rev-parse', 'HEAD').decode().strip() == binding['snapshot_pins']['compiler_revision']
            and not git(services, 'status', '--porcelain', '--untracked-files=no').strip(), 'Go validator source differs')
    with tempfile.TemporaryDirectory(prefix='eks-source-input-') as temporary:
        workspace = Path(temporary)
        raw_path = workspace / 'publication-snapshot.json'; raw_path.write_bytes(decoded)
        snapshot = workspace / 'snapshot'
        # This helper and Go module are both outside R. The original validator
        # runs before any Content is materialized; the Python loader rechecks pins.
        go_env = {key: os.environ[key] for key in ('PATH', 'HOME', 'GOPATH', 'GOCACHE', 'GOMODCACHE', 'GOPROXY')
                  if key in os.environ}
        go_env.update(GOWORK='off', GOFLAGS='-mod=readonly')
        subprocess.run(['go', 'run', str(trusted_root / 'scripts/materialize_eks_snapshot.go'),
                        str(raw_path), str(snapshot)], cwd=services, check=True, timeout=120,
                       env=go_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        load_snapshot(snapshot, **binding['snapshot_pins'])
        governance = assess_source(repo, binding, workspace)
        try:
            compile_snapshot(workspace / 'bundle', snapshot,
                bundle_sha256=binding['bundle_manifest_sha256'], docs_ref=binding['head_revision'],
                output=workspace / 'strict-output', **binding['snapshot_pins'])
        except SnapshotReadinessRejected as error:
            proof = error.proof
            check_rejection(proof, binding)
        else:
            raise ValueError('Strict success requires the ordinary formal path, not diagnostic selection')
        require(not (workspace / 'strict-output').exists(), 'Rejected compile produced artifacts')
        # Slow compilation cannot authorize a stale PR, changed attempt or lease.
        authenticate_docs(api, binding, repo, trusted_root)
        authenticate_producer(api, binding)
        governance = check_governance(workspace / 'governance',
            strict_json((workspace / 'bundle/evidence/source-receipts.json').read_bytes()))
        lease(binding)
        receipt = {'schema_version': 1, 'scope': SCOPE, 'status': 'source_input_diagnostic_compatible',
            'formal_publication': False, 'strict_verdict': 'readiness_rejected', 'strict_exit_code': 78,
            'output_artifact_count': 0, 'binding_sha256': sha(canonical(binding)),
            'base_revision': binding['base_revision'], 'head_revision': binding['head_revision'],
            'trusted_code_revision': binding['trusted_code_revision'], 'changed_paths': paths,
            'bundle_manifest_sha256': binding['bundle_manifest_sha256'],
            'producer': {key: binding[key] for key in ('infra_source', 'run_id', 'run_attempt', 'jobs',
                'artifact_id', 'artifact_zip_sha256', 'artifact_gzip_sha256')},
            'capture_times': capture, 'capture_scope': 'facts_at_original_observation_not_current_freshness',
            'source_governance_status': governance['status'], 'rejection': proof,
            'assessed_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'seconds': round(time.monotonic()-start, 3)}
    output.mkdir(mode=0o700)
    (output / 'receipt.json').write_bytes(canonical(receipt))
    return receipt


def selected_binding(raw, event):
    if not raw: return None
    require(len(raw.encode()) <= 48000, 'Operator binding exceeds bounds')
    value = strict_json(raw)
    # An unrelated PR's independent selection is inert, never a fallback.
    if type(value) is dict and value.get('head_revision') != event.get('pull_request', {}).get('head', {}).get('sha'):
        return None
    validate_binding(value)
    require(event.get('repository', {}).get('full_name') == DOCS and event.get('number') == value['docs_pr'],
            'Wrong event repository or PR')
    same_pr(event.get('pull_request', {}), value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--select', action='store_true')
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--services', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        require(os.environ.get('GITHUB_EVENT_NAME') == 'pull_request' and
                os.environ.get('GITHUB_REPOSITORY') == DOCS, 'Only the real Docs pull request event is supported')
        event = strict_json(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
        binding = selected_binding(os.environ.get(BINDING_ENV, ''), event)
        if args.select:
            if binding:
                authenticate_docs(GitHub(os.environ['GH_TOKEN']), binding, args.repo.resolve(), Path(__file__).resolve().parents[1])
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('selected=' + ('true' if binding else 'false') + '\n')
                if binding:
                    output.write('compiler_revision=' + binding['snapshot_pins']['compiler_revision'] + '\n')
            return
        require(binding is not None and args.services is not None and args.output is not None,
                'Exact operator selection and paths are required')
        run(binding, api=GitHub(os.environ['GH_TOKEN']), repo=args.repo.resolve(),
            trusted_root=Path(__file__).resolve().parents[1], services=args.services.resolve(), output=args.output.resolve())
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError, zipfile.BadZipFile):
        parser.exit(1, 'EKS source-input assessment rejected; no compatibility or publication receipt issued.\n')


if __name__ == '__main__':
    main()
