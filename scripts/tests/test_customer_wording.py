from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from customer_wording import apply  # noqa: E402


class CustomerWordingTests(unittest.TestCase):
    def test_prose_is_reworded_and_data_is_not(self):
        document = {'properties': {'url': {
            'description': 'CDN URL; it is not a SocialFetch-hosted asset.',
            'examples': ['SocialFetch-hosted'], 'x-aisa-source': {'converter': 'SocialFetch storage'}}},
            'summary': 'Whether SocialFetch stored a durable copy', 'title': 'deleted from SocialFetch storage'}
        result = apply(document)
        self.assertEqual(result['properties']['url']['description'], 'CDN URL; it is not an AIsa-hosted asset.')
        self.assertEqual(result['properties']['url']['examples'], ['SocialFetch-hosted'])
        self.assertEqual(result['properties']['url']['x-aisa-source'], {'converter': 'SocialFetch storage'})
        self.assertEqual(result['summary'], 'Whether AIsa stored a durable copy')
        self.assertEqual(result['title'], 'deleted from AIsa hosted-media storage')

    def test_reviewed_sources_have_no_unhandled_supplier_prose(self):
        import glob, json, re
        root = Path(__file__).resolve().parents[2]
        for name in sorted(glob.glob(str(root / 'openapi/upstream/response-socialfetch-*.json'))):
            document = json.loads(Path(name).read_text())
            document['info'].pop('x-aisa-source', None)
            text = json.dumps(apply(document))
            prose = re.findall(r'"(?:description|summary|title)": "([^"]*)"', text)
            with self.subTest(name=Path(name).name):
                self.assertFalse([p for p in prose if 'socialfetch' in p.lower()])


if __name__ == '__main__':
    unittest.main()
