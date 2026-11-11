"""Prove the response amendment is reversible without altering older reviews."""
import copy
import json
from pathlib import Path
import unittest

from compose_openapi import compose, digest, resolve
from runtime_registry import public_mirror_index
from source_governance import policy_errors
from test_runtime_contracts import facts, operation


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / 'docs/current-source-review-20261110/tikhub-response-amendment.json'
LOCATIONS = {
    ('paths', '/tikhub/douyin/creator_v2/fetch_item_list_download', 'post', 'responses', '200'),
    ('paths', '/tikhub/youtube/web/get_trending_videos', 'get', 'responses', '200'),
}


def undo_response_amendment(test, document, source):
    """Verify the current content, then undo only the two reviewed response roots.

    ``document`` has its info.x-aisa-source removed, matching the content-hash
    convention used by the historical region and nullability reviews.
    """
    review = json.loads(REVIEW.read_text())
    test.assertEqual(source['content_hash'], digest(document))
    test.assertEqual(source['content_hash'], review['source_content_hash'])
    test.assertEqual(source['prior_source'], review['prior_source'])
    test.assertEqual(len(review['edits']), len(LOCATIONS))
    test.assertEqual({tuple(edit['pointer']) for edit in review['edits']}, LOCATIONS)
    for edit in reversed(review['edits']):
        parent = document
        for key in edit['pointer'][:-1]:
            parent = parent[key]
        test.assertEqual(parent[edit['pointer'][-1]], edit['after'])
        test.assertEqual(digest(edit['after']), edit['after_sha256'])
        test.assertEqual(digest(edit['before']), edit['before_sha256'])
        parent[edit['pointer'][-1]] = copy.deepcopy(edit['before'])
    test.assertEqual(digest(document), review['unchanged_declarations_sha256'])
    test.assertEqual(digest(document), review['prior_source']['content_hash'])
    return copy.deepcopy(review['prior_source'])


class TikHubResponseAmendmentTests(unittest.TestCase):
    def test_only_two_response_roots_change_and_previous_source_clock_is_preserved(self):
        review = json.loads(REVIEW.read_text())
        document = json.loads((ROOT / review['source_file']).read_text())
        source = document['info'].pop('x-aisa-source')
        prior = undo_response_amendment(self, document, source)
        self.assertEqual(policy_errors(source), [])
        self.assertFalse(review['whole_source_maintenance_clock_advanced'])
        for field in ('kind', 'url', 'fetched_at', 'owner', 'refresh_policy',
                      'review_period_days', 'policy_revision'):
            self.assertEqual(source[field], prior[field])
        # The predecessor is exactly the separately reviewed nullable amendment.
        self.assertEqual(prior['converter'], 'reviewed-official-tikhub-nullability-amendment@1')
        self.assertEqual(prior['content_hash'], 'sha256:7f2beb52342a3942a5d55021fdf8ae5b8755502561a8fcb706224876460bd4d8')

    def test_evidence_does_not_promote_404_to_verified_success(self):
        review = json.loads(REVIEW.read_text())
        edits = {edit['pointer'][2]: edit for edit in review['edits']}
        self.assertEqual(edits['post']['evidence_status'], 'explicit_endpoint_media_type')
        self.assertIn('Content-Type: application/vnd.ms-excel', edits['post']['before']['description'])
        self.assertEqual(edits['get']['evidence_status'], 'pending_success_payload_unverified')
        self.assertNotIn('content', edits['get']['before'])
        self.assertIn('unverified', edits['get']['after']['description'])
        self.assertNotIn('content', edits['get']['after'])
        self.assertEqual(edits['get']['live_check']['run_status'], 404)
        self.assertIs(edits['get']['live_check']['success_payload_verified'], False)

    def test_existing_passthrough_composition_consumes_the_amendment(self):
        review = json.loads(REVIEW.read_text())
        mirrors = public_mirror_index(ROOT)
        for edit in review['edits']:
            source_path, method = edit['pointer'][1:3]
            public_path = '/apis/v1' + source_path
            runtime = facts('provider', method)
            op = operation(runtime)
            op.update(parameters=[], **{
                'x-aisa-passthrough': True,
                'x-aisa-query-policy': {'request_wins': True},
                'x-aisa-upstream-path': source_path.replace('/tikhub/', '/api/v1/', 1),
            })
            runtime['paths'] = {public_path: {method: op}}
            document, pending = compose(runtime, public_mirrors=mirrors)
            with self.subTest(method=method):
                self.assertFalse(pending)
                actual = document['paths'][public_path][method]
                self.assertNotIn('x-aisa-response-passthrough', actual)
                self.assertNotIn('x-aisa-response-upstream-origin-sha256', actual)
                response = resolve(actual['responses']['200'], document)
                if method == 'post':
                    self.assertNotIn('x-aisa-response-pending', actual)
                    self.assertEqual(actual['x-aisa-response-source']['source']['content_hash'],
                                     review['source_content_hash'])
                    self.assertEqual(response['content']['application/vnd.ms-excel']['schema'],
                                     {'type': 'string', 'format': 'binary'})
                else:
                    self.assertIn('x-aisa-response-pending', actual)
                    self.assertNotIn('x-aisa-response-source', actual)
                    self.assertEqual(actual['x-aisa-response-pending']['statuses'], ['200'])
                    self.assertEqual(response.get('content', {}).get('application/json', {}).get('schema', {}), {})
                    generic, unresolved = compose(runtime, public_mirrors=mirrors, unreviewed_runtime=True)
                    self.assertFalse(unresolved)
                    generic_op = generic['paths'][public_path][method]
                    self.assertEqual(generic_op['responses']['200']['content']['application/json']['schema'], {})
                    self.assertEqual(generic_op['x-aisa-review']['response'], 'generic')
                    self.assertNotIn('x-aisa-response-source', generic_op)


if __name__ == '__main__':
    unittest.main()
