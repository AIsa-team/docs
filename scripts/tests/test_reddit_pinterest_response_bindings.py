"""Keep historical social responses out of unrelated SocialFetch routes."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from compose_openapi import compose
from runtime_registry import public_mirror_index

PLACEHOLDER = "Successful response. The payload schema has not been reviewed yet."
CASES = {
    "reddit": {
        "/apis/v1/reddit/posts/comments": "/reddit/post/comments",
        "/apis/v1/reddit/subreddits": "/reddit/subreddit/details",
        "/apis/v1/reddit/subreddits/search": "/reddit/subreddit/search",
        "/apis/v1/reddit/subreddits/{subreddit}/posts": "/reddit/subreddit",
    },
    "pinterest": {
        "/apis/v1/pinterest/boards/pins": "/pinterest/board",
        "/apis/v1/pinterest/pins": "/pinterest/pin",
        "/apis/v1/pinterest/profiles/{handle}/boards": "/pinterest/user/boards",
    },
}


def load(filename):
    return json.loads((ROOT / filename).read_text())


def path_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SocialResponseBindingTest(unittest.TestCase):
    def test_unreviewed_social_responses_are_explicitly_pending_in_both_locales(self):
        for provider in CASES:
            for locale in ("", "zh/"):
                document = load(f"openapi/{locale}{provider}.json")
                # The other two Reddit routes also lack independent response evidence.
                for path, item in document["paths"].items():
                    with self.subTest(provider=provider, locale=locale, path=path):
                        operation = item["get"]
                        response = operation["responses"]["200"]
                        self.assertEqual(response["description"], PLACEHOLDER)
                        self.assertEqual(response["content"]["application/json"], {"schema": {}})
                        self.assertEqual(operation["x-aisa-review"]["response"], "generic")
                        self.assertNotIn("x-aisa-response-source", operation)
                        self.assertEqual(operation["x-aisa-response-upstream-origin-sha256"],
                                         path_hash("https://api.socialfetch.dev"))

    def test_no_independent_candidate_relabels_a_historical_response(self):
        mirrors = public_mirror_index(ROOT)
        for routes in CASES.values():
            for public_path, historical_path in routes.items():
                with self.subTest(path=public_path):
                    self.assertFalse(mirrors.get((public_path, "get"), {}).get(
                        "independent_response_candidates"))
                    # The historical declaration remains available for its original URL.
                    legacy = mirrors[("/apis/v1" + historical_path, "get")]
                    self.assertIn("200", legacy["response_operation"]["responses"])
                    self.assertNotEqual("/apis/v1" + historical_path, public_path)

    def test_copied_schema_cannot_cross_origin_or_upstream_path_bindings(self):
        for provider, routes in CASES.items():
            historical = load(f"openapi/upstream/{provider}.json")
            published = load(f"openapi/{provider}.json")
            for public_path, historical_path in routes.items():
                runtime = copy.deepcopy(published)
                runtime["paths"] = {public_path: copy.deepcopy(published["paths"][public_path])}
                operation = runtime["paths"][public_path]["get"]
                # Model runtime facts with no reviewed payload, before publication.
                operation["responses"]["200"] = {"description": "Successful response"}
                operation.pop("x-aisa-review", None)
                for mismatch in ("origin", "path"):
                    with self.subTest(path=public_path, mismatch=mismatch):
                        source = copy.deepcopy(historical)
                        source["servers"] = [{"url": "https://api.aisa.one"}]
                        source["paths"] = {public_path: {"get": {"responses": {
                            "200": historical["paths"][historical_path]["get"]["responses"]["200"]}}}}
                        metadata = source["info"]["x-aisa-source"]
                        metadata.update(response_only=True,
                                        upstream_origin_sha256=operation["x-aisa-response-upstream-origin-sha256"],
                                        upstream_path_sha256=operation["x-aisa-response-upstream-path-sha256"])
                        if mismatch == "origin":
                            metadata["upstream_origin_sha256"] = path_hash("https://api.scrapecreators.com")
                        else:
                            metadata["upstream_path_sha256"] = path_hash("/v1" + historical_path)
                        with tempfile.TemporaryDirectory() as directory:
                            mirrors = public_mirror_index(Path(directory), {"historical.json": source})
                        result, pending = compose(runtime, public_mirrors=mirrors)
                        self.assertEqual(pending, [])
                        actual = result["paths"][public_path]["get"]
                        self.assertIn("x-aisa-response-pending", actual)
                        self.assertNotIn("x-aisa-response-source", actual)
                        self.assertNotIn("content", actual["responses"]["200"])
                        self.assertEqual(actual["parameters"], operation["parameters"])

    def test_pages_explain_the_missing_provider_specific_response_evidence(self):
        for provider, routes in CASES.items():
            published = load(f"openapi/{provider}.json")
            for path in routes:
                operation_id = published["paths"][path]["get"]["operationId"]
                pages = [p for p in (ROOT / "api-reference" / provider).glob("*.mdx")
                         if f'x-aisa-operation-id: "{operation_id}"' in p.read_text()]
                self.assertEqual(len(pages), 1, operation_id)
                for locale, pending_text in (("", "pending review"), ("zh/", "仍待审核")):
                    text = (ROOT / locale / pages[0].relative_to(ROOT)).read_text()
                    self.assertIn(pending_text, text)
                    self.assertIn("SocialFetch", text)
                    self.assertNotIn("Response`", text)


if __name__ == "__main__":
    unittest.main()
