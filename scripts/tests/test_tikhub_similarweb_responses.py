"""Focused response-contract checks for the reviewed TikHub and SimilarWeb routes."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "Successful response. The payload schema has not been reviewed yet."
SW_TARGETS = [
    "/apis/v1/similarweb/keyword-analysis/keywords/overview",
    "/apis/v1/similarweb/segment-analysis/segments/traffic-sources",
    "/apis/v1/similarweb/website-analysis/websites/conversion-rates",
    "/apis/v1/similarweb/website-analysis/websites/conversion-rates/aggregated",
    "/apis/v1/similarweb/website-analysis/websites/traffic-by-demographics/aggregated",
]
TIKHUB_TARGETS = {
    "/apis/v1/tikhub/douyin/creator_v2/fetch_item_list_download": "post",
    "/apis/v1/tikhub/youtube/web/get_trending_videos": "get",
}

def operation(document, path, method=None):
    item = document["paths"][path]
    if method:
        return item[method]
    return next(value for key, value in item.items() if key in {"get", "post", "put", "patch", "delete"})

class ReviewedResponseTests(unittest.TestCase):
    def test_similarweb_unverified_success_responses_retain_open_debt(self):
        for filename in ("openapi/similarweb.json", "openapi/zh/similarweb.json"):
            document = json.loads((ROOT / filename).read_text())
            for path in SW_TARGETS:
                with self.subTest(filename=filename, path=path):
                    op = operation(document, path, "get")
                    response = op["responses"]["200"]
                    self.assertEqual(response.get("description"), PLACEHOLDER)
                    self.assertEqual(response["content"]["application/json"]["schema"], {})
                    self.assertNotIn("x-aisa-response-source", op)
                    self.assertEqual(op["x-aisa-review"]["response"], "generic")
                    self.assertEqual(op["x-aisa-review"]["status"], "unreviewed")
            # The disabled legacy route remains intentionally pending.
            folders = operation(document, "/apis/v1/similarweb/website/folders", "get")
            self.assertEqual(folders.get("x-aisa-status"), "disabled")
            self.assertEqual(folders["responses"]["200"].get("description"), "Successful response" if filename == "openapi/similarweb.json" else "成功响应")

    def test_tikhub_export_is_binary_and_trending_response_remains_unknown(self):
        source = json.loads((ROOT / "openapi/upstream/tikhub.json").read_text())
        post_source = source["paths"]["/tikhub/douyin/creator_v2/fetch_item_list_download"]["post"]["responses"]["200"]
        self.assertEqual(post_source["content"]["application/vnd.ms-excel"]["schema"], {"type": "string", "format": "binary"})
        get_source = source["paths"]["/tikhub/youtube/web/get_trending_videos"]["get"]["responses"]["200"]
        self.assertNotIn("content", get_source)
        self.assertIn("unverified", get_source["description"])
        for filename in ("openapi/tikhub.json", "openapi/zh/tikhub.json"):
            document = json.loads((ROOT / filename).read_text())
            post = operation(document, "/apis/v1/tikhub/douyin/creator_v2/fetch_item_list_download", "post")
            get = operation(document, "/apis/v1/tikhub/youtube/web/get_trending_videos", "get")
            with self.subTest(filename=filename, route="post"):
                self.assertNotEqual(post["responses"]["200"].get("description"), PLACEHOLDER)
                self.assertEqual(post["responses"]["200"]["content"]["application/vnd.ms-excel"]["schema"]["format"], "binary")
                self.assertIn("x-aisa-response-source", post)
                self.assertNotIn("x-aisa-response-pending", post)
            with self.subTest(filename=filename, route="get"):
                response = get["responses"]["200"]
                self.assertNotIn("$ref", response)
                for media in response.get("content", {}).values():
                    self.assertEqual(media.get("schema", {}), {})
                self.assertNotIn("x-aisa-response-source", get)
                pending = get.get("x-aisa-response-pending", {})
                review = get.get("x-aisa-review", {})
                self.assertTrue(
                    pending.get("statuses") == ["200"]
                    or (review.get("status") == "unreviewed" and review.get("response") == "generic"),
                    "Unknown GET success response must retain explicit pending/unreviewed debt",
                )

    def test_pages_explain_reviewed_response_shapes_in_english_and_chinese(self):
        pages = [
            "api-reference/tikhub/get_tikhub-youtube-web-get_trending_videos.mdx",
            "api-reference/tikhub/post_tikhub-douyin-creator_v2-fetch_item_list_download.mdx",
            "zh/api-reference/tikhub/get_tikhub-youtube-web-get_trending_videos.mdx",
            "zh/api-reference/tikhub/post_tikhub-douyin-creator_v2-fetch_item_list_download.mdx",
        ]
        for name in pages:
            text = (ROOT / name).read_text()
            with self.subTest(name=name):
                self.assertNotIn("Response structure is not yet fully documented", text)
                self.assertNotIn("响应结构尚未完整文档化", text)
        sw_pages = [
            "get_similarweb_apis_v1_similarweb_keyword_analysi_490801.mdx",
            "get_similarweb_apis_v1_similarweb_segment_analysi_6349fe.mdx",
            "get_similarweb_apis_v1_similarweb_website_analysi_850464.mdx",
            "get_similarweb_apis_v1_similarweb_website_analysi_7399a9.mdx",
            "get_similarweb_apis_v1_similarweb_website_analysi_aa2e1f.mdx",
        ]
        for lang in ("", "zh/"):
            for name in sw_pages:
                text = (ROOT / f"{lang}api-reference/similarweb" / name).read_text()
                self.assertIn("成功响应结构尚未核实" if lang else "successful response schema for this endpoint has not been verified", text)
                self.assertNotIn("meta.status", text)

if __name__ == "__main__":
    unittest.main()
