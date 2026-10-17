#!/usr/bin/env python3
"""Consume exact operator-authorized source-input evidence, never formal output.

The private Services workflow run and immutable artifact are authenticated using
the existing scoped CI Read App. Ordinary formal freshness acquisition is not
changed. No unsigned public blob or stale public native document is accepted.
"""
import argparse
import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import urllib.parse
import urllib.request
import zipfile

from contract_change_scope import git_changed_paths, is_reviewed_input_change
from export_schema_input_bundle import export_reviewed_bundle
from schema_input_bundle import canonical, load_bundle, require, sha, strict_json, INPUT_CONTEXT_MEMBER
from source_governance import source_report
from publication_origin import inspect_publication

SCOPE = 'authenticated_current_source_input_qualification_only_not_formal_publication_or_promotion'
REPOSITORY = 'AIsa-team/AIsaServices'
WORKFLOW = '.github/workflows/api-contract-e2e.yml'
HEX40 = re.compile('[0-9a-f]{40}')
HEX64 = re.compile('[0-9a-f]{64}')
ID = re.compile('[1-9][0-9]{0,23}')
MAX_ARCHIVE = 135 << 20


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, 'Timezone required')
    return result


def binding_value(raw, event, now):
    if not raw or 'pull_request' not in event:
        return None
    value = strict_json(raw)
    keys = {'schema_version', 'scope', 'head_revision', 'base_revision', 'candidate_compiler_inputs',
            'source_api_revision', 'source_export_revision', 'qualifier_revision', 'run_id',
            'run_attempt', 'artifact_id', 'archive_sha256', 'issued_at', 'expires_at'}
    require(isinstance(value, dict) and set(value) == keys and type(value['schema_version']) is int and
            value['schema_version'] == 1 and value['scope'] == SCOPE, 'Invalid closed recovery binding')
    pr = event['pull_request']
    if pr['head']['sha'] != value['head_revision']:
        return None
    require(pr['head']['repo']['full_name'] == 'AIsa-team/docs' and
            pr['base']['repo']['full_name'] == 'AIsa-team/docs' and pr['base']['ref'] == 'main' and
            pr['base']['sha'] == value['base_revision'], 'Recovery binding differs from exact PR base')
    for key in ('head_revision', 'base_revision', 'source_api_revision', 'source_export_revision', 'qualifier_revision'):
        require(isinstance(value[key], str) and HEX40.fullmatch(value[key]), 'Full revision required')
    require(type(value['run_attempt']) is int and value['run_attempt'] > 0 and
            all(isinstance(value[key], str) and ID.fullmatch(value[key]) for key in ('run_id', 'artifact_id')) and
            isinstance(value['archive_sha256'], str) and HEX64.fullmatch(value['archive_sha256']), 'Invalid exact run/artifact pins')
    inputs = value['candidate_compiler_inputs']
    require(isinstance(inputs, dict) and set(inputs) == {'protocol_version', 'docs_ref', 'composer_revision',
            'source_manifest_sha256', 'bundle_manifest_sha256'} and inputs['protocol_version'] == 'aisa-runtime-canonical-v1' and
            inputs['docs_ref'] == value['head_revision'] and HEX40.fullmatch(inputs['composer_revision']) and
            all(HEX64.fullmatch(inputs[key]) for key in ('source_manifest_sha256', 'bundle_manifest_sha256')),
            'Invalid independently pinned candidate inputs')
    issued, expires = timestamp(value['issued_at']), timestamp(value['expires_at'])
    require(issued <= now < expires and 0 < (expires - issued).total_seconds() <= 3600, 'Recovery binding expired')
    return value


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, url):
        require(urllib.parse.urlsplit(url).scheme == 'https', 'Non-HTTPS artifact redirect')
        result = super().redirect_request(req, fp, code, msg, headers, url)
        if urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(url).netloc:
            result.remove_header('Authorization')
        return result


def reader(token):
    require(bool(token), 'Scoped CI Read App token required')
    opener = urllib.request.build_opener(Redirect())
    def read(path, limit=2 << 20):
        request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/' + path,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'})
        with opener.open(request, timeout=60) as response:
            raw = response.read(limit + 1)
        require(len(raw) <= limit, 'GitHub response exceeds bound')
        return raw
    return read


