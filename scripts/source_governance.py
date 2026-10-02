"""Source maintenance declarations and observational receipts, never wire policy.

Maintenance fields live only in info.x-aisa-source. Receipts live in workflow
reports/cache, keyed by source content hash and maintenance policy revision.
Local rereads and fetched_at do not count as successful manual reviews.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

POLICY_FIELDS = ("owner", "refresh_policy", "review_period_days", "refresh_interval_hours", "refresh_reason")
MODES = {"automatic", "manual", "pinned"}


def policy_revision(source):
    policy = {key: source[key] for key in POLICY_FIELDS if key in source}
    policy["authority_url"] = source.get("url")
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def initial_policy(source, owner="AIsa-team/docs"):
    """Declare repository ownership; deliberately creates no review receipt."""
    value = copy.deepcopy(source)
    mode = value.get("refresh_policy")
    if mode not in MODES:
        mode = "automatic" if value.get("kind") == "provider_openapi" else "manual"
    value.update(owner=owner, refresh_policy=mode, review_period_days=30)
    if mode == "automatic":
        value["refresh_interval_hours"] = 24
    else:
        value.pop("refresh_interval_hours", None)
    value["policy_revision"] = policy_revision(value)
    return value


def policy_errors(source):
    errors = []
    if not isinstance(source.get("owner"), str) or not source["owner"].strip():
        errors.append("missing_owner")
    if source.get("refresh_policy") not in MODES:
        errors.append("missing_or_invalid_policy")
    if not isinstance(source.get("url"), str) or not source["url"].startswith("https://"):
        errors.append("missing_authority")
    if type(source.get("review_period_days")) is not int or not 0 < source["review_period_days"] <= 30:
        errors.append("invalid_review_period")
    if source.get("refresh_policy") == "automatic" and (type(source.get("refresh_interval_hours")) is not int or not 0 < source["refresh_interval_hours"] <= 24):
        errors.append("invalid_refresh_interval")
    if source.get("refresh_policy") == "pinned" and not source.get("refresh_reason"):
        errors.append("missing_pin_reason")
    if source.get("policy_revision") != policy_revision(source):
        errors.append("missing_or_stale_policy_revision")
    if not source.get("content_hash"):
        errors.append("missing_source_hash")
    return errors


def receipt_key(source):
    return str(source.get("content_hash", "")) + "|" + str(source.get("policy_revision", ""))


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def validate_receipt(source, receipt, now):
    """Validate attribution and binding, not authenticity or provider uptime."""
    if not isinstance(receipt, dict) or policy_errors(source):
        return False
    if receipt.get("source_hash") != source.get("content_hash") or receipt.get("policy_revision") != source.get("policy_revision"):
        return False
    at = timestamp(receipt.get("last_successful_review_at"))
    if at is None or at > now or receipt.get("result") != "confirmed":
        return False
    evidence = receipt.get("evidence", {})
    if not isinstance(evidence, dict) or not isinstance(evidence.get("url"), str) or not evidence["url"].startswith("https://"):
        return False
    if source["refresh_policy"] == "automatic":
        return evidence.get("kind") == "official_acquisition" and evidence["url"] == source["url"]
    # A manual/pinned review must be explicitly attributed, backed by official
    # evidence and immutable review provenance; cache rereads are insufficient.
    return (evidence.get("kind") in {"official_documentation", "official_release", "provider_confirmation"}
            and isinstance(receipt.get("reviewer"), str) and bool(receipt["reviewer"].strip())
            and bool(re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("review_ref", "")))))


def observation(source, receipts, checked_at, status=None):
    key = receipt_key(source)
    receipt = receipts.get(key) if isinstance(receipts, dict) else None
    valid = validate_receipt(source, receipt, checked_at)
    last = timestamp(receipt.get("last_successful_review_at")) if valid else None
    due = last + timedelta(days=source["review_period_days"]) if last else None
    mode = source.get("refresh_policy")
    errors = policy_errors(source)
    if errors or not valid:
        freshness = "unknown"
    elif due <= checked_at or (mode == "automatic" and last + timedelta(hours=source["refresh_interval_hours"]) <= checked_at):
        freshness = "overdue"
    else:
        freshness = "fresh"
    if status == "fetch_failed":
        freshness = "fetch_failed"
    signal = receipt.get('latest_revision') if isinstance(receipt, dict) else None
    if mode == 'pinned' and isinstance(signal, dict) and signal.get('source_hash') != source.get('content_hash'):
        freshness, status = 'overdue', 'pinned_update_available'
    outcome = status
    if outcome is None:
        if errors or not valid:
            outcome = "unknown"
        elif mode == "manual":
            outcome = "manual_overdue" if freshness == "overdue" else "manual_due"
        elif mode == "pinned":
            outcome = "pinned"
        else:
            outcome = "unchanged"
    return {"status": outcome, "freshness": freshness, "owner": source.get("owner"),
            "policy": mode, "policy_revision": source.get("policy_revision"),
            "source_hash": source.get("content_hash"), "authority_url": source.get("url"),
            "source_as_of": source.get("fetched_at"), "checked_at": checked_at.isoformat(),
            "last_successful_review_at": last.isoformat() if last else None,
            "review_due_at": due.isoformat() if due else None,
            "next_acquisition_due_at": (last + timedelta(hours=source["refresh_interval_hours"])).isoformat() if last and mode == "automatic" else None,
            "review_key": key, "evidence": copy.deepcopy(receipt.get("evidence")) if valid else None,
            "latest_revision_signal": copy.deepcopy(signal),
            "policy_errors": errors, "compatibility": "not_assessed"}


def acquisition_receipt(source, checked_at):
    return {"source_hash": source.get("content_hash"), "policy_revision": source.get("policy_revision"),
            "checked_at": checked_at.isoformat(), "last_successful_review_at": checked_at.isoformat(),
            "result": "confirmed", "evidence": {"kind": "official_acquisition", "url": source.get("url")},
            "compatibility": "not_assessed"}


def source_report(root, receipts=None, checked_at=None, attempts=None):
    checked_at = checked_at or datetime.now(timezone.utc)
    receipts = receipts or {}
    sources = {}
    for path in sorted((root / "openapi/upstream").glob("*.json")):
        source = json.loads(path.read_text()).get("info", {}).get("x-aisa-source", {})
        attempt = (attempts or {}).get(receipt_key(source), {})
        receipt = receipts.get(receipt_key(source), {})
        attempted_at = timestamp(attempt.get('checked_at'))
        reviewed_at = timestamp(receipt.get('last_successful_review_at'))
        failed_latest = attempt.get('status') == 'fetch_failed' and attempted_at and attempted_at <= checked_at and (not reviewed_at or attempted_at > reviewed_at)
        sources[path.name] = observation(source, receipts, checked_at, 'fetch_failed' if failed_latest else None)
    errors = {name: row['policy_errors'] for name, row in sources.items() if row['policy_errors']}
    failed = bool(errors) or any(row['freshness'] in {'overdue', 'fetch_failed'} for row in sources.values())
    return {"schema_version": 1, "checked_at": checked_at.isoformat(), "sources": sources, 'policy_errors': errors,
            "status": 'failed' if failed else ("passed" if sources and all(row["freshness"] == "fresh" for row in sources.values()) else "not_assessed"),
            "scope": "source maintenance evidence only; not provider compatibility or execution"}
