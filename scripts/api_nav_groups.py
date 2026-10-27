"""API Reference categories shared by regrouping and runtime page generation.

`openapi/nav-groups.json` maps an OpenAPI `info.title` (or a legacy navigation
group name) to a category and vendor group. Category and vendor names also map
to themselves so an already regrouped tab is a fixed point.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path("openapi/nav-groups.json")


def load(root: Path) -> dict | None:
    path = Path(root) / CONFIG_PATH
    if not path.exists():
        return None
    config = json.loads(path.read_text())
    validate(config)
    return config


def mappings(config: dict) -> dict[str, dict]:
    result = {}
    for category in config["categories"]:
        result[category["name"]] = {"category": category["name"]}
        for group in category["groups"]:
            result[group] = {"category": category["name"], "group": group}
    result.update(config.get("groups", {}))
    return result


def validate(config: dict) -> None:
    categories = {category["name"]: category for category in config["categories"]}
    if len(categories) != len(config["categories"]):
        raise ValueError("duplicate API navigation category")
    targets = list(mappings(config).items()) + [(rule["prefix"], rule) for rule in config.get("pages", [])]
    for source, target in targets:
        category = categories.get(target.get("category"))
        if category is None:
            raise ValueError(f"{source}: unknown API navigation category {target.get('category')!r}")
        if "group" in target and target["group"] not in category["groups"]:
            raise ValueError(f"{source}: group {target['group']!r} is not listed under {category['name']!r}")
        if "subgroup" in target and "group" not in target:
            raise ValueError(f"{source}: subgroup requires a group")


def target_for(config: dict | None, name: str) -> dict | None:
    return mappings(config).get(name) if config else None


def page_target(config: dict, page: str) -> dict | None:
    for rule in config.get("pages", []):
        if page.startswith(rule["prefix"]):
            return rule
    return None


def _child(items: list, name: str, order: list[str] | None = None, **fields) -> dict:
    for item in items:
        if isinstance(item, dict) and item.get("group") == name:
            return item
    node = {"group": name, **fields, "pages": []}
    order = order or []
    rank = order.index(name) if name in order else len(order)
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("group") in order and order.index(item["group"]) > rank:
            items.insert(index, node)
            return node
    items.append(node)
    return node


def locate(groups: list, config: dict, target: dict, label=lambda name: name) -> list:
    """Return the page list for a target, creating missing levels in configured order."""
    category = next(c for c in config["categories"] if c["name"] == target["category"])
    fields = {"icon": category["icon"]} if category.get("icon") else {}
    node = _child(groups, label(category["name"]), [label(c["name"]) for c in config["categories"]], **fields)
    if target.get("group"):
        node = _child(node["pages"], label(target["group"]), [label(g) for g in category["groups"]])
    if target.get("subgroup"):
        node = _child(node["pages"], label(target["subgroup"]))
    return node["pages"]


def nav_pages(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [page for item in node for page in nav_pages(item)]
    if isinstance(node, dict):
        return nav_pages(node.get("groups", [])) + nav_pages(node.get("pages", []))
    return []


def regroup(groups: list, config: dict) -> tuple[list, list[str]]:
    """Rebuild English API groups as category -> vendor groups.

    Returns the new groups and the names of top-level groups without a mapping,
    which are kept unchanged after the categories. Duplicate pages keep their
    first position.
    """
    maps = mappings(config)
    result: list = []
    placed: set[str] = set()

    def merge(dest: list, items: list) -> None:
        for item in items:
            if isinstance(item, str):
                if item not in placed:
                    placed.add(item)
                    dest.append(item)
            else:
                fields = {k: v for k, v in item.items() if k not in {"group", "pages"}}
                merge(_child(dest, item["group"], **fields)["pages"], item.get("pages", []))

    def route(items: list, target: dict) -> None:
        for item in items:
            if isinstance(item, str):
                merge(locate(result, config, page_target(config, item) or target), [item])
                continue
            vendor = maps.get(item["group"]) if "group" not in target else None
            if vendor and vendor["category"] == target["category"] and "group" in vendor:
                route(item.get("pages", []), vendor)
            else:
                merge(locate(result, config, target), [item])

    unmapped = []
    for group in groups:
        target = maps.get(group.get("group"))
        if target is None:
            unmapped.append(group)
        else:
            route(group.get("pages", []), target)
    leftovers: list = []
    merge(leftovers, unmapped)
    return result + leftovers, [group.get("group") for group in unmapped]
