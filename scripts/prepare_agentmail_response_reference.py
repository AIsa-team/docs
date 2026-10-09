"""Prepare owning AgentMail no-content declarations for independent review.

Offline composite importer. It retains the locked request authority and selects
eleven explicit owning success declarations. It never claims execution proof.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import yaml
from import_upstream import OfficialSourceLoader
from source_governance import initial_policy
from compose_openapi import digest

REVISION = "a7936224861284c48b6a98f731aa5c76b47d1e32"
URL = f"https://raw.githubusercontent.com/agentmail-to/agentmail-docs/{REVISION}/openapi/openapi.yml"
RAW_SHA256 = "fc782abbbdacce91c27397a78f3aaa5f2fd3d347d74937600541e799febdf223"
OPERATIONS = (
    ("delete", "/v0/api-keys/{api_key_id}"),
    ("delete", "/v0/domains/{domain_id}"),
    ("post", "/v0/domains/{domain_id}/verify"),
    ("delete", "/v0/inboxes/{inbox_id}"),
    ("delete", "/v0/inboxes/{inbox_id}/api-keys/{api_key_id}"),
    ("delete", "/v0/inboxes/{inbox_id}/drafts/{draft_id}"),
    ("delete", "/v0/inboxes/{inbox_id}/lists/{direction}/{type}/{entry}"),
    ("delete", "/v0/inboxes/{inbox_id}/messages/{message_id}"),
    ("delete", "/v0/inboxes/{inbox_id}/threads/{thread_id}"),
    ("delete", "/v0/lists/{direction}/{type}/{entry}"),
    ("delete", "/v0/threads/{thread_id}"),
)


def extract(document):
    if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith("3."):
        raise ValueError("owning OpenAPI 3 declaration required")
    paths = {}
    for method, path in OPERATIONS:
        operation = document.get("paths", {}).get(path, {}).get(method)
        if not isinstance(operation, dict) or "$ref" in operation:
            raise ValueError("exact owning method/path declaration missing")
        responses = operation.get("responses", {})
        success = {status: value for status, value in responses.items()
                   if isinstance(status, str) and status.startswith("2")}
        if set(success) != {"204"} or success["204"] != {"description": ""}:
            raise ValueError("reviewed explicit 204 no-content declaration changed")
        # An HTTP 204 formally has no body; do not infer a JSON null/object schema.
        paths.setdefault(path, {})[method] = {"responses": copy.deepcopy(success)}
    return {"openapi": "3.1.0", "info": {"title": "AgentMail owning no-content responses", "version": REVISION}, "paths": paths}


BASE_REVISION = "e98e7918260a821397fbd1062da8d1cd9d43bf29"
BASE_URL = f"https://raw.githubusercontent.com/AIsa-team/docs/{BASE_REVISION}/openapi/upstream/agentmail-official.json"
BASE_SHA256 = "70ec3d05b562a1b19e442480c3c071607e3133780b898db05c1fcf548b7108aa"


def merge(base, owning):
    """Preserve the complete locked request graph; replace eleven successes only."""
    selected = extract(owning)
    result = copy.deepcopy(base)
    for method, path in OPERATIONS:
        original = result.get("paths", {}).get(path, {}).get(method)
        if not isinstance(original, dict):
            raise ValueError("locked request method/path missing")
        responses = original.get("responses", {})
        success = {s: v for s, v in responses.items() if str(s).startswith("2")}
        if success != {"200": {"description": "Successful response"}}:
            raise ValueError("locked hosted success contract changed")
        original["responses"] = {s: v for s, v in responses.items() if s != "200"}
        original["responses"].update(copy.deepcopy(selected["paths"][path][method]["responses"]))
    return result


def prepare(base_raw, raw, fetched_at):
    if hashlib.sha256(raw).hexdigest() != RAW_SHA256 or hashlib.sha256(base_raw).hexdigest() != BASE_SHA256:
        raise ValueError("pinned source bytes changed; independent review required")
    base = json.loads(base_raw)
    result = merge(base, yaml.load(raw, Loader=OfficialSourceLoader))
    original_source = result["info"].pop("x-aisa-source")
    source = {"kind": "manual", "url": URL, "fetched_at": fetched_at,
              "content_hash": digest(result), "converter": "scripts/prepare_agentmail_response_reference.py@1",
              "source_git_revision": REVISION, "raw_content_hash": "sha256:" + RAW_SHA256,
              "source_pages": [{"url": URL, "raw_content_hash": "sha256:" + RAW_SHA256, "scope": "Eleven explicitly declared HTTP 204 success responses only"},
                               {"url": BASE_URL, "raw_content_hash": "sha256:" + BASE_SHA256, "scope": "All other locked request/response/component semantics including five retained operations"}],
              "retained_request_source": original_source,
              "response_overrides": [method.upper() + " " + path for method, path in OPERATIONS],
              "hosted_status_conflict": "Hosted generated source declares description-only 200; owning pinned fern-openapi output explicitly declares204. Selected formal204 only for eleven reviewed methods; no business-call status verification.",
              "refresh_policy": "pinned", "refresh_reason": "Composite source preserves hosted requests and eleven owning generated 204 responses. Refresh both pinned inputs and independently review before changing either authority."}
    result["info"]["x-aisa-source"] = initial_policy(source)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--fetched-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    result = prepare(args.base.read_bytes(), args.raw.read_bytes(), args.fetched_at)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
