import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from human_api_retirements import apply_retirements
from sync_prod_runtime_docs import preserve_navigation


class RetirementTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
