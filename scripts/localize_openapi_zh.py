#!/usr/bin/env python3
"""Generate Chinese OpenAPI specs and API-reference MDX mirrors.

Translation is stored in a stable source-string catalog. The script never edits
runtime identifiers: paths, methods, operationIds, parameter/property names,
$refs, enum values, examples, servers, and security configuration are copied
unchanged from the English source.

Typical workflow:
  python scripts/localize_openapi_zh.py extract
  python scripts/localize_openapi_zh.py translate --batch-size 20
  python scripts/localize_openapi_zh.py generate
  python scripts/localize_openapi_zh.py validate
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "openapi"
ZH_OPENAPI_DIR = OPENAPI_DIR / "zh"
API_DIR = ROOT / "api-reference"
ZH_API_DIR = ROOT / "zh" / "api-reference"
CATALOG_PATH = ROOT / "translations" / "openapi-zh.json"
CATALOG_LOCK_PATH = Path("/tmp") / f"aisa-openapi-zh-{hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]}.lock"
NAV_LABELS_PATH = ROOT / "translations" / "openapi-nav-zh.json"

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
# Schema `title` is often a model/class identifier (for example
# AgentSignupRequest), so only prose-bearing summary/description fields are
# localized inside specs. MDX frontmatter titles are translated separately.
TRANSLATABLE_KEYS = {"summary", "description"}

# Exact labels that are useful even before model translation and keep terminology consistent.
GLOSSARY = {
    "Successful response": "成功响应",
    "Bad Request": "请求错误",
    "Unauthorized": "未授权",
    "Forbidden": "禁止访问",
    "Not Found": "未找到",
    "Too Many Requests": "请求过多",
    "Internal Server Error": "内部服务器错误",
    "Request Body": "请求体",
    "Response": "响应",
    "Example": "示例",
    "Examples": "示例",
    "Parameters": "参数",
    "Streaming responses": "流式响应",
    "OpenAI Chat": "OpenAI 聊天",
    "Create chat completion": "创建聊天补全",
}

PRESERVE_TERMS = [
    "AIsa", "OpenAI", "Anthropic", "Claude", "Google", "Gemini", "Grok",
    "DeepSeek", "Qwen", "Kimi", "MiniMax", "GLM", "Seedream", "Wan",
    "Twitter", "YouTube", "Tavily", "Perplexity", "Polymarket", "Kalshi",
    "Apollo", "DataForSEO", "AgentMail", "Reddit", "Instagram", "Pinterest",
    "CoinGecko", "JSON", "HTTP", "HTTPS", "API", "SDK", "SSE", "URL",
    "OAuth", "Bearer", "Webhook", "WebSocket", "GraphQL", "x402", "MPP",
]




def referenced_spec_paths() -> list[Path]:
    """Return only specs referenced by canonical endpoint MDX pages."""
    names: set[str] = set()
    for mdx_path in API_DIR.rglob("*.mdx"):
        text = mdx_path.read_text(errors="ignore")
        match = re.search(r'^openapi:\s*["\']?openapi/([^"\'\s]+)', text, re.M)
        if match:
            names.add(match.group(1))
    return [OPENAPI_DIR / name for name in sorted(names)]

def key_for(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def load_catalog() -> dict[str, Any]:
    if CATALOG_PATH.exists():
        return json.loads(CATALOG_PATH.read_text())
    return {"version": 1, "language": "zh-CN", "entries": {}}


def save_catalog(catalog: dict[str, Any]) -> None:
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CATALOG_PATH.with_name(f".{CATALOG_PATH.name}.{os.getpid()}.tmp")
    # Compact JSON keeps the committed translation memory reviewable without
    # inflating this large catalog with several megabytes of indentation.
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary, CATALOG_PATH)


def merge_translations(translated: dict[str, str]) -> dict[str, Any]:
    """Atomically merge a worker checkpoint into the shared catalog."""
    CATALOG_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CATALOG_LOCK_PATH.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        latest = load_catalog()
        for key, value in translated.items():
            latest["entries"][key]["translation"] = value
        save_catalog(latest)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return latest


def is_translatable_spec_field(path: tuple[str, ...], key: str) -> bool:
    """Translate OpenAPI documentation prose, never runtime/sample values."""
    if key not in TRANSLATABLE_KEYS:
        return False
    if any(part in {"example", "examples", "default", "const", "enum"} for part in path):
        return False
    in_paths = "paths" in path
    in_semantic_components = "components" in path and any(
        part in path for part in ("schemas", "parameters", "responses", "securitySchemes", "requestBodies")
    )
    return in_paths or in_semantic_components or path == ("info",)


def iter_spec_strings(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            child = path + (str(key),)
            if key in TRANSLATABLE_KEYS and isinstance(value, str) and value.strip():
                if is_translatable_spec_field(path, key):
                    yield child, value
            yield from iter_spec_strings(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_spec_strings(value, path + (str(index),))


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("MDX is missing frontmatter")
    # Some generated source pages end immediately after the closing delimiter
    # and therefore have no trailing newline. Accept both valid shapes.
    match = re.search(r"\n---(?:\n|$)", text[4:])
    if not match:
        raise ValueError("MDX frontmatter is not closed")
    start = 4 + match.start()
    body_start = 4 + match.end()
    return text[4:start], text[body_start:]


def frontmatter_value(frontmatter: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(.*?)\s*$", frontmatter, re.M)
    if not match:
        return None
    raw = match.group(1).strip()
    if raw in {">", ">-", "|", "|-"}:
        block: list[str] = []
        for line in frontmatter[match.end():].splitlines():
            if line.startswith((" ", "\t")) or not line.strip():
                block.append(line.strip())
            else:
                break
        return " ".join(part for part in block if part).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        raw = raw[1:-1]
    return raw


def add_entry(catalog: dict[str, Any], source: str, context: str) -> None:
    if not source.strip():
        return
    key = key_for(source)
    entry = catalog["entries"].setdefault(
        key,
        {"source": source, "translation": GLOSSARY.get(source, ""), "contexts": []},
    )
    if entry["source"] != source:
        raise RuntimeError(f"catalog hash collision: {key}")
    # A common description can occur in hundreds of schema positions. A few
    # representative pointers are sufficient for review and keep the catalog
    # compact enough for normal Git workflows.
    if context not in entry["contexts"] and len(entry["contexts"]) < 5:
        entry["contexts"].append(context)


def extract() -> None:
    catalog = load_catalog()
    active_keys: set[str] = set()
    for spec_path in referenced_spec_paths():
        try:
            data = json.loads(spec_path.read_text())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid OpenAPI JSON {spec_path.relative_to(ROOT)}: {exc}") from exc
        for path, source in iter_spec_strings(data):
            add_entry(catalog, source, f"{spec_path.relative_to(ROOT)}:{'/'.join(path)}")
            active_keys.add(key_for(source))

    for mdx_path in sorted(API_DIR.rglob("*.mdx")):
        text = mdx_path.read_text()
        frontmatter, body = split_frontmatter(text)
        if "openapi:" not in frontmatter:
            continue
        for field in ("title", "description", "excerpt"):
            source = frontmatter_value(frontmatter, field)
            if source:
                add_entry(catalog, source, f"{mdx_path.relative_to(ROOT)}:frontmatter:{field}")
                active_keys.add(key_for(source))
        # Custom body translation is intentionally tracked as a whole document.
        # This preserves code fences exactly during model translation.
        if body.strip():
            add_entry(catalog, body, f"{mdx_path.relative_to(ROOT)}:body")
            active_keys.add(key_for(body))

    # Remove messages that are no longer in the active extraction boundary.
    # This is important when a field is reclassified as a technical identifier.
    catalog["entries"] = {
        key: entry for key, entry in catalog["entries"].items() if key in active_keys
    }
    for entry in catalog["entries"].values():
        entry["contexts"] = sorted(set(entry["contexts"]))
    save_catalog(catalog)
    untranslated = sum(not e.get("translation") for e in catalog["entries"].values())
    print(f"catalog entries={len(catalog['entries'])} untranslated={untranslated}")


def chunk_entries(entries: list[tuple[str, dict[str, Any]]], max_items: int, max_chars: int = 18000):
    batch: list[tuple[str, dict[str, Any]]] = []
    chars = 0
    for item in entries:
        size = len(item[1]["source"])
        if batch and (len(batch) >= max_items or chars + size > max_chars):
            yield batch
            batch, chars = [], 0
        batch.append(item)
        chars += size
    if batch:
        yield batch


def call_hermes(batch: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    payload = [{"id": key, "text": entry["source"]} for key, entry in batch]
    prompt = f"""You are translating AIsa API documentation from English to Simplified Chinese.
