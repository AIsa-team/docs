#!/usr/bin/env python3
"""Add an MCP tab beside the curl in every API reference page's Example.

A reader on an endpoint page is at the moment of intent: they want to call
this one thing. The page showed them one way to do it. The same operation is
reachable over MCP under a name they cannot guess, and nothing on the page
said so.

The name is not guessed here either. Each page's frontmatter says which spec
and which path it documents; that spec's `operationId` is what the MCP server
calls the operation — verified identical on 2026-09-16 — and the set of ids
the server actually serves is read from the server itself before anything is
written. An operation the MCP catalogue does not carry gets no MCP tab rather
than a call that would fail.

  python3 scripts/add_mcp_examples.py            # dry run, prints a summary
  python3 scripts/add_mcp_examples.py --write
  python3 scripts/add_mcp_examples.py --write --only api-reference/financial

Idempotent: a page already carrying an MCP tab is rewritten, not doubled, so
this can be re-run after the catalogue changes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_ORIGIN = "https://mcp.aisa.one"
CATALOGUE = f"{MCP_ORIGIN}/servers"

#: How a rerun recognises its own work. Not shown to anyone: a line saying
#: "this is an example" on a page whose heading is "Example" is a line that
#: costs a reader attention and tells them nothing.
MARK = "Register the AIsa MCP server"


# --- what the MCP server actually serves -----------------------------------

def _key() -> str:
    key = os.environ.get("AISA_API_KEY") or ""
    if not key:
        path = Path.home() / ".aisa" / "key"
        key = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not key:
        sys.exit("no AISA_API_KEY and no ~/.aisa/key — tools/list needs one")
    return key


def _rpc(url: str, key: str, method: str, params: dict | None = None) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    # Twenty-six endpoints, two calls each: on this link one TLS handshake
    # timing out is ordinary, and losing the whole enumeration to it is not.
    raw = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
            break
        except Exception:                       # noqa: BLE001 — any transport fault
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    # Streamable HTTP answers as SSE; the payload is the one `data:` line.
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(raw)


def mcp_operations() -> set[str]:
    """Every operation id this origin serves, from its own endpoints.

    Read rather than derived: the includes in aisa-mcp take `operations: "*"`
    from some specs and a named list from others, so a set computed from the
    specs alone would claim operations the server does not expose.
    """
    cache = Path(tempfile.gettempdir()) / "aisa-mcp-operations.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 3600:
        return set(json.loads(cache.read_text(encoding="utf-8")))
    key = _key()
    with urllib.request.urlopen(CATALOGUE, timeout=60) as r:
        catalogue = json.load(r)
    names: set[str] = set()
    for server in catalogue.get("servers", []):
        endpoint = (server.get("transport") or {}).get("endpoint")
        if not endpoint:
            continue
        _rpc(endpoint, key, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "add_mcp_examples", "version": "1"},
        })
        listed = _rpc(endpoint, key, "tools/list")
        for tool in listed.get("result", {}).get("tools", []):
            names.add(tool["name"])
    cache.write_text(json.dumps(sorted(names)), encoding="utf-8")
    return names


# --- what each page documents ----------------------------------------------

FRONT_OPENAPI = re.compile(r'^openapi:\s*"([^"]+)"\s*$', re.M)
EXAMPLE = re.compile(
    r"(?P<head>^##\s+(?:Example|示例)\s*\n+)"
    r"(?P<body>(?:```bash\n.*?\n```|<CodeGroup>.*?</CodeGroup>))",
    re.S | re.M)
CURL = re.compile(r"```bash(?:\s+\w+)?\n(?P<cmd>.*?)\n```", re.S)


def spec_operation_id(front_value: str) -> str | None:
    """`openapi/openapi-financial.json GET /earnings` -> its operationId."""
    parts = front_value.split()
    if len(parts) != 3:
        return None
    spec, method, path = parts
    try:
        doc = json.loads((ROOT / spec).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    item = (doc.get("paths") or {}).get(path) or {}
    return (item.get(method.lower()) or {}).get("operationId")


def curl_arguments(cmd: str) -> dict:
    """The example arguments the page already chose, reused rather than reinvented.

    A page that says `?ticker=NVDA` has picked a ticker that makes the response
    worth reading. Inventing a second example here would mean two sets of
    values to keep sensible.
    """
    try:
        parts = shlex.split(cmd.replace("\\\n", " "))
    except ValueError:
        return {}
    args: dict = {}
    for i, part in enumerate(parts):
        if part in ("-d", "--data", "--data-raw") and i + 1 < len(parts):
            try:
                payload = json.loads(parts[i + 1])
            except ValueError:
                continue
            if isinstance(payload, dict):
                args.update(payload)
        elif part.startswith("http") and "?" in part:
            query = part.split("?", 1)[1]
            for pair in query.split("&"):
                if "=" not in pair:
                    continue
                k, v = pair.split("=", 1)
                args[k] = v
    return args


DOCS = "https://aisa.one/docs"

#: The first line is for the person: it tells them the block is the whole
#: thing, not a fragment. Everything after the JSON is for their agent, and
#: it is the short form of the prompt on aisa.one/mcp — enough to register the
#: server, get through OAuth and run this exact call without a second page.
LEAD = {
    "en": [
        "// Copy this whole block into Claude Code, Codex, Cursor or any coding agent.",
        "// It carries everything needed to connect, authorize and run this example —",
        "// no key to paste, one click of Allow in the browser.",
    ],
    "zh": [
        "// 把整段复制给 Claude Code、Codex、Cursor 或任意 coding agent。",
        "// 连接、授权、跑通这个例子需要的东西都在里面 ——",
        "// 不用粘贴任何 key，浏览器里点一次 Allow 就好。",
    ],
}


def mcp_block(operation_id: str, args: dict, doc_path: str, lang: str) -> str:
    call = json.dumps(
        {"operation_id": operation_id, "arguments": args, "max_price_usd": 0.05},
        indent=2, ensure_ascii=False)
    lead = "\n".join(LEAD.get(lang, LEAD["en"]))
    return f"""```jsonc MCP
{lead}
{call}
// ── for the agent ─────────────────────────────────────────────────────────
// {MARK}, then call its `use` tool with the JSON above.
//   name       aisa
//   endpoint   {MCP_ORIGIN}/mcp
//   transport  streamable-http
//   auth       OAuth. The server publishes RFC 9728 metadata, so open a
//              browser and the user clicks Allow once — nothing to paste.
//              If AISA_API_KEY is set, send it as a bearer header instead.
// Use your own MCP mechanism, not a hand-edited config file:
//   Codex        codex mcp add aisa --url {MCP_ORIGIN}/mcp
//   Claude Code  claude mcp add --transport http -s user aisa {MCP_ORIGIN}/mcp
//   Cursor / VS Code   a "url" entry for {MCP_ORIGIN}/mcp in the MCP config
// The server lists five tools over {MCP_ORIGIN}/servers worth of APIs:
// search, get_details, use, batch_use, list_categories. search and
// get_details are free; use is billed per call and max_price_usd refuses
// anything above the cap before spending. This operation's full contract —
// every argument, the response shape, the price and the pitfalls — is at
//   {DOCS}/{doc_path}.md
// Then run the call and show me the result.
```"""


#: The one-time connection note, kept in snippets/ so the wording and the add
#: commands live in one file per language rather than in every page that
#: mentions them. Two files, not one: an English note on a translated page is
#: the kind of inconsistency the zh/ tree exists to avoid.
SNIPPET = {"en": "/snippets/mcp-setup.mdx", "zh": "/snippets/zh/mcp-setup.mdx"}
SNIPPET_TAG = "<McpSetup"

#: The one line that cannot live in the snippet.
#:
#: Two reasons, both measured. A snippet prop is substituted in markdown text
#: and nowhere else, so `?from={page}` inside a URL stays literal. And the
#: referrer cannot stand in for it: Mintlify renders an external markdown link
#: as `target="_blank" rel="noreferrer"`, and noreferrer empties
#: document.referrer, so the page being linked to learns nothing. The
#: parameter has to be in the href, and the href has to be written per page.
LINK = {
    "en": "[Set this endpoint up in your agent →]({url})",
    "zh": "[在你的 agent 里把这个端点跑起来 →]({url})",
}



def with_snippet(text: str, lang: str, doc_path: str) -> str:
    """Import the shared note, place it once, and follow it with this page's link.

    The prose is shared so it has one source; the link is generated because it
    cannot be shared — see LINK for why neither a snippet prop nor the referrer
    can carry the page identity.
    """
    line = f'import McpSetup from "{SNIPPET[lang]}";'
    link = LINK[lang].format(url=f"https://aisa.one/mcp?from=/{doc_path}")
    block = f"{SNIPPET_TAG} />\n\n{link}"
    if line not in text:
        end = text.index("---", 3) + 4
        text = text[:end] + "\n" + line + "\n" + text[end:]
    if SNIPPET_TAG in text:
        # Replace whatever a previous run left, link line included.
        text = re.sub(r"<McpSetup[^>]*/>(\n\n\[[^\]]*\]\([^)]*\))?", block, text)
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    return text


def rewrite(text: str, operation_id: str, doc_path: str, lang: str) -> str | None:
    """The new page text, None when there is nothing to work with, or the
    sentinel "current" when the page already says exactly this."""
    match = EXAMPLE.search(text)
    if not match:
        return None
    body = match.group("body")
    curl = CURL.search(body)
    if not curl:
        return None
    rest = f"```bash REST\n{curl.group('cmd')}\n```"
    mcp = mcp_block(operation_id, curl_arguments(curl.group("cmd")), doc_path, lang)
    block = f"<CodeGroup>\n{rest}\n\n{mcp}\n</CodeGroup>"
    if body == block:
        return "current"
    return text[:match.start("body")] + block + text[match.end("body"):]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", default="", help="limit to a path prefix")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--snippet", action="store_true",
                    help="also include the one-time connection note on each page")
    args = ap.parse_args()

    served = mcp_operations()
    print(f"mcp serves {len(served)} operations")

    pages = sorted(p for p in ROOT.glob("**/api-reference/**/*.mdx")
                   if str(p.relative_to(ROOT)).startswith(("api-reference/", "zh/api-reference/")))
    if args.only:
        pages = [p for p in pages if str(p.relative_to(ROOT)).startswith(args.only)]

    changed = skipped_no_mcp = no_frontmatter = no_example = unchanged = 0
    for page in pages:
        text = page.read_text(encoding="utf-8")
        front = FRONT_OPENAPI.search(text)
        if not front:
            no_frontmatter += 1
            continue
        op = spec_operation_id(front.group(1))
        if not op or op not in served:
            skipped_no_mcp += 1
            continue
        rel = str(page.relative_to(ROOT))
        doc_path = rel[:-len(".mdx")]
        lang = "zh" if rel.startswith("zh/") else "en"
        out = rewrite(text, op, doc_path, lang)
        if args.snippet:
            base = text if out in (None, "current") else out
            snipped = with_snippet(base, lang, doc_path)
            if snipped != base:
                out = snipped
        if out is None:
            no_example += 1
            continue
        if out == "current":
            unchanged += 1
            continue
        changed += 1
        if args.write:
            page.write_text(out, encoding="utf-8")
            print(f"  wrote {rel}  ({op})")
        else:
            print(f"  would write {rel}  ({op})")
        if args.limit and changed >= args.limit:
            break

    print(f"\n{changed} to change · {unchanged} already current · "
          f"{no_example} have no Example section to extend · "
          f"{skipped_no_mcp} not in the MCP catalogue · {no_frontmatter} no openapi frontmatter")
    if not args.write:
        print("dry run — pass --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
