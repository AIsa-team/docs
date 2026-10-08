"""Pure fixed-version selection and deadline rules; never schedules or publishes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

CANDIDATE_BUDGET = 3600
CONSUMER_BUDGET = 14400


def validate_config(config):
    exact = {'candidate_budget_seconds': CANDIDATE_BUDGET,
             'consumer_budget_seconds': CONSUMER_BUDGET,
             'candidate_cron': '*/10 * * * *', 'monitor_cron': '35 * * * *'}
    for name, value in exact.items():
        if config.get(name) != value:
            raise ValueError('activation plan differs from frozen W0 threshold: ' + name)
    for name, cap in [('candidate_interval_seconds', 600), ('monitor_interval_seconds', 3600),
                      ('version_cache_max_seconds', 300), ('automatic_acquisition_interval_seconds', 86400)]:
        value = config.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= cap:
            raise ValueError('invalid activation cadence/cache cap: ' + name)
    if not isinstance(config.get('activation_enabled'), bool):
        raise ValueError('activation_enabled must be explicit')
    return config


def select_revision(event, published_ref, published_hash, dispatch_ref=None, dispatch_hash=None):
    """An omitted dispatch uses the same immutable published source next cycle.

    This selects an input, not approval. Callers must still verify main
    reachability, all exact bytes, and an attributable formal producer receipt.
    """
    if event not in ('repository_dispatch', 'schedule', 'workflow_dispatch'):
        raise ValueError('unsupported selection event')
    ref = dispatch_ref if event == 'repository_dispatch' else published_ref
    digest = dispatch_hash if event == 'repository_dispatch' else published_hash
    if not re.fullmatch(r'[0-9a-f]{40}', str(ref)) or not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
        raise ValueError('selected publication requires a full immutable SHA and exact content hash')
    return {'docs_ref': ref, 'openapi_sha256': digest, 'event': event,
            'publication_verified': False, 'requires_formal_receipt': True}


def deadline(start, phase, now=None):
    if phase not in ('candidate', 'convergence'):
        raise ValueError('unknown budget phase')
    began = datetime.fromisoformat(start.replace('Z', '+00:00'))
    if began.tzinfo is None:
        raise ValueError('budget start needs an explicit timezone')
    now = now or datetime.now(timezone.utc)
    elapsed = (now - began).total_seconds()
    if elapsed < 0:
        raise ValueError('budget start is in the future')
    cap = CANDIDATE_BUDGET if phase == 'candidate' else CONSUMER_BUDGET
    return {'budget_start': began.isoformat(), 'phase': phase, 'elapsed_seconds': elapsed,
            'budget_seconds': cap, 'deadline_breached': elapsed > cap,
            'status': 'failed' if elapsed > cap else 'within_budget'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('contract_activation.json'))
    parser.add_argument('--event', choices=('repository_dispatch', 'schedule', 'workflow_dispatch'))
    parser.add_argument('--published-ref')
    parser.add_argument('--published-hash')
    parser.add_argument('--dispatch-ref')
    parser.add_argument('--dispatch-hash')
    args = parser.parse_args()
    plan = validate_config(json.loads(args.config.read_text()))
    result = {'activation_enabled': plan['activation_enabled'], 'plan': plan,
              'scope': 'configuration and fixed input selection only; no refresh, scheduling or publication'}
    if args.event:
        result['selection'] = select_revision(args.event, args.published_ref, args.published_hash,
                                               args.dispatch_ref, args.dispatch_hash)
    print(json.dumps(result, indent=2))
