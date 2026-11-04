"""API Reference categories shared by regrouping and runtime page generation.

`openapi/nav-groups.json` maps an OpenAPI `info.title` (or a legacy navigation
group name) to a category and platform group. Category and group names also map
to themselves so an already regrouped tab is a fixed point.

Optional keys:

- `section`: one top-level group that holds every category without `top`, so
  the sidebar first shows only the (collapsible) categories.
- `fallback`: the category for titles without a mapping. It takes any group
  name, so a new provider never lists its endpoints at the top level.
- `paths`: rules for nested legacy groups, keyed by their group path joined
  with `/`. They move a vendor's per-platform groups to that platform.
- `vendors`: subgroup names of third-party vendors. In a platform group they
  sort after the platform's own pages.
- `first_party`: subgroup names of AIsa's own products inside a platform group.
  They sort after the platform's own pages and before third-party vendors.
- `operations`: rules for single endpoints, matched by the OpenAPI document
  name (`spec`, e.g. `aisa-commerce`) and a regular expression on the path
  (`pattern`). They place one provider's endpoints under several platforms,
  which a page filename cannot always tell. They win over `pages` rules.
  Subgroups that these rules create in one group follow the rules' order.
"""
from __future__ import annotations

import json
import re
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
    fallback = config.get("fallback")
    if fallback is not None and fallback not in categories:
        raise ValueError(f"unknown fallback API navigation category {fallback!r}")
    section = config.get("section")
    if section is not None and section.get("name") in categories:
        raise ValueError("the API navigation section must not share a category name")
    targets = list(mappings(config).items()) + [(rule["prefix"], rule) for rule in config.get("pages", [])]
    for rule in config.get("operations", []):
        if not isinstance(rule.get("spec"), str) or not isinstance(rule.get("pattern"), str):
            raise ValueError(f"operation rule needs a spec and a pattern: {rule!r}")
        re.compile(rule["pattern"])
        targets.append((f"{rule['spec']} {rule['pattern']}", rule))
    targets += list(config.get("paths", {}).items())
    for source, target in targets:
        category = categories.get(target.get("category"))
        if category is None:
            raise ValueError(f"{source}: unknown API navigation category {target.get('category')!r}")
        if "group" in target and target["group"] not in category["groups"] and category["name"] != fallback:
            raise ValueError(f"{source}: group {target['group']!r} is not listed under {category['name']!r}")
        if "subgroup" in target and "group" not in target:
            raise ValueError(f"{source}: subgroup requires a group")


def target_for(config: dict | None, name: str) -> dict | None:
    return mappings(config).get(name) if config else None


def fallback_target(config: dict | None, name: str) -> dict | None:
    """Where an unmapped provider title goes: its own group in the fallback category."""
    if config and config.get("fallback"):
        return {"category": config["fallback"], "group": name}
    return None


def operation_target(config: dict, operation: tuple[str, str] | None) -> dict | None:
    """The first `operations` rule for a (document name, path) pair."""
    if operation:
        spec, path = operation
        for rule in config.get("operations", []):
            if rule["spec"] == spec and re.search(rule["pattern"], path):
                return rule
    return None


def page_target(config: dict, page: str, operation: tuple[str, str] | None = None) -> dict | None:
    """Where a page goes by its own rule: its operation first, then its filename."""
    found = operation_target(config, operation)
    if found:
        return found
    page = page.removeprefix("zh/")
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


def _top_order(config: dict, label) -> list[str]:
    """Top-level order: `top` categories and the section, in category order."""
    section = config.get("section")
    order: list[str] = []
    for category in config["categories"]:
        name = category["name"] if category.get("top") or not section else section["name"]
        if label(name) not in order:
            order.append(label(name))
    return order


def locate(groups: list, config: dict, target: dict, label=lambda name: name) -> list:
    """Return the page list for a target, creating missing levels in configured order."""
    category = next(c for c in config["categories"] if c["name"] == target["category"])
    fields = {"icon": category["icon"]} if category.get("icon") else {}
    section = config.get("section")
    container, order = groups, _top_order(config, label)
    if section and not category.get("top"):
        section_fields = {"icon": section["icon"]} if section.get("icon") else {}
        container = _child(groups, label(section["name"]), order, **section_fields)["pages"]
        order = [label(c["name"]) for c in config["categories"] if not c.get("top")]
    node = _child(container, label(category["name"]), order, **fields)
    if target.get("group"):
        node = _child(node["pages"], label(target["group"]), [label(g) for g in category["groups"]])
    if target.get("subgroup"):
        node = _child(node["pages"], label(target["subgroup"]), _subgroup_order(config, target, label))
    return node["pages"]


