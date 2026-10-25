"""Observe the exporter's real source assessment without changing its verdict."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--docs-ref', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--diagnostic', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / 'scripts'))
    import schema_input_bundle
    from export_schema_input_bundle import export_reviewed_bundle

    report = {'scope': 'source_assessment_diagnostic_only', 'verdict_changed': False,
              'source_assessment_reached': False, 'sources': []}
    original = schema_input_bundle.source_report

    def observed(*values, **options):
        assessment = original(*values, **options)
        report.update(source_assessment_reached=True, status=assessment['status'],
                      checked_at=assessment['checked_at'], policy_errors=assessment['policy_errors'])
        scope = assessment['source_scope']['sources']
        for name, row in sorted(assessment['sources'].items()):
            if row['freshness'] == 'fresh' and not row['policy_errors']:
                continue
            scoped = bool(scope.get(name) and not row['policy_errors'] and row['review_due_at'])
            report['sources'].append({'name': name, 'global': not scoped,
                **{key: row.get(key) for key in ('status', 'freshness', 'policy', 'policy_errors',
                    'source_hash', 'policy_revision', 'last_successful_review_at',
                    'next_acquisition_due_at', 'review_due_at')}})
        report['scoped_failures'] = assessment['scoped_failures']
        return assessment

    schema_input_bundle.source_report = observed
    try:
        result = export_reviewed_bundle(args.repo, args.docs_ref, args.output)
        report['export_passed'] = True
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        report.update(export_passed=False, exception_type=type(error).__name__)
        print('Schema input export rejected: ' + str(error), file=sys.stderr)
        return 1
    finally:
        schema_input_bundle.source_report = original
        args.diagnostic.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print('Exact source assessment: ' + json.dumps(report, sort_keys=True), file=sys.stderr)


if __name__ == '__main__':
    raise SystemExit(main())
