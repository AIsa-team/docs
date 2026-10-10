#!/usr/bin/env python3
"""Bind monitor selection to a sole-publisher commit and its original step clock."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile

from export_contract_publication import canonical, source_expiry
from fetch_runtime_release import require, sha
from publication_surface import publication_hashes
from source_governance import policy_errors, policy_revision

REPOSITORY = 'AIsa-team/docs'
WORKFLOW = '.github/workflows/pull-openapi.yml'
STEP = 'Commit contract mirrors and coverage'
ORIGIN = 'docs/publication/release-origin.json'


def instant(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Publication clock requires timezone')
    return parsed.astimezone(timezone.utc)


def record(root, run_id, attempt, now=None):
    """Called only after real staged changes, before the guarded publish commit."""
    if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=root).returncode == 0:
        return None
    require(re.fullmatch('[0-9]+', str(run_id)) and type(attempt) is int and attempt > 0, 'Invalid publisher identity')
    pointer = (root / 'docs/publication/current.json').read_bytes()
    current = json.loads(pointer)
    base = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    origin = {'schema_version': 1, 'repository': REPOSITORY, 'workflow': WORKFLOW,
              'run_id': str(run_id), 'run_attempt': int(attempt), 'assessed_base': base,
              'budget_start': (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat(),
              'contract_release': current['contract_release'], 'current_sha256': sha(pointer)}
    (root / ORIGIN).write_text(json.dumps(origin, indent=2, sort_keys=True) + '\n')
    return origin


def verify_producer(origin, run, jobs, parent, now=None):
    now = now or datetime.now(timezone.utc)
    require(origin.get('schema_version') == 1 and origin.get('repository') == REPOSITORY
            and origin.get('workflow') == WORKFLOW, 'Untrusted publication origin')
    require(re.fullmatch('[0-9a-f]{40}', str(parent)) and origin.get('assessed_base') == parent,
            'Publication must have its assessed base as sole parent')
    require(str(run.get('id')) == origin.get('run_id')
            and run.get('run_attempt') == origin.get('run_attempt')
            and run.get('repository', {}).get('full_name') == REPOSITORY
            and run.get('path') == WORKFLOW and run.get('head_branch') == 'main'
            and run.get('head_sha') == parent
            and run.get('event') in {'schedule', 'workflow_dispatch'}, 'Untrusted publisher run')
    # A notification failure must not invalidate an already successful publish.
    # The original compose and publish-step conclusions are the relevant proof.
    compose = [job for job in jobs if job.get('name') == 'compose']
    require(len(compose) == 1 and compose[0].get('conclusion') == 'success', 'Publisher compose did not succeed')
    steps = [step for step in compose[0].get('steps', []) if step.get('name') == STEP]
    require(len(steps) == 1 and steps[0].get('conclusion') == 'success', 'Publish step did not succeed')
    t0 = instant(origin['budget_start'])
    require(instant(steps[0]['started_at']) <= t0 <= instant(steps[0]['completed_at']) <= now,
            'Budget start is outside the original successful publish step')


def verify_graph(root, origin, artifact, now=None):
    now = now or datetime.now(timezone.utc)
    pointer = (root / 'docs/publication/current.json').read_bytes()
    current = json.loads(pointer)
    raw = (root / 'docs/publication/formal-contract-readiness.json').read_bytes()
    report = json.loads(raw)
    require(sha(pointer) == origin.get('current_sha256'), 'Origin pointer bytes differ')
    require(raw == artifact, 'Published formal receipt differs from authenticated producer artifact')
    hashes = publication_hashes(root)
    core = {key: current.get(key) for key in ('schema_version', 'runtime', 'files_sha256')}
    require(not any((root / name).is_symlink() for name in hashes), 'Publication graph contains symlinks')
    require(current.get('schema_version') == 1 and current.get('status') == 'passed' and current.get('files_sha256') == hashes
            and current.get('contract_release') == origin.get('contract_release') == sha(canonical(core)),
            'Publication graph or C differs')
    require(report.get('status') == 'passed'
            and report.get('evaluation') == 'actual_publication_graph_and_offline_composed_candidate'
            and report.get('runtime') == current.get('runtime'), 'Formal producer assessment is invalid')
    for scope in (report, report.get('composed_candidate', {})):
        require(scope.get('status') == 'passed' and not scope.get('global_errors')
                and not scope.get('missing_inputs') and not scope.get('blocked_providers'), 'Formal blockers present')
    require(report.get('publication_surfaces', {}).get('status') == 'passed', 'Publication surfaces not passed')
    binding = report['publication_artifact']
    require(binding.get('files_sha256') == hashes and binding.get('openapi_sha256') == hashes['openapi.yaml']
            and binding.get('published_ref') == origin['assessed_base'], 'Formal graph binding differs')
    for key, path in [('formal_readiness', 'docs/publication/formal-contract-readiness.json'),
                      ('runtime_acquisition', 'docs/publication/runtime-acquisition.json')]:
        require(current[key] == {'path': path, 'sha256': sha((root / path).read_bytes())}, 'Publication receipt binding differs')
    acquisition = json.loads((root / 'docs/publication/runtime-acquisition.json').read_bytes())
    require(report.get('runtime_acquisition_sha256') == current['runtime_acquisition']['sha256']
            and all(acquisition.get(k) == v for k, v in current['runtime'].items()), 'Acquisition identity differs')
    require(source_expiry(report, now) == current.get('source_authorization_expires_at'), 'Source authorization differs')
    sources = report['source_governance']['sources']
    paths = {p.name: p for p in (root / 'openapi/upstream').glob('*.json')}
    require(set(sources) == set(paths) and binding.get('source_hashes') ==
            {name: row.get('source_hash') for name, row in sources.items()}, 'Source graph differs')
    for name, path in paths.items():
        source = json.loads(path.read_bytes())['info']['x-aisa-source']
        row = sources[name]
        require(not policy_errors(source) and source.get('policy_revision') == policy_revision(source)
                and row.get('policy_revision') == source.get('policy_revision')
                and row.get('source_hash') == source.get('content_hash')
                and row.get('policy') == source.get('refresh_policy')
                and row.get('authority_url') == source.get('url'), 'Source policy binding differs')
    return current


def gh_json(endpoint):
    return json.loads(subprocess.check_output(['gh', 'api', endpoint], timeout=30))


def inspect_publication(root, ref, historical=False):
    require(subprocess.run(["git", "merge-base", "--is-ancestor", ref, "HEAD"], cwd=root).returncode == 0,
            "Formal publication is not an ancestor of monitor main")
    attributed = subprocess.check_output(["git", "log", "-1", "--format=%H", ref, "--", ORIGIN], cwd=root, text=True).strip()
    require(attributed == ref, "Requested ref is not an attributed publication commit")
    require(re.fullmatch('[0-9a-f]{40}', ref), 'No attributed formal publication on main')
    parents = subprocess.check_output(['git', 'show', '-s', '--format=%P', ref], cwd=root, text=True).split()
    require(len(parents) == 1, 'Formal publication must have one assessed parent')
    with tempfile.TemporaryDirectory(prefix='monitor-formal-') as directory:
        fixed = Path(directory) / 'docs'
        fixed.mkdir()
        archive = subprocess.Popen(['git', 'archive', ref], cwd=root, stdout=subprocess.PIPE)
        subprocess.run(['tar', '-x', '-C', str(fixed)], stdin=archive.stdout, check=True)
        archive.stdout.close()
        require(archive.wait() == 0, 'Fixed publication checkout unavailable')
        origin = json.loads((fixed / ORIGIN).read_bytes())
        require(re.fullmatch('[0-9]+', str(origin.get('run_id'))) and type(origin.get('run_attempt')) is int
                and origin['run_attempt'] > 0, 'Invalid producer attempt')
        endpoint = f"repos/{REPOSITORY}/actions/runs/{origin['run_id']}/attempts/{origin['run_attempt']}"
        run = gh_json(endpoint)
        jobs = gh_json(endpoint + '/jobs?per_page=100')['jobs']
        verify_producer(origin, run, jobs, parents[0])
        artifacts = Path(directory) / 'artifact'
        subprocess.run(['gh', 'run', 'download', origin['run_id'], '--repo', REPOSITORY,
                        '--name', 'formal-contract-readiness', '--dir', str(artifacts)], check=True, timeout=60)
        files = list(artifacts.rglob('formal-contract-readiness.json'))
        require(len(files) == 1, 'Expected one authenticated formal report')
        current = verify_graph(fixed, origin, files[0].read_bytes(),
                               now=instant(origin["budget_start"]) if historical else None)
        report = json.loads(files[0].read_bytes())
        policy = {name: {key: row.get(key) for key in ("source_hash", "policy_revision", "policy")}
                  for name, row in report["source_governance"]["sources"].items()}
    selected = {'expected_docs_ref': ref, 'budget_start': origin['budget_start'],
                'contract_release': current['contract_release'], 'producer_origin': origin,
                'authorization_fingerprint': policy,
                'authorization_expires_at': current['source_authorization_expires_at']}
    return selected


def first_contract_ref(root, contract_release):
    require(subprocess.check_output(['git', 'rev-parse', '--is-shallow-repository'], cwd=root, text=True).strip() == 'false',
            'Complete publication history required; never reset the contract clock')
    refs = subprocess.check_output(['git', 'log', '--format=%H', 'HEAD', '--', ORIGIN], cwd=root, text=True).split()
    first = None
    for ref in refs:
        pointer = json.loads(subprocess.check_output(['git', 'show', ref + ':docs/publication/current.json'], cwd=root))
        if pointer.get('contract_release') != contract_release:
            break
        first = ref
    require(first is not None, 'Current contract has no attributed clock')
    return first


def select(root, output=None):
    # Metadata-only publication refreshes cannot restart a genuine contract clock.
    ref = subprocess.check_output(['git', 'log', '-1', '--format=%H', 'HEAD', '--', ORIGIN], cwd=root, text=True).strip()
    selected = inspect_publication(root, ref)
    first_ref = first_contract_ref(root, selected['contract_release'])
    first = selected if first_ref == ref else inspect_publication(root, first_ref, historical=True)
    selected.update(budget_start=first['budget_start'], clock_docs_ref=first_ref,
                    clock_producer_origin=first['producer_origin'])
    if output is not None:
        output.write_text(json.dumps(selected, indent=2, sort_keys=True) + '\n')
    return selected


def remote_formal_ref():
    rows = gh_json(f"repos/{REPOSITORY}/commits?sha=main&path={ORIGIN}&per_page=1")
    require(isinstance(rows, list) and len(rows) == 1 and re.fullmatch("[0-9a-f]{40}", str(rows[0].get("sha"))),
            "Latest official publication unavailable")
    return rows[0]["sha"]


def verify_consumer_refs(root, expected_ref, refs, budget_start):
    selected = select(root)
    latest_ref = selected['expected_docs_ref']
    require(remote_formal_ref() == latest_ref, 'Official formal publication changed; reselect before assessment')
    require(selected['budget_start'] == budget_start, 'Genuine contract clock differs')
    proofs = {}
    for ref in set(refs) | {expected_ref}:
        require(re.fullmatch('[0-9a-f]{40}', str(ref)), 'Consumer publication ref is invalid')
        candidate = selected if ref == latest_ref else inspect_publication(root, ref)
        require(subprocess.run(['git', 'merge-base', '--is-ancestor', ref, latest_ref], cwd=root).returncode == 0
                and candidate['contract_release'] == selected['contract_release']
                and candidate['authorization_fingerprint'] == selected['authorization_fingerprint'],
                'Consumer contract or active source authorization differs')
        proofs[ref] = candidate
    # Each graph assessment can be slow. Revalidate active authorization after all
    # inspections, and reject a formal publication advance; code-only main
    # commits do not change remote_formal_ref. Never advance the recorded clock.
    for candidate in proofs.values():
        require(instant(candidate['authorization_expires_at']) > datetime.now(timezone.utc),
                'Consumer source authorization expired during assessment')
    require(instant(selected['authorization_expires_at']) > datetime.now(timezone.utc),
            'Latest source authorization expired during assessment')
    require(remote_formal_ref() == latest_ref, 'Official formal publication changed during assessment')
    return {'status': 'passed', 'expected_docs_ref': expected_ref, 'latest_docs_ref': latest_ref,
            'contract_release': selected['contract_release'], 'budget_start': selected['budget_start'],
            'clock_docs_ref': selected['clock_docs_ref'], 'publications': proofs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('record', 'select'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--run-id')
    parser.add_argument('--attempt', type=int)
    parser.add_argument('--output', type=Path, default=Path('/tmp/publication-selection.json'))
    args = parser.parse_args()
    if args.mode == 'record':
        record(args.root, args.run_id, args.attempt)
    else:
        select(args.root, args.output)


if __name__ == '__main__':
    main()