def verify_producer(binding, read):
    run = strict_json(read('actions/runs/' + binding['run_id']))
    require(str(run['id']) == binding['run_id'] and run['run_attempt'] == binding['run_attempt'] and
            run['head_sha'] == binding['qualifier_revision'] and run['path'] == WORKFLOW and
            run['event'] == 'workflow_dispatch' and run['repository']['full_name'] == REPOSITORY and
            run['status'] == 'completed' and run['conclusion'] == 'success', 'Trusted qualifier run differs')
    jobs = strict_json(read('actions/runs/' + binding['run_id'] + '/attempts/' + str(binding['run_attempt']) + '/jobs'))['jobs']
    for name in ('contracts', 'Durable contract publication on MySQL', 'source-input-recovery-qualification'):
        found = [job for job in jobs if job['name'] == name]
        require(len(found) == 1 and found[0]['conclusion'] == 'success', 'Qualifier required job did not pass')
    artifact = strict_json(read('actions/artifacts/' + binding['artifact_id']))
    require(str(artifact['id']) == binding['artifact_id'] and artifact['expired'] is False and
            artifact['name'] == 'source-input-qualification-' + binding['run_id'] + '-' + str(binding['run_attempt']) and
            str(artifact['workflow_run']['id']) == binding['run_id'] and
            artifact['workflow_run']['head_sha'] == binding['qualifier_revision'] and
            type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE,
            'Qualification artifact metadata differs')
    archive = read('actions/artifacts/' + binding['artifact_id'] + '/zip', MAX_ARCHIVE)
    require(sha(archive) == binding['archive_sha256'], 'Qualification archive differs from operator pin')
    expected = {'qualification.json'} | {phase + '/' + name
        for phase in ('source-before', 'source-after')
        for name in {'observations.json'} | {node + '/' + part for node in ('api-a', 'api-b')
            for part in ('source.json', 'snapshot.json', 'receipt.json')}}
    with zipfile.ZipFile(io.BytesIO(archive)) as packet:
        files = [item for item in packet.infolist() if not item.is_dir()]
        require(len(files) == len(expected) and {item.filename for item in files} == expected and
                sum(item.file_size for item in files) <= 270 << 20 and
                all(not stat.S_ISLNK(item.external_attr >> 16) and not item.flag_bits & 1 and
                    0 < item.file_size <= 66 << 20 for item in files), 'Unexpected qualification members')
        info = packet.getinfo('qualification.json')
        require(0 < info.file_size <= 4 << 20, 'Qualification metadata exceeds bound')
        with packet.open(info) as source:
            report_raw = source.read((4 << 20) + 1)
        require(len(report_raw) == info.file_size, 'Qualification metadata truncated')
    # Independently resolve the old source lock from the selected exporter Git
    # commit. The API's self-reported input pins are not their own authority.
    lock = strict_json(read('contents/packages/apicontract/composer-inputs.lock.json?ref=' + binding['source_export_revision']))
    require(lock['encoding'] == 'base64', 'Unexpected source lock encoding')
    original_inputs = strict_json(base64.b64decode(lock['content']))['compiler_inputs']
    return strict_json(report_raw), original_inputs, run


def verify_report(binding, report, original_inputs, now):
    require(report['schema_version'] == 1 and report['status'] == 'passed' and report['scope'] == SCOPE and
            report['workflow_revision'] == binding['qualifier_revision'] and report['run_id'] == binding['run_id'] and
            report['run_attempt'] == binding['run_attempt'] and report['source_unchanged_across_qualification'] is True and
            report['production_database_writes'] == 0 and report['provider_calls'] == 0 and
            report['formal_publication_or_promotion'] is False, 'Qualification scope/provenance differs')
    request = report['request']
    require(request['scope'] == SCOPE and all(request[key] == binding[key] for key in
            ('head_revision', 'base_revision', 'candidate_compiler_inputs', 'source_api_revision', 'source_export_revision')),
            'Qualified input differs from exact authorized candidate')
    started, completed = timestamp(report['started_at']), timestamp(report['completed_at'])
    require(timestamp(request['issued_at']) <= started <= completed <= now and
            completed < timestamp(request['expires_at']) and
            now < timestamp(request['expires_at']) and (now - completed).total_seconds() <= 900,
            'Input qualification is overdue or outside its authorized interval')
    source = report['source']
    require(source['compiler_revision'] == binding['source_api_revision'] and source['compiler_inputs'] == original_inputs and
            type(source['generation']) is int and source['generation'] >= 0 and HEX64.fullmatch(source['source_digest']),
            'Qualified source differs from independent old API/compiler pins')
    require(report['source_governance']['status'] == 'passed' and not report['source_governance']['policy_errors'] and
            all(row['freshness'] == 'fresh' for row in report['source_governance']['sources'].values()),
            'Qualified source policy/receipts did not pass')
    require(report['input_bundle']['docs_ref'] == binding['head_revision'] and
            report['input_bundle']['manifest_sha256'] == binding['candidate_compiler_inputs']['bundle_manifest_sha256'] and
            report['composition']['scope'] == 'existing_composer_offline_shadow_only_not_formal_publication' and
            report['composition']['summary']['status'] == 'passed', 'Qualified full Composer result differs')


