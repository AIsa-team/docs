import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from human_api_retirements import apply_retirements
from sync_prod_runtime_docs import preserve_navigation


class RetirementTests(unittest.TestCase):
    def test_generated_alias_stays_archived_across_repeated_full_generation(self):
        from test_full_registry import FullRegistryTests, contract
        fixture = FullRegistryTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        root = fixture.root
        document = contract('aisa-twitter', method='post')
        operation = next(iter(document['paths'].values()))['post']
        operation['operationId'] = 'postTwitter'
        route = '/apis/v1/twitter/post_twitter'
        document['paths'] = {route: {'post': operation}}
        fixture.sources({'aisa-twitter': document})
        (root / 'docs').mkdir()
        policy = {'scope': 'human_presentation_only', 'formal_publication': False,
                  'guide': 'resources/twitter-migration', 'operations': [{
                      'method': 'POST', 'path': route,
                      'page': 'api-reference/twitter/legacy-post', 'title': 'Post'}]}
        (root / 'docs/human-api-retirements.json').write_text(json.dumps(policy))
        for iteration in range(3):
            fixture.publish(fixture.pull()[0])
            snapshot = {p.relative_to(root).as_posix(): p.read_text()
                        for p in root.rglob('*.mdx')}
            for prefix in ('', 'zh/'):
                alias = snapshot[prefix + 'api-reference/aisa-twitter/postTwitter.mdx']
                self.assertIn('x-aisa-human-retirement: true', alias)
                self.assertNotIn('openapi:', alias)
                self.assertNotIn('aisa-contract-details', alias)
            if iteration:
                self.assertEqual(snapshot, first)
            first = snapshot

    def test_regenerated_legacy_pages_and_preserved_navigation_cannot_reactivate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'docs').mkdir()
            row={'method':'POST','path':'/apis/v1/twitter/post_twitter','page':'api-reference/twitter/post_twitter-post-twitter','title':'Post'}
            config={'scope':'human_presentation_only','formal_publication':False,'guide':'resources/twitter-migration','operations':[row]}
            (root/'docs/human-api-retirements.json').write_text(json.dumps(config))
            navigation={'languages':[{'language':'en','tabs':[{'tab':'API Reference','groups':[{'group':'X','pages':[row['page'],'api-reference/twitter/readonly']}]}]}]}
            (root/'docs.json').write_text(json.dumps({'navigation':preserve_navigation(navigation,navigation)}))
            (root/'openapi').mkdir();(root/'openapi/aisa-twitter.json').write_bytes(b'original formal bytes')
            (root/'reference-contracts').mkdir();(root/'reference-contracts/aisa-twitter.json').write_bytes(b'original human history bytes')
            newpage=root/'api-reference/aisa-twitter/new-generated-name.mdx'
            changes={newpage:'---\nopenapi: "openapi/aisa-twitter.json POST /apis/v1/twitter/post_twitter"\n---\nAvailability: enabled\ncurl -X POST old-endpoint'}
            apply_retirements(root,changes)
            self.assertNotIn('openapi:',changes[newpage]);self.assertNotIn('curl',changes[newpage])
            self.assertIn('retired',changes[newpage])
            self.assertIn('重新授权',changes[root/('zh/'+row['page']+'.mdx')])
            nav=json.loads(changes[root/'docs.json'])['navigation']
            self.assertNotIn(row['page'],json.dumps(nav));self.assertIn('api-reference/twitter/readonly',json.dumps(nav))
            self.assertEqual((root/'openapi/aisa-twitter.json').read_bytes(),b'original formal bytes')
            self.assertEqual((root/'reference-contracts/aisa-twitter.json').read_bytes(),b'original human history bytes')
            self.assertTrue(all(p==root/'docs.json' or p.suffix=='.mdx' for p in changes))
            before=dict(changes);apply_retirements(root,changes);self.assertEqual(before,changes)

    def test_same_action_from_other_provider_and_v2_path_are_not_retired(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'docs').mkdir()
            (root/'docs/human-api-retirements.json').write_text(json.dumps({'scope':'human_presentation_only','formal_publication':False,'guide':'resources/twitter-migration','operations':[]}))
            page=root/'api-reference/twitter/other.mdx';text='---\nopenapi: "reference-contracts/twitter.json POST /apis/v1/twitter/create_tweet_v2"\n---\n'
            changes={page:text};apply_retirements(root,changes);self.assertEqual(changes,{page:text})

    def test_cannot_claim_formal_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'docs').mkdir()
            (root/'docs/human-api-retirements.json').write_text('{"scope":"human_presentation_only","formal_publication":true}')
            with self.assertRaises(ValueError):apply_retirements(root,{})

    def test_policy_with_per_row_replacement_links_each_language(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'docs').mkdir()
            twitter={'scope':'human_presentation_only','formal_publication':False,'guide':'resources/twitter-migration','operations':[
                {'method':'POST','path':'/apis/v1/twitter/like_twitter','page':'api-reference/twitter/post_twitter-like-twitter','title':'Like Tweet'}]}
            row={'method':'GET','path':'/apis/v1/old/fetch_post','page':'api-reference/old/fetch_post','title':'old fetch_post',
                 'replacement':{'method':'GET','path':'/apis/v1/new/posts/{id}','page':'api-reference/new/posts-id'}}
            other={'scope':'human_presentation_only','formal_publication':False,'notice':{'en':'Gone.','zh':'已退役。'},
                   'replacement_label':{'en':'Use instead: ','zh':'请改用：'},'operations':[row]}
            (root/'docs/human-api-retirements.json').write_text(json.dumps(twitter))
            (root/'docs/human-api-retirements-other.json').write_text(json.dumps(other))
            nav={'languages':[{'language':'en','tabs':[{'tab':'API','groups':[{'group':'Old','pages':[row['page']]},{'group':'New','pages':[row['replacement']['page']]}]}]}]}
            (root/'docs.json').write_text(json.dumps({'navigation':nav}))
            changes={};apply_retirements(root,changes)
            en=changes[root/(row['page']+'.mdx')];zh=changes[root/('zh/'+row['page']+'.mdx')]
            self.assertIn('Use instead: [`GET /apis/v1/new/posts/{id}`](/api-reference/new/posts-id)',en)
            self.assertIn('请改用：[`GET /apis/v1/new/posts/{id}`](/zh/api-reference/new/posts-id)',zh)
            self.assertIn('`GET /apis/v1/old/fetch_post`',en);self.assertNotIn('openapi:',en)
            self.assertIn('Reauthorize the X account',changes[root/'api-reference/twitter/post_twitter-like-twitter.mdx'])
            groups=json.loads(changes[root/'docs.json'])['navigation']['languages'][0]['tabs'][0]['groups']
            self.assertEqual(groups,[{'group':'New','pages':[row['replacement']['page']]}])
            (root/'docs/human-api-retirements-dup.json').write_text(json.dumps(other))
            with self.assertRaises(ValueError):apply_retirements(root,{})

    def test_repository_retirements_are_already_applied(self):
        # Committed archives (including the eight legacy X pages) are a fixed point of the policies.
        root=Path(__file__).resolve().parents[2]
        changes={};apply_retirements(root,changes)
        stale=[p.relative_to(root).as_posix() for p,t in changes.items() if not p.exists() or p.read_text()!=t]
        self.assertEqual(stale,[])

    def test_overseas_social_policy_points_to_live_reference_pages(self):
        root=Path(__file__).resolve().parents[2]
        policy=json.loads((root/'docs/human-api-retirements-social-overseas.json').read_text())
        rows=policy['operations'];retired={row['page'] for row in rows}
        self.assertEqual(len(rows),147);self.assertEqual(len({(r['method'],r['path']) for r in rows}),147)
        overseas=('instagram','tiktok','twitter','youtube','linkedin','reddit','threads','telegram')
        nav=(root/'docs.json').read_text()
        for row in rows:
            self.assertEqual(row['path'].split('/')[3],'tikhub');self.assertIn(row['path'].split('/')[4],overseas)
            new=row['replacement'];self.assertNotIn(new['page'],retired);self.assertNotIn('tikhub',new['path'])
            for prefix in ('','zh/'):
                page=root/(prefix+new['page']+'.mdx')
                self.assertIn(' '+new['method']+' '+new['path'].split('?')[0],page.read_text().split('---')[1])
                self.assertIn('"'+prefix+new['page']+'"',nav)


if __name__=='__main__':unittest.main()
