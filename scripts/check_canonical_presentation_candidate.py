#!/usr/bin/env python3
"""Check presentation-only changes through an isolated canonical projection."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from canonical_import import assess_canonical_candidate
from contract_change_scope import git_changed_paths, requires_artifact_check
from fetch_runtime_release import PublicReader
from generate_payment_discovery import candidate as payment_catalog
from refresh_payment_publication import ChallengeReader, ORIGIN, refresh
from runtime_publication import stage_canonical, verified_mode
from schema_input_bundle import canonical, require
from validate_runtime_api_reference_slugs import validate as validate_pages


def presentation_only(paths):
    artifacts = [name for name in paths if requires_artifact_check([name])]
    return bool(artifacts) and all(
        name.startswith(('api-reference/', 'zh/api-reference/')) and name.endswith('.mdx') or
        name in {'docs.json', 'api-reference.mdx', 'zh/api-reference.mdx', 'openapi/nav-groups.json',
                  'docs/current-source-review-20261009/merged-source-reviews.json'}
        for name in artifacts)


def checked_scope(root, base):
    require(re.fullmatch(r'[0-9a-f]{40}', str(base)) is not None, 'Full candidate base revision required')
    paths = git_changed_paths(root, base)
    require(paths is not None and presentation_only(paths),
            'Canonical presentation projection cannot accept schema or publication-output changes')
    subprocess.run(['git', 'merge-base', '--is-ancestor', base, 'HEAD'], cwd=root, check=True)
    require(subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], cwd=root).returncode == 0,
            'Candidate tracked bytes changed after checkout')
    untracked = subprocess.check_output(
        ['git', 'ls-files', '--others', '--exclude-standard'], cwd=root, text=True).splitlines()
    require(not any(requires_artifact_check([name]) for name in untracked),
            'Candidate has untracked publication inputs')
    return paths


def observe_payment(root, facts):
    deadline = time.monotonic() + 180
    return refresh(root, facts, PublicReader(ORIGIN, deadline), ChallengeReader(deadline))


def assess(root, facts, *, base, baseline, payment_observer=observe_payment):
    root, facts = Path(root).resolve(), Path(facts).resolve()
    paths = checked_scope(root, base)
    require(verified_mode(facts) == 'canonical', 'Canonical Runtime acquisition required')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    receipts = (root / '.cache/source-reviews.json').read_bytes()
    with tempfile.TemporaryDirectory(prefix='canonical-presentation-') as directory:
        projected = Path(directory) / 'candidate'
        subprocess.run(['git', 'worktree', 'add', '--quiet', '--detach', str(projected), head],
                       cwd=root, check=True)
        try:
            cache = projected / '.cache/source-reviews.json'
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(receipts)
            staged = stage_canonical(projected, facts, baseline=baseline, write=True)
            require(staged['status'] == 'passed', 'Canonical presentation stage failed')
            payment = payment_observer(projected, facts)
            require(payment['status'] == 'passed', 'Payment observation failed')
            (projected / 'discovery/openapi.json').write_text(
                json.dumps(payment_catalog(projected), indent=2, ensure_ascii=True) + '\n')
            require(not validate_pages(projected, generated_only=True), 'Generated page references differ')
            report = assess_canonical_candidate(projected, root, projected, facts,
                previous_ref=staged['previous_formal_ref'], source_receipts=cache)
            # This validates the future generated graph, not the committed PR
            # as a formal publication. The sole publisher still assesses,
            # exports and performs its own fresh acquisition and main CAS.
            report['presentation_candidate'] = {'base_revision': base, 'head_revision': head,
                'changed_paths': paths, 'projected_files': staged['projected_files'],
                'scope': 'presentation_only_isolated_projection_not_formal_publication'}
            return report
        finally:
            subprocess.run(['git', 'worktree', 'remove', '--force', str(projected)], cwd=root, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('scope', 'assess'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--base', required=True)
    parser.add_argument('--facts-dir', type=Path)
    parser.add_argument('--baseline-ref')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.action == 'scope':
        paths = git_changed_paths(args.root, args.base) if re.fullmatch(r'[0-9a-f]{40}', args.base) else None
        print(str(paths is not None and presentation_only(paths)).lower())
        return 0
    if not all((args.facts_dir, args.baseline_ref, args.report)):
        parser.error('Assessment requires facts, baseline and report')
    try:
        report = assess(args.root, args.facts_dir, base=args.base, baseline=args.baseline_ref)
        status = 0 if report['status'] == 'passed' else 1
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        report = {'status': 'not_assessed', 'evaluation': 'canonical_presentation_candidate', 'error': str(exc)}
        status = 3
    args.report.write_bytes(canonical(report) + b'\n')
    print(json.dumps({key: report.get(key) for key in ('status', 'evaluation')}))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
