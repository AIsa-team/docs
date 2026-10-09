#!/usr/bin/env python3
"""Classify fixed Git changes without granting publication approval."""
import argparse
import json
import os
import subprocess


def requires_artifact_check(paths):
    return any(path.startswith(('openapi/', 'api-reference/', 'zh/api-reference/',
                               'docs/current-source-review-20261009/'))
               or path in ('openapi.yaml', 'docs.json', 'api-reference.mdx',
                           'zh/api-reference.mdx', 'docs/response-source-review-receipts.json') for path in paths)


def git_requires_artifact_check(root, base, head='HEAD'):
    # An initial push or manual run has no safe code-only comparison.
    if not base or set(base) == {'0'}:
        return True
    # Invalid/unavailable revisions fail rather than defaulting to code-only.
    paths = subprocess.check_output(
        ['git', 'diff', '--name-only', base, head], cwd=root, text=True).splitlines()
    return requires_artifact_check(paths)


def verify_required_jobs(needs):
    if needs.get('changes', {}).get('result') != 'success':
        raise ValueError('Change classification did not succeed')
    scope = needs['changes'].get('outputs', {}).get('artifacts')
    if scope not in ('true', 'false'):
        raise ValueError('Change classification has no explicit artifact scope')
    if needs.get('code-contracts', {}).get('result') != 'success':
        raise ValueError('Code contracts did not pass')
    result = needs.get('artifact-contracts', {}).get('result')
    if scope == 'true' and result != 'success':
        raise ValueError('Artifact change requires passed formal readiness')
    if scope == 'false' and result not in ('skipped', 'success'):
        raise ValueError('Unexpected artifact check failure')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='')
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--root', default='.')
    parser.add_argument('--check-jobs', action='store_true', help='Verify GitHub needs results from NEEDS_JSON')
    args = parser.parse_args()
    if args.check_jobs:
        verify_required_jobs(json.loads(os.environ['NEEDS_JSON']))
        print('All applicable contract checks passed')
    else:
        print('artifacts=' + str(git_requires_artifact_check(args.root, args.base, args.head)).lower())
