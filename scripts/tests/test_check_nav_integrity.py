"""Navigation, orphan-page, and redirect checks for docs.json."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_nav_integrity import UNLISTED_PAGES, validate


def write_site(root: Path, pages: list[str], navigation: list[str], redirects: list[tuple[str, str]]) -> None:
    for page in pages:
        path = root / f"{page}.mdx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntitle: Test\n---\n", encoding="utf-8")
    for page in UNLISTED_PAGES:
        path = root / f"{page}.mdx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntitle: Test\n---\n", encoding="utf-8")
    config = {
        "navigation": {"languages": [{"language": "en", "tabs": [
            {"tab": "Guides", "groups": [{"group": "Start", "pages": [
                navigation[0], {"group": "Nested", "pages": navigation[1:]},
            ]}]},
        ]}]},
        "redirects": [
            {"source": source, "destination": destination, "permanent": True}
            for source, destination in redirects
        ],
    }
    (root / "docs.json").write_text(json.dumps(config), encoding="utf-8")


class CheckNavIntegrityTests(unittest.TestCase):
    def test_consistent_site_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_site(
                root,
                pages=["guides", "guides/pricing", "old/page", "snippets/x", "api-reference/a/get_x"],
                navigation=["guides", "guides/pricing"],
                redirects=[("/old/page", "/guides/pricing#funding"), ("/gone", "https://aisa.one"),
                           ("/legacy/:slug*", "/guides/:slug*")],
            )
            self.assertEqual(validate(root), [])

    def test_reports_missing_orphan_dangling_and_chained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_site(
                root,
                pages=["guides", "orphan"],
                navigation=["guides", "missing/page"],
                redirects=[("/a", "/b"), ("/b", "/guides"), ("/c", "/nowhere")],
            )
            errors = validate(root)
            self.assertIn("navigation page has no file: missing/page", errors)
            self.assertIn("page is not in navigation or a redirect source: orphan.mdx", errors)
            self.assertIn("redirect chain: /a -> /b is itself redirected", errors)
            self.assertIn("redirect destination has no page: /c -> /nowhere", errors)
            self.assertEqual(len(errors), 4)


if __name__ == "__main__":
    unittest.main()
