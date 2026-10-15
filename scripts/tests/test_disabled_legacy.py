import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_registry import disabled_legacy_paths

FIXTURE = Path(__file__).parent / 'fixtures/disabled-twitter-spaces.json'
PATH = '/apis/v1/twitter/spaces/detail'


class DisabledLegacyAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())
        self.registry = self.fixture['registry']
        self.index = self.fixture['runtime_index']

    def projected(self, facts=None):
        return disabled_legacy_paths(self.registry, self.index, facts or {})

    def test_real_runtime_tombstone_binds_only_registered_owner_and_legacy_source(self):
        projected = self.projected()
        self.assertIn(PATH, projected['twitter-trend'])
        self.assertIn(PATH, projected['twitter'])
        self.assertNotIn('unregistered-twitter-copy', projected)

    def test_absent_owner_or_absent_tombstone_has_no_authority(self):
        self.registry['providers'] = {}
        self.assertEqual(self.projected(), {})
        self.registry = self.fixture['registry'] = {'providers': {'twitter': {'legacy_sources': ['twitter-trend']}}}
        self.index['coverage']['excluded_endpoints'] = []
        self.assertEqual(self.projected(), {})

    def test_other_catalog_or_non_disabled_status_does_not_disable(self):
        row = self.index['coverage']['excluded_endpoints'][0]
        row['provider'] = 'aisa-twitter'
        self.assertEqual(self.projected(), {})
        row['provider'] = 'twitter'
        for status in ['enabled', 'pending', None, True]:
            row['status'] = status
            self.assertEqual(self.projected(), {})

    def test_group_membership_is_explicit_not_inferred_from_url_prefix(self):
        self.registry = {'providers': {'social': {'group': ['twitter', 'other'], 'legacy_sources': ['twitter-trend']}}}
        self.assertIn(PATH, self.projected()['twitter-trend'])
        self.registry['providers']['social']['group'] = ['other']
        self.assertEqual(self.projected(), {})

    def test_ambiguous_legacy_owner_does_not_disable(self):
        self.registry['providers']['other'] = {'legacy_sources': ['twitter-trend']}
        self.assertNotIn('twitter-trend', self.projected())

    def test_projected_pending_or_conflicting_index_row_blocks_path(self):
        for location in ['projected_endpoints', 'pending_endpoints', 'excluded_endpoints']:
            with self.subTest(location=location):
                index = copy.deepcopy(self.index)
                row = {'provider': 'another-owner', 'path': PATH, 'status': 'enabled'}
                target = index if location == 'pending_endpoints' else index['coverage']
                target.setdefault(location, []).append(row)
                self.assertEqual(disabled_legacy_paths(self.registry, index, {}), {})

    def test_active_or_undeclared_runtime_operation_blocks_even_other_method_or_catalog(self):
        for method in ['get', 'post', 'x-aisa-any']:
            for status in ['enabled', None]:
                fact = {'servers': [{'url': 'https://api.aisa.one/apis/v1'}],
                        'paths': {'/twitter/spaces/detail': {method: {'x-aisa-status': status}}}}
                self.assertEqual(self.projected({'another-owner': fact}), {})

    def test_bad_or_different_public_path_never_matches_exact_route(self):
        row = self.index['coverage']['excluded_endpoints'][0]
        for path in ['/twitter/spaces/detail', PATH + '?query=1', '/apis/v1/twitter/../spaces/detail',
                     '/apis/v1/twitter//spaces/detail', 'https://api.aisa.one' + PATH, '/apis/v1/twitter/%73paces/detail']:
            row['path'] = path
            self.assertEqual(self.projected(), {})
        row['path'] = PATH + '-other'
        self.assertNotIn(PATH, self.projected().get('twitter-trend', set()))


if __name__ == '__main__':
    unittest.main()