Return ONLY a valid JSON object mapping every input id to its Chinese translation.
Rules:
- Preserve Markdown and all code fences byte-for-byte inside each string; translate only prose outside code fences.
- Preserve API paths, HTTP methods, operationId, parameter/property names, $ref, enum values, URLs, model IDs, environment variables, placeholders, JSON keys, and code examples exactly.
- Preserve these product/protocol terms when natural: {', '.join(PRESERVE_TERMS)}.
- Use professional concise technical Chinese. Translate API Key as API 密钥; Token as 词元 when it means model tokens, otherwise preserve the technical token literal where necessary.
- Do not add explanations and do not omit any id.
INPUT JSON:
{json.dumps(payload, ensure_ascii=False)}
"""
    last_error = "unknown error"
    for attempt in range(1, 4):
        result = subprocess.run(
            ["hermes", "-z", prompt, "--ignore-rules", "--safe-mode"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
        )
        if result.returncode != 0:
            last_error = f"hermes exit {result.returncode}: {result.stderr[-2000:]}"
            continue
        output = result.stdout.strip()
        output = re.sub(r"^```(?:json)?\s*|\s*```$", "", output, flags=re.S)
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            # Some providers append harmless prose or a second JSON value after
            # the requested object. Decode the first complete JSON value and
            # accept it only when its keys exactly match this batch.
            try:
                data, _end = json.JSONDecoder().raw_decode(output)
            except json.JSONDecodeError:
                last_error = f"invalid translation JSON: {exc}: {output[:500]}"
                continue
        expected = {key for key, _ in batch}
        if set(data) == expected and all(isinstance(v, str) for v in data.values()):
            return data
        last_error = f"translation response keys mismatch: expected {len(expected)}, got {len(data)}"
    raise RuntimeError(last_error)


def translate(batch_size: int, limit: int | None, workers: int, worker: int) -> None:
    if workers < 1 or worker < 0 or worker >= workers:
        raise ValueError("worker must satisfy 0 <= worker < workers")
    catalog = load_catalog()
    pending = [(k, v) for k, v in catalog["entries"].items() if not v.get("translation")]
    # Translate long custom MDX bodies first so the expensive prose-heavy work
    # is checkpointed early; then process the remaining strings by context.
    pending.sort(
        key=lambda item: (
            0 if any(context.endswith(":body") for context in item[1]["contexts"]) else 1,
            -len(item[1]["source"]),
            item[0],
        )
    )
    pending = [item for item in pending if int(item[0], 16) % workers == worker]
    completed = 0

    def process_batch(batch: list[tuple[str, dict[str, Any]]]) -> int:
        """Translate a batch, recursively splitting malformed large responses."""
        try:
            translated = call_hermes(batch)
        except RuntimeError as exc:
            if len(batch) == 1:
                raise
            midpoint = len(batch) // 2
            print(
                f"worker={worker}/{workers} splitting batch={len(batch)} after: {str(exc)[:160]}",
                flush=True,
            )
            return process_batch(batch[:midpoint]) + process_batch(batch[midpoint:])
        latest = merge_translations(translated)
        remaining = sum(not entry.get("translation") for entry in latest["entries"].values())
        print(f"worker={worker}/{workers} checkpoint={len(batch)} remaining={remaining}", flush=True)
        return len(batch)

    for number, batch in enumerate(chunk_entries(pending, batch_size), start=1):
        if limit is not None and completed >= limit:
            break
        if limit is not None:
            batch = batch[: max(0, limit - completed)]
        completed += process_batch(batch)
        print(f"worker={worker}/{workers} batch={number} translated={completed}", flush=True)
    print(f"worker={worker}/{workers} translated this run={completed}")


def translation(catalog: dict[str, Any], source: str) -> str:
    entry = catalog["entries"].get(key_for(source))
    if not entry or entry.get("source") != source or not entry.get("translation"):
        raise KeyError(f"missing translation: {source[:100]!r}")
    return entry["translation"]


def localize_tree(node: Any, catalog: dict[str, Any], path: tuple[str, ...] = ()) -> Any:
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in TRANSLATABLE_KEYS and isinstance(value, str) and value.strip():
                if is_translatable_spec_field(path, key):
                    result[key] = translation(catalog, value)
                    continue
            result[key] = localize_tree(value, catalog, path + (str(key),))
        return result
    if isinstance(node, list):
        return [localize_tree(value, catalog, path + (str(index),)) for index, value in enumerate(node)]
    return node


def replace_frontmatter_value(frontmatter: str, field: str, value: str) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    # Replace either a scalar or a YAML folded/literal block up to the next
    # non-indented frontmatter key.
    pattern = rf"^{re.escape(field)}:\s*.*?(?=\n\S|\Z)"
    match = re.search(pattern, frontmatter, re.M | re.S)
    if not match:
        return frontmatter
    return frontmatter[:match.start()] + f"{field}: {encoded}" + frontmatter[match.end():]


def generate() -> None:
    catalog = load_catalog()
    missing = [e["source"] for e in catalog["entries"].values() if not e.get("translation")]
    if missing:
        raise SystemExit(f"catalog has {len(missing)} untranslated strings; run translate first")

    ZH_OPENAPI_DIR.mkdir(parents=True, exist_ok=True)
    for spec_path in referenced_spec_paths():
        try:
            source = json.loads(spec_path.read_text())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid OpenAPI JSON {spec_path.relative_to(ROOT)}: {exc}") from exc
        localized = localize_tree(source, catalog)
        (ZH_OPENAPI_DIR / spec_path.name).write_text(json.dumps(localized, ensure_ascii=False, indent=2) + "\n")

    generated = 0
    for mdx_path in sorted(API_DIR.rglob("*.mdx")):
        text = mdx_path.read_text()
        frontmatter, body = split_frontmatter(text)
        if "openapi:" not in frontmatter:
            continue
        title = frontmatter_value(frontmatter, "title")
        description = frontmatter_value(frontmatter, "description")
        excerpt = frontmatter_value(frontmatter, "excerpt")
        if title:
            frontmatter = replace_frontmatter_value(frontmatter, "title", translation(catalog, title))
        if description:
            frontmatter = replace_frontmatter_value(frontmatter, "description", translation(catalog, description))
        if excerpt:
            frontmatter = replace_frontmatter_value(frontmatter, "excerpt", translation(catalog, excerpt))
        frontmatter = re.sub(
            r'^(openapi:\s*["\']?)openapi/',
            r'\1openapi/zh/',
            frontmatter,
            count=1,
            flags=re.M,
        )
        localized_body = translation(catalog, body) if body.strip() else body
        # Route links between localized API pages to the canonical Chinese mirror.
        localized_body = localized_body.replace("](/api-reference/", "](/zh/api-reference/")
        localized_body = localized_body.replace('href="/api-reference/', 'href="/zh/api-reference/')
        target = ZH_API_DIR / mdx_path.relative_to(API_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"---\n{frontmatter}\n---\n{localized_body}")
        generated += 1
    print(f"generated specs={len(list(ZH_OPENAPI_DIR.glob('*.json')))} mdx={generated}")


def find_language_block(docs: dict[str, Any], language: str) -> dict[str, Any]:
    for block in docs.get("navigation", {}).get("languages", []):
        if block.get("language") == language:
            return block
    raise KeyError(f"language navigation not found: {language}")


def find_api_tab(language_block: dict[str, Any]) -> dict[str, Any]:
    for tab in language_block.get("tabs", []):
        if tab.get("tab") in {"API Reference", "API 参考"}:
            return tab
    raise KeyError("API Reference tab not found")


def collect_nav_labels(node: Any, labels: set[str]) -> None:
    if isinstance(node, dict):
        for key in ("tab", "group"):
            value = node.get(key)
            if isinstance(value, str):
                labels.add(value)
        for value in node.values():
            collect_nav_labels(value, labels)
    elif isinstance(node, list):
        for value in node:
            collect_nav_labels(value, labels)


def extract_nav() -> None:
    docs = json.loads((ROOT / "docs.json").read_text())
    api_tab = find_api_tab(find_language_block(docs, "en"))
    labels: set[str] = set()
    collect_nav_labels(api_tab, labels)
    existing = json.loads(NAV_LABELS_PATH.read_text()) if NAV_LABELS_PATH.exists() else {}
    output = {label: existing.get(label, "") for label in sorted(labels)}
    output["API Reference"] = "API 参考"
    NAV_LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    NAV_LABELS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"navigation labels={len(output)} untranslated={sum(not value for value in output.values())}")


def translate_nav() -> None:
    labels = json.loads(NAV_LABELS_PATH.read_text())
    pending = {key: value for key, value in labels.items() if not value}
    if not pending:
        print("navigation labels already translated")
        return
    prompt = f"""Translate these AIsa API documentation navigation labels into concise Simplified Chinese.
