import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_dev_tasks

ROOT = Path(__file__).resolve().parents[2]


def detail(language):
    zh = language == "zh"
    return {
        "task_id": "social.get_post", "domain": "social", "method": "POST", "path": "/v1/tasks/social.get_post",
        "name": "获取帖子" if zh else "Get a social post",
        "description": "已知帖子 URL 时使用。" if zh else "Use when you have the URL of a post {or video}.",
        "input": [
            {"name": "platform", "type": "string", "required": True, "enum": ["tiktok", "x"], "description": "平台。" if zh else "Platform."},
            {"name": "url", "type": "string", "required": True, "max_length": 2048, "description": "URL | 链接" if zh else "Public URL <of the post>."},
        ],
        "version": 1, "status": "beta", "route_by": "platform",
        "routes": [{"value": "tiktok", "fields": ["platform", "post_id"]}, {"value": "x", "fields": ["platform", "post_id", "language"]}],
        "output": {"entity": "social_post", "list": False, "schema": {"type": "object", "properties": {"post_id": {"type": ["string", "null"]}}}},
        "hit_rule": {"any_of": ["post_id"]}, "billing": {"mode": "fixed"}, "strategy": "auto",
    }


def fake_get(api, path):
    if path == "/v1/tasks":
        return {"object": "list", "data": [{"task_id": "social.get_post"}]}
    return detail("zh" if path.endswith("?lang=zh") else "en")


class SyncDevTasksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs.json").write_text((ROOT / "docs.json").read_text())
        stale = self.root / "tasks" / "social-removed.mdx"
        stale.parent.mkdir()
        stale.write_text("old")

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_mirrored_pages_spec_and_nav(self):
        with patch.object(sync_dev_tasks, "get", fake_get):
            tasks = sync_dev_tasks.acquire("https://dev-api.aisa.one")
        sync_dev_tasks.write(self.root, tasks, "https://dev-api.aisa.one")
        sync_dev_tasks.write(self.root, tasks, "https://dev-api.aisa.one")  # idempotent
        self.assertFalse((self.root / "tasks" / "social-removed.mdx").exists())
        en = (self.root / "tasks" / "social-get-post.mdx").read_text()
        zh = (self.root / "zh" / "tasks" / "social-get-post.mdx").read_text()
        self.assertIn('openapi: "tasks/openapi.json POST /v1/tasks/social.get_post"', en)
        self.assertIn('openapi: "zh/tasks/openapi.json POST /v1/tasks/social.get_post"', zh)
        self.assertIn("Public URL \\<of the post\\>.", en)
        self.assertIn("URL \\| 链接", zh)
        self.assertIn("| X | `platform`, `post_id`, `language` |", en)
        spec = json.loads((self.root / "tasks" / "openapi.json").read_text())
        operation = spec["paths"]["/v1/tasks/social.get_post"]["post"]
        self.assertEqual(operation["operationId"], "task_social_get_post")
        self.assertEqual(operation["requestBody"]["content"]["application/json"]["example"]["input"]["platform"], "tiktok")
        self.assertEqual(spec["servers"], [{"url": "https://dev-api.aisa.one"}])
        docs = json.loads((self.root / "docs.json").read_text())
        for language, tab, group, page in (("en", "API Reference", "Tasks", "tasks/social-get-post"),
                                           ("zh", "API 参考", "任务", "zh/tasks/social-get-post")):
            entry = next(e for e in docs["navigation"]["languages"] if e["language"] == language)
            groups = next(t for t in entry["tabs"] if t["tab"] == tab)["groups"]
            matches = [g for g in groups if g.get("group") == group]
            self.assertEqual(len(matches), 1)
            self.assertIn(page, json.dumps(matches[0]))

    def test_unavailable_catalog_writes_nothing(self):
        def fail(api, path):
            raise sync_dev_tasks.CatalogUnavailable(path)
        before = (self.root / "docs.json").read_text()
        with patch.object(sync_dev_tasks, "get", fail), patch.object(sys, "argv", ["x", "--root", str(self.root)]):
            self.assertEqual(sync_dev_tasks.main(), 0)
        self.assertEqual((self.root / "docs.json").read_text(), before)
        self.assertTrue((self.root / "tasks" / "social-removed.mdx").exists())

    def test_detail_without_output_schema_is_unavailable(self):
        def old(api, path):
            body = fake_get(api, path)
            body.pop("output", None)
            return body
        with patch.object(sync_dev_tasks, "get", old):
            with self.assertRaises(sync_dev_tasks.CatalogUnavailable):
                sync_dev_tasks.acquire("https://dev-api.aisa.one")


if __name__ == "__main__":
    unittest.main()