def _subgroup_order(config: dict, target: dict, label) -> list[str]:
    """Subgroups that `operations` rules create in the target's group, in rule order."""
    order: list[str] = []
    for rule in config.get("operations", []):
        if rule.get("group") == target.get("group") and rule.get("subgroup"):
            if label(rule["subgroup"]) not in order:
                order.append(label(rule["subgroup"]))
    return order


def nav_pages(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [page for item in node for page in nav_pages(item)]
    if isinstance(node, dict):
        return nav_pages(node.get("groups", [])) + nav_pages(node.get("pages", []))
    return []


def order_vendors(groups: list, config: dict, label=lambda name: name) -> None:
    """In a platform group, put AIsa's own product subgroups after the platform's
    own pages, then third-party vendor subgroups. In place; otherwise stable."""
    tiers = {label(name): 1 for name in config.get("first_party", [])}
    tiers.update({label(name): 2 for name in config.get("vendors", [])})
    if not tiers:
        return
    # A category may hold a platform group that shares a first-party name.
    section = (config.get("section") or {}).get("name")
    containers = {label(c["name"]) for c in config["categories"]} | ({label(section)} if section else set())

    def tier(item) -> int:
        return tiers.get(item.get("group"), 0) if isinstance(item, dict) else 0

    def visit(items: list) -> None:
        for item in items:
            if isinstance(item, dict):
                pages = item.get("pages", [])
                if item.get("group") not in containers and any(tier(p) for p in pages):
                    pages.sort(key=tier)
                visit(pages)

    visit(groups)


def regroup(groups: list, config: dict, operations: dict | None = None) -> tuple[list, list[str]]:
    """Rebuild English API groups as [section ->] category -> platform groups.

    Returns the new groups and the names of top-level groups without a mapping.
    With a fallback category they become groups in it; without one they are kept
    unchanged after the categories. Duplicate pages keep their first position.
    `operations` maps a page to its (document name, path) for `operations` rules.
    """
    maps = mappings(config)
    operations = operations or {}

    def explicit(page: str) -> dict | None:
        return page_target(config, page, operations.get(page))
    paths = config.get("paths", {})
    section = (config.get("section") or {}).get("name")
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

    def rule(path: list[str], parent: dict | None) -> dict | None:
        key = "/".join(path)
        if key in paths:
            return paths[key]
        # Inside a platform group, names describe the vendor's own structure.
        if parent is None or "group" not in parent:
            return maps.get(path[-1])
        return None

    later: list[tuple[str, dict]] = []

    def keep(node: dict, group: str | None) -> dict | None:
        """Copy a kept subgroup, moving out pages whose rule names another group."""
        pages = []
        for child in node.get("pages", []):
            if isinstance(child, dict):
                child = keep(child, group)
                if child is not None:
                    pages.append(child)
                continue
            moved = explicit(child)
            if moved and moved.get("group") != group:
                later.append((child, moved))
            else:
                pages.append(child)
        return {**node, "pages": pages} if pages else None

    def route(items: list, target: dict, path: list[str]) -> None:
        for item in items:
            if isinstance(item, str):
                moved = explicit(item)
                if moved and moved.get("group") != target.get("group"):
                    later.append((item, moved))
                else:
                    merge(locate(result, config, moved or target), [item])
                continue
            child = path + [item["group"]]
            found = rule(child, target)
            if found is not None:
                route(item.get("pages", []), found, child)
            else:
                kept = keep(item, target.get("group"))
                if kept is not None:
                    merge(locate(result, config, target), [kept])

    top: list = []
    for group in groups:
        # An already regrouped section is unwrapped so the result is a fixed point.
        top.extend(group.get("pages", []) if section and group.get("group") == section else [group])
    unmapped = []
    for group in top:
        if isinstance(group, str):
            unmapped.append(group)
            continue
        target = rule([group.get("group")], None)
        if target is None:
            unmapped.append(group)
        else:
            route(group.get("pages", []), target, [group["group"]])
    for page, moved in later:
        merge(locate(result, config, moved), [page])
    leftovers: list = []
    for group in unmapped:
        fallback = fallback_target(config, group["group"]) if isinstance(group, dict) else None
        if fallback:
            merge(locate(result, config, fallback), group.get("pages", []))
        else:
            merge(leftovers, [group])
    order_vendors(result, config)
    return result + leftovers, [g.get("group") if isinstance(g, dict) else g for g in unmapped]
