"""Validate the maintenance identities of the November supplier response sources."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import digest
from source_governance import observation, policy_errors, policy_revision


ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    'fred-official.json',
    'tikhub.json',
    'response-duffel-flights-get-offer-request-20261110.json',
    'response-duffel-flights-post-create-20261110.json',
    'response-duffel-stays-get-search-rates-20261110.json',
    'response-duffel-stays-get-search-result-20261110.json',
    'response-financial-analyst-estimates.json',
    'response-pinterest-get-boards-pins.json',
    'response-pinterest-get-pins.json',
    'response-pinterest-get-profiles-boards.json',
    'response-reddit-get-posts-comments.json',
    'response-reddit-get-subreddits-posts.json',
    'response-reddit-get-subreddits-search.json',
    'response-reddit-get-subreddits.json',
    'response-similarweb-conversion-rates-aggregated.json',
    'response-similarweb-conversion-rates.json',
    'response-similarweb-keyword-overview.json',
    'response-similarweb-segment-traffic-sources.json',
    'response-similarweb-traffic-demographics-aggregated.json',
)


class SupplierResponseSourceGovernanceTests(unittest.TestCase):
    def documents(self):
        for filename in SOURCES:
            yield filename, json.loads((ROOT / 'openapi/upstream' / filename).read_text())

    def test_sources_have_valid_policy_bound_to_their_own_authority(self):
        for filename, document in self.documents():
            with self.subTest(source=filename):
                source = document['info']['x-aisa-source']
                self.assertEqual(policy_errors(source), [])
                self.assertEqual(source['policy_revision'], policy_revision(source))

    def test_content_hash_identifies_the_published_source_contract(self):
        # These projections follow the importer convention: hash the complete
        # document with only its maintenance/provenance metadata removed. Parent
        # documents and official page hashes have separate evidence fields.
        for filename, document in self.documents():
            with self.subTest(source=filename):
                source = document['info'].pop('x-aisa-source')
                self.assertEqual(source['content_hash'], digest(document))

    def test_policy_declarations_do_not_claim_a_successful_review(self):
        for filename, document in self.documents():
            with self.subTest(source=filename):
                source = document['info']['x-aisa-source']
                before = copy.deepcopy(source)
                result = observation(source, {}, datetime(2026, 11, 11, tzinfo=timezone.utc))
                self.assertEqual(result['freshness'], 'unknown')
                self.assertIsNone(result['last_successful_review_at'])
                self.assertIsNone(result['evidence'])
                self.assertNotIn('last_successful_review_at', source)
                self.assertEqual(source, before)


if __name__ == '__main__':
    unittest.main()