Return ONLY one valid JSON object with exactly the same English keys and Chinese values.
Preserve product/provider/protocol names such as OpenAI, Twitter, Tavily, Perplexity, DataForSEO, Apollo, AgentMail, Reddit, Instagram, Pinterest, CoinGecko, x402.
INPUT JSON:
{json.dumps(pending, ensure_ascii=False)}
"""
    result = subprocess.run(
        ["hermes", "-z", prompt, "--ignore-rules", "--safe-mode"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])
    output = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.stdout.strip(), flags=re.S)
    translated = json.loads(output)
    if set(translated) != set(pending):
        raise RuntimeError("navigation translation keys mismatch")
    labels.update(translated)
    NAV_LABELS_PATH.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + "\n")
    print(f"translated navigation labels={len(pending)}")


def localize_nav_node(node: Any, labels: dict[str, str]) -> Any:
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in {"tab", "group"} and isinstance(value, str):
                translated = labels.get(value)
                if not translated:
                    raise KeyError(f"missing navigation label: {value}")
                result[key] = translated
            else:
                result[key] = localize_nav_node(value, labels)
        return result
    if isinstance(node, list):
        return [localize_nav_node(value, labels) for value in node]
    if isinstance(node, str) and (node == "api-reference" or node.startswith("api-reference/")):
        return "zh/" + node
    return node


def sync_nav() -> None:
    docs_path = ROOT / "docs.json"
    docs = json.loads(docs_path.read_text())
    labels = json.loads(NAV_LABELS_PATH.read_text())
    en_tab = find_api_tab(find_language_block(docs, "en"))
    localized = localize_nav_node(copy.deepcopy(en_tab), labels)
    localized["tab"] = "API 参考"
    zh_block = find_language_block(docs, "zh")
    tabs = zh_block.get("tabs", [])
    for index, tab in enumerate(tabs):
        if tab.get("tab") == "API 参考":
            tabs[index] = localized
            break
    else:
        tabs.append(localized)
    docs_path.write_text(json.dumps(docs, ensure_ascii=False, indent=2) + "\n")
    print("Chinese API navigation synchronized")


def strip_translatable(node: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in TRANSLATABLE_KEYS and isinstance(value, str):
                if is_translatable_spec_field(path, key):
                    result[key] = "<translated>"
                    continue
            result[key] = strip_translatable(value, path + (str(key),))
        return result
    if isinstance(node, list):
        return [strip_translatable(value, path + (str(index),)) for index, value in enumerate(node)]
    return node


def validate() -> None:
    failures: list[str] = []
    source_specs = referenced_spec_paths()
    for source_path in source_specs:
        target_path = ZH_OPENAPI_DIR / source_path.name
        if not target_path.exists():
            failures.append(f"missing localized spec: {target_path.relative_to(ROOT)}")
            continue
        try:
            source = json.loads(source_path.read_text())
            target = json.loads(target_path.read_text())
        except json.JSONDecodeError as exc:
            failures.append(f"invalid JSON: {exc}")
            continue
        if strip_translatable(source) != strip_translatable(target):
            failures.append(f"structural difference: {source_path.name}")

    source_pages = []
    for source_path in sorted(API_DIR.rglob("*.mdx")):
        frontmatter, _ = split_frontmatter(source_path.read_text())
        if "openapi:" not in frontmatter:
            continue
        source_pages.append(source_path.relative_to(API_DIR))
        target_path = ZH_API_DIR / source_path.relative_to(API_DIR)
        if not target_path.exists():
            failures.append(f"missing localized MDX: {target_path.relative_to(ROOT)}")
            continue
        target_text = target_path.read_text()
        target_frontmatter, _ = split_frontmatter(target_text)
        if "openapi/zh/" not in target_frontmatter:
            failures.append(f"localized MDX does not reference zh spec: {target_path.relative_to(ROOT)}")
        source_excerpt = frontmatter_value(frontmatter, "excerpt")
        target_excerpt = frontmatter_value(target_frontmatter, "excerpt")
        if source_excerpt and (not target_excerpt or target_excerpt == source_excerpt):
            failures.append(f"untranslated localized MDX excerpt: {target_path.relative_to(ROOT)}")
        if re.search(r'(?:\]\(|href=["\'])/api-reference/', target_text):
            failures.append(f"localized MDX links to English API route: {target_path.relative_to(ROOT)}")

    docs = json.loads((ROOT / "docs.json").read_text())
    en_tab = find_api_tab(find_language_block(docs, "en"))
    zh_tab = find_api_tab(find_language_block(docs, "zh"))

    def nav_pages(node: Any) -> list[str]:
        result: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "pages" and isinstance(value, list):
                    for page in value:
                        if isinstance(page, str):
                            result.append(page)
                        else:
                            result.extend(nav_pages(page))
                elif isinstance(value, (dict, list)):
                    result.extend(nav_pages(value))
        elif isinstance(node, list):
            for value in node:
                result.extend(nav_pages(value))
        return result

    en_pages = nav_pages(en_tab)
    zh_pages = nav_pages(zh_tab)
    expected_zh_pages = ["zh/" + page for page in en_pages]
    if zh_pages != expected_zh_pages:
        failures.append("Chinese API navigation page sequence differs from English mirror")
    for page in zh_pages:
        if not (ROOT / f"{page}.mdx").exists():
            failures.append(f"missing Chinese navigation target: {page}")

    manual_pages = {"errors.mdx", "rate-limits.mdx", "credits-balance.mdx"}
    extra = sorted(
        p.relative_to(ZH_API_DIR)
        for p in ZH_API_DIR.rglob("*.mdx")
        if p.relative_to(ZH_API_DIR) not in source_pages and p.name not in manual_pages
    )
    # zh/api-reference.mdx itself is a hand-written overview and intentionally extra.
    extra = [p for p in extra if str(p) != "."]
    if extra:
        failures.append(f"unexpected generated pages: {len(extra)}")

    if failures:
        print("\n".join(failures[:100]), file=sys.stderr)
        raise SystemExit(1)
    print(f"validation passed: specs={len(source_specs)} pages={len(source_pages)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("extract")
    translate_parser = sub.add_parser("translate")
    translate_parser.add_argument("--batch-size", type=int, default=20)
    translate_parser.add_argument("--limit", type=int)
    translate_parser.add_argument("--workers", type=int, default=1)
    translate_parser.add_argument("--worker", type=int, default=0)
    sub.add_parser("generate")
    sub.add_parser("validate")
    sub.add_parser("extract-nav")
    sub.add_parser("translate-nav")
    sub.add_parser("sync-nav")
    args = parser.parse_args()
    if args.command == "extract":
        extract()
    elif args.command == "translate":
        translate(args.batch_size, args.limit, args.workers, args.worker)
    elif args.command == "generate":
        generate()
    elif args.command == "validate":
        validate()
    elif args.command == "extract-nav":
        extract_nav()
    elif args.command == "translate-nav":
        translate_nav()
    elif args.command == "sync-nav":
        sync_nav()


if __name__ == "__main__":
    main()
