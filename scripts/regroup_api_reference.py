#!/usr/bin/env python3
"""Regroup the API Reference tabs as category -> platform groups.

The English tab is rebuilt from `openapi/nav-groups.json`; the Chinese tab is
then mirrored from it with labels from `translations/openapi-nav-zh.json`.
Safe to rerun: the page set never changes and a regrouped tab is a fixed point.

It also writes the "Browse by platform" index (`api-reference/platforms.mdx`
and its Chinese page): every platform group, A to Z, linked to its first page.
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
INDEX_PAGE = "api-reference/platforms"
INDEX_COPY = {
    "en": {
        "title": "Browse by platform",
        "description": "Every API platform A to Z, with its category and endpoint count.",
        "lead": ("Each row links to the platform's first endpoint. The sidebar lists the same platforms "
                 "under their category. To search every endpoint, press <kbd>Ctrl</kbd> + <kbd>K</kbd>."),
        "columns": ("Platform", "Category", "Endpoints"),
    },
    "zh": {
        "title": "按平台浏览",
        "description": "按字母顺序列出全部 API 平台，以及所属分类和端点数量。",
        "lead": ("每一行链接到该平台的第一个端点。侧栏按分类列出同样的平台。"
                 "要搜索全部端点，请按 <kbd>Ctrl</kbd> + <kbd>K</kbd>。"),
        "columns": ("平台", "分类", "端点数"),
    },
}


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


def platform_rows(docs: dict, config: dict) -> list[dict]:
    """Every platform group of the English tab: name, category, first page, endpoints."""
    section = (config.get("section") or {}).get("name")
    categories = {category["name"] for category in config["categories"] if not category.get("top")}
    rows = []
    for group in api_tab(docs, "en")["groups"]:
        holders = group["pages"] if section and group.get("group") == section else [group]
        for category in holders:
            if not isinstance(category, dict) or category.get("group") not in categories:
                continue
            for platform in category["pages"]:
                pages = api_nav_groups.nav_pages(platform)
                if isinstance(platform, dict) and pages:
                    rows.append({"name": platform["group"], "category": category["group"],
                                 "first": pages[0], "count": len(set(pages))})
    return sorted(rows, key=lambda row: (row["name"].casefold(), row["category"]))


def cell(text: str) -> str:
    return text.replace("|", "\\|")


def platform_index(docs: dict, config: dict, labels: dict[str, str], language: str) -> str:
    text = INDEX_COPY[language]
    prefix = "/zh/" if language == "zh" else "/"
    lines = ["---", f"title: {json.dumps(text['title'], ensure_ascii=False)}",
             f"description: {json.dumps(text['description'], ensure_ascii=False)}", "---", "",
             "{/* Generated by scripts/regroup_api_reference.py from docs.json. Do not edit. */}", "",
             text["lead"]]
    letter = None
    for row in platform_rows(docs, config):
        first = row["name"][:1].upper()
        first = first if first.isalpha() and first.isascii() else "#"
        if first != letter:
            letter = first
            lines += ["", f"## {letter}", "", "| " + " | ".join(text["columns"]) + " |", "| --- | --- | ---: |"]
        name, category = row["name"], row["category"]
        if language == "zh":
            local = labels.get(name) or name
            name = local if local == name else f"{local}（{name}）"
            category = labels.get(category) or category
        lines.append(f"| [{cell(name)}]({prefix}{row['first']}) | {cell(category)} | {row['count']} |")
    return "\n".join(lines) + "\n"


def index_pages(docs: dict, config: dict, labels: dict[str, str]) -> dict[str, str]:
    """The index pages by repository path, empty when navigation does not list it."""
    if INDEX_PAGE not in api_nav_groups.nav_pages(api_tab(docs, "en")):
        return {}
    return {f"{INDEX_PAGE}.mdx": platform_index(docs, config, labels, "en"),
            f"zh/{INDEX_PAGE}.mdx": platform_index(docs, config, labels, "zh")}


def write_index_pages(root: Path) -> list[str]:
    """Refresh the index pages from root's docs.json; return the changed paths."""
    config = api_nav_groups.load(root)
    if config is None:
        return []
    docs = json.loads((root / "docs.json").read_text())
    labels = json.loads((root / LABELS_PATH).read_text())
    changed = []
    for name, text in index_pages(docs, config, labels).items():
        path = root / name
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
            changed.append(name)
    return changed


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
        print(f"warning: unmapped API group: {name}", file=sys.stderr)
    output = json.dumps(docs, indent=2, ensure_ascii=False) + "\n"
    pages = len(api_nav_groups.nav_pages(api_tab(docs, "en")))
    index = index_pages(docs, config, labels)
    if args.check:
        stale = [name for name, text in index.items()
                 if not (args.root / name).exists() or (args.root / name).read_text() != text]
        if output != current or stale:
            print("docs.json API navigation or the platform index is stale; run scripts/regroup_api_reference.py",
                  file=sys.stderr)
            return 1
        print(f"API navigation regrouped; pages={pages}")
        return 0
    if output != current:
        docs_path.write_text(output)
    for name, text in index.items():
        path = args.root / name
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
    print(f"API navigation regrouped; pages={pages} unmapped={len(unmapped)} platforms={len(platform_rows(docs, config))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