def final_evidence(binding, report, original_inputs, event, view, saved, clock=None):
    finished = (clock or (lambda: datetime.now(timezone.utc)))()
    selected = binding_value(canonical(binding), event, finished)
    require(selected == binding, 'Final input authorization differs or expired')
    verify_report(binding, report, original_inputs, finished)
    governance = source_report(view, saved['receipts'], checked_at=finished, attempts=saved.get('attempts', {}))
    require(governance['status'] == 'passed' and not governance['policy_errors'], 'Current source input authorization failed')
    return governance, finished


def assess(root, output, binding, event, read, now, clock=None):
    require(not output.exists() and output.parent.is_dir(), 'Output must be new')
    paths = git_changed_paths(root, binding['base_revision'], binding['head_revision'])
    require(paths is not None and is_reviewed_input_change(paths), 'Recovery accepts only a closed source-only PR')
    report, original_inputs, run = verify_producer(binding, read)
    verify_report(binding, report, original_inputs, now)
    require(report['request']['docs_pr'] == event['pull_request']['number'], 'Qualified PR number differs')
    require(report['changed_paths'] == sorted(paths), 'Qualified changed-path intent differs')
    subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor',
                    binding['candidate_compiler_inputs']['composer_revision'], binding['base_revision']],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    output.mkdir()
    result = export_reviewed_bundle(root, binding['head_revision'], output / 'bundle')
    inputs = binding['candidate_compiler_inputs']
    require(result['manifest_sha256'] == inputs['bundle_manifest_sha256'], 'Actual R bundle differs from qualification')
    bundle = load_bundle(output / 'bundle', expected_manifest_sha256=inputs['bundle_manifest_sha256'], expected_docs_ref=inputs['docs_ref'])
    recipe = strict_json(bundle.contents[INPUT_CONTEXT_MEMBER])
    # The new source-only qualifier does not replace the original independent
    # Actions producer validation of historical formal context F.
    previous = inspect_publication(root, recipe['historical_formal_ref'], historical=True)
    require(previous['expected_docs_ref'] == recipe['historical_formal_ref'], 'Historical formal publisher differs')
    view = output / 'governance'; view.mkdir()
    for name, raw in bundle.contents.items():
        if name.startswith('input/'):
            path = view / name.removeprefix('input/'); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    saved = strict_json(bundle.contents['evidence/source-receipts.json'])
    # Download, Git export and historical producer authentication can take many
    # minutes. Recheck all real clocks only after those operations, immediately
    # before issuing the passed receipt; the entry-point clock is not reused.
    governance, finished = final_evidence(binding, report, original_inputs, event, view, saved, clock)
    receipt = {'schema_version': 1, 'status': 'passed', 'scope': SCOPE, 'input': result,
        'checked_at': finished.isoformat(),
        'changed_paths': sorted(paths), 'source_governance': governance, 'qualified_source': report['source'],
        'historical_formal_provenance': previous,
        'qualifier': {'repository': REPOSITORY, 'workflow': WORKFLOW, 'revision': binding['qualifier_revision'],
                      'run_id': binding['run_id'], 'run_attempt': binding['run_attempt'], 'artifact_id': binding['artifact_id'],
                      'archive_sha256': binding['archive_sha256']},
        'freshness_scope': 'authenticated_source_at_qualification_only_not_CI_time_current_or_formal_freshness'}
    (output / 'receipt.json').write_bytes(canonical(receipt))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--select', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        now = datetime.now(timezone.utc)
        event = strict_json(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
        binding = binding_value(os.environ.get('OPERATOR_INPUT_RECOVERY_BINDING', ''), event, now)
        if args.select:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('selected=' + ('true' if binding is not None else 'false') + '\n')
        else:
            require(binding is not None and args.output is not None, 'Exact source-input recovery authorization required')
            assess(Path.cwd(), args.output, binding, event, reader(os.environ.get('GH_TOKEN', '')), now)
            print('Exact authenticated source-input qualification passed; no formal freshness granted')
    except Exception as exc:
        parser.exit(1, 'Trusted source-input recovery rejected: ' + type(exc).__name__ + '\n')
