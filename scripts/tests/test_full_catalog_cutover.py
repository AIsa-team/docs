"""Whole documentation catalog regression, not whole-runtime contract coverage."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import consolidate_openapi as consolidate
from pull_openapi import normalize_paths, operations, stage


def effective_operations(document):
    return {
        ((operation.get("servers") or document["servers"])[0]["url"].rstrip("/") + path, method): operation
        for path, method, operation in operations(document)
    }


class FullCatalogCutoverTests(unittest.TestCase):
    def test_pilot_cutover_and_legacy_pin_preserve_every_other_operation(self):
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "openapi").mkdir()
            for source in (repository / "openapi").glob("*.json"):
                shutil.copy2(source, root / "openapi" / source.name)
            output = root / "openapi/similarweb.json"
            previous = json.loads(output.read_text())
            original_bytes = output.read_bytes()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "openapi/similarweb.json"], cwd=root, check=True)
            subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "user.name=Contract Test", "-c", "user.email=contract-test@example.invalid",
                            "commit", "-qm", "Published documentation baseline"], cwd=root, check=True)
            pin = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            facts = normalize_paths(copy.deepcopy(previous))
            facts["openapi"] = "3.1.0"
            facts["servers"] = [{"url": "https://api.aisa.one"}]
            facts["info"]["x-aisa-document"] = {"facts_hash": "sha256:catalog-regression-fixture"}
            for _, _, operation in operations(facts):
                operation["x-aisa-validation"] = "runtime"
                operation["x-aisa-status"] = "enabled"
            (root / "facts").mkdir()
            (root / "facts/similarweb.json").write_text(json.dumps(facts))
            registry = root / "openapi/registry.yaml"
            registry.write_text("auto_register: false\nproviders:\n  similarweb: {}\n")

            def write(changes):
                for path, content in changes.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)

            with patch.object(consolidate, "OPENAPI_DIR", str(root / "openapi")):
                baseline = effective_operations(consolidate.build_unified_spec())
                self.assertGreater(len(baseline), 1000, "exercise the full existing docs catalog")
                write(stage(root, root / "facts", "unused", with_pages=False)[0])
                generated = effective_operations(consolidate.build_unified_spec())
                self.assertEqual(set(generated), set(baseline))
                for identity, operation in baseline.items():
                    if not identity[0].startswith("https://api.aisa.one/apis/v1/similarweb/"):
                        self.assertEqual(generated[identity], operation, identity)
                registry.write_text(f"auto_register: false\nproviders:\n  similarweb:\n    pin: {pin}\n")
                write(stage(root, None, "unused", with_pages=False)[0])
                self.assertEqual(output.read_bytes(), original_bytes)
                self.assertEqual(effective_operations(consolidate.build_unified_spec()), baseline)
                self.assertEqual(stage(root, None, "unused", with_pages=False)[0], {})


if __name__ == "__main__":
    unittest.main()
