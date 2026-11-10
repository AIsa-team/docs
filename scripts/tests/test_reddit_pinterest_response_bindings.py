"""Focused response-source checks for Reddit and Pinterest public routes."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "Successful response. The payload schema has not been reviewed yet."
CASES = {
    "reddit": {
        "/apis/v1/reddit/posts/comments": "response-reddit-get-posts-comments.json",
        "/apis/v1/reddit/subreddits": "response-reddit-get-subreddits.json",
        "/apis/v1/reddit/subreddits/search": "response-reddit-get-subreddits-search.json",
        "/apis/v1/reddit/subreddits/{subreddit}/posts": "response-reddit-get-subreddits-posts.json",
    },
    "pinterest": {
        "/apis/v1/pinterest/boards/pins": "response-pinterest-get-boards-pins.json",
        "/apis/v1/pinterest/pins": "response-pinterest-get-pins.json",
        "/apis/v1/pinterest/profiles/{handle}/boards": "response-pinterest-get-profiles-boards.json",
    },
}


class SocialResponseBindingTest(unittest.TestCase):
    def test_reviewed_routes_have_typed_responses_in_both_documents(self):
        for provider, routes in CASES.items():
            for filename in (f"openapi/{provider}.json", f"openapi/zh/{provider}.json"):
                with self.subTest(provider=provider, filename=filename):
                    document = json.loads((ROOT / filename).read_text())
                    for path in routes:
                        response = document["paths"][path]["get"]["responses"]["200"]
                        self.assertNotEqual(response.get("description"), PLACEHOLDER)
                        self.assertIn("content", response)
                        self.assertIn("application/json", response["content"])
                        schema = response["content"]["application/json"]["schema"]
                        self.assertTrue(isinstance(schema, dict) and ("$ref" in schema or schema.get("type")))
                        self.assertEqual(document["paths"][path]["get"]["x-aisa-response-source"]["kind"], "upstream_success_contract")
                        review = document["paths"][path]["get"].get("x-aisa-review", {})
                        self.assertNotEqual(review.get("response"), "generic")
                        self.assertNotIn("example", response["content"]["application/json"])
                        self.assertNotIn("examples", response["content"]["application/json"])

    def test_english_and_chinese_pages_both_publish_response_contracts(self):
        for provider, routes in CASES.items():
            for path in routes:
                operation_id = json.loads((ROOT / f"openapi/{provider}.json").read_text())["paths"][path]["get"]["operationId"]
                pages = list((ROOT / "api-reference" / provider).glob("*.mdx"))
                matches = []
                for page in pages:
                    if f'x-aisa-operation-id: "{operation_id}"' in page.read_text():
                        matches.append(page)
                self.assertEqual(len(matches), 1, operation_id)
                zh_page = ROOT / "zh" / "api-reference" / provider / matches[0].name
                self.assertTrue(zh_page.exists(), zh_page)
                self.assertIn("## Response contract", matches[0].read_text())
                self.assertIn("## 响应契约", zh_page.read_text())

    def test_sources_are_response_only_and_bound_to_exact_public_routes(self):
        for provider, routes in CASES.items():
            for path, source_name in routes.items():
                with self.subTest(provider=provider, path=path):
                    source = json.loads((ROOT / "openapi/upstream" / source_name).read_text())
                    metadata = source["info"]["x-aisa-source"]
                    self.assertIs(metadata["response_only"], True)
                    self.assertRegex(metadata["upstream_path_sha256"], r"^[0-9a-f]{64}$")
                    self.assertRegex(metadata["upstream_origin_sha256"], r"^[0-9a-f]{64}$")
                    self.assertEqual(list(source["paths"]), [path])
                    operation = source["paths"][path]["get"]
                    self.assertNotIn("requestBody", operation)
                    self.assertIn("application/json", operation["responses"]["200"]["content"])

    def test_reddit_routes_without_a_matching_source_remain_explicitly_pending(self):
        document = json.loads((ROOT / "openapi/reddit.json").read_text())
        for path in ("/apis/v1/reddit/posts", "/apis/v1/reddit/posts/transcript"):
            response = document["paths"][path]["get"]["responses"]["200"]
            self.assertEqual(response.get("description"), PLACEHOLDER)
            self.assertEqual(response["content"]["application/json"]["schema"], {})


if __name__ == "__main__":
    unittest.main()
