#!/usr/bin/env python3
"""Regroup the API Reference tabs as category -> vendor groups.

The English tab is rebuilt from `openapi/nav-groups.json`; the Chinese tab is
then mirrored from it with labels from `translations/openapi-nav-zh.json`.
Safe to rerun: the page set never changes and a regrouped tab is a fixed point.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import api_nav_groups

ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = Path("translations/openapi-nav-zh.json")
API_TABS = {"en": "API Reference", "zh": "API 参考"}


def api_tab(docs: dict, language: str) -> dict:
    for block in docs["navigation"]["languages"]:
        if block.get("language") == language:
            tabs = [tab for tab in block.get("tabs", []) if tab.get("tab") in API_TABS.values()]
            if len(tabs) != 1:
                raise ValueError(f"{language}: expected exactly one API tab, found {len(tabs)}")
            return tabs[0]
    raise KeyError(f"language navigation not found: {language}")


def labels_in(node, found: set[str]) -> set[str]:
    if isinstance(node, dict):
        if isinstance(node.get("group"), str):
            found.add(node["group"])
        for value in node.values():
            labels_in(value, found)
    elif isinstance(node, list):
        for value in node:
            labels_in(value, found)
    return found


def localize(node, labels: dict[str, str]):
    if isinstance(node, dict):
        return {key: labels[value] if key == "group" else localize(value, labels) for key, value in node.items()}
    if isinstance(node, list):
        return [localize(value, labels) for value in node]
    if isinstance(node, str) and (node == "api-reference" or node.startswith("api-reference/")):
        return "zh/" + node
    return node


def regroup_docs(docs: dict, config: dict, labels: dict[str, str]) -> tuple[dict, list[str]]:
    docs = copy.deepcopy(docs)
    en = api_tab(docs, "en")
    before = api_nav_groups.nav_pages(en)
    en["groups"], unmapped = api_nav_groups.regroup(en["groups"], config)
    after = api_nav_groups.nav_pages(en)
    if set(before) != set(after) or len(after) != len(set(after)):
        raise AssertionError("regrouping changed the English API page set")
    missing = sorted(label for label in labels_in(en, set()) if not labels.get(label))
    if missing:
        raise KeyError("missing labels in translations/openapi-nav-zh.json: " + ", ".join(missing))
    zh = api_tab(docs, "zh")
    zh_before = set(api_nav_groups.nav_pages(zh))
    zh.clear()
    zh.update(localize(en, labels))
    zh["tab"] = API_TABS["zh"]
    if zh_before != {"zh/" + page for page in after}:
        raise AssertionError("Chinese API page set differs from the English mirror")
    return docs, unmapped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if docs.json is not already regrouped")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    docs_path = args.root / "docs.json"
    current = docs_path.read_text()
    config = api_nav_groups.load(args.root)
    if config is None:
        raise SystemExit(f"missing {api_nav_groups.CONFIG_PATH}")
    labels = json.loads((args.root / LABELS_PATH).read_text())
    docs, unmapped = regroup_docs(json.loads(current), config, labels)
    for name in unmapped:
        print(f"warning: unmapped API group kept at the end: {name}", file=sys.stderr)
    output = json.dumps(docs, indent=2, ensure_ascii=False) + "\n"
    pages = len(api_nav_groups.nav_pages(api_tab(docs, "en")))
    if args.check:
        if output != current:
            print("docs.json API navigation is not regrouped; run scripts/regroup_api_reference.py", file=sys.stderr)
            return 1
        print(f"API navigation regrouped; pages={pages}")
        return 0
    if output != current:
        docs_path.write_text(output)
    print(f"API navigation regrouped; pages={pages} unmapped={len(unmapped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
