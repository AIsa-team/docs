<!--
Title: <type>(<scope>): <imperative summary> (<LINEAR-ID>)
  type:  docs | fix | feat | oracle | openapi | upstream | import | readiness | test | chore | revert
  scope: optional, e.g. zh, errors, duffel, unipile
  e.g.   docs(zh): restore $AISA_API_KEY in skill curl examples (AIS-263)
Delete sections that do not apply. Never paste real API keys or production payloads.
-->

## Why

<!-- The problem or trigger: Linear issue, failing run, live mismatch, upstream change. -->

Linear: AIS-

## Changes

<!-- One bullet per change, naming the file or page. Say what was intentionally left unchanged. -->

-

## Verification

<!-- Evidence, not assertions. Paste commands, live responses or measured tables, with the date. -->

- [ ] Commands, endpoints, model IDs and examples were run against the live API (date: YYYY-MM-DD)
- [ ] `python scripts/check_nav_integrity.py`
- [ ] `npx --yes mint@4.2.1006 broken-links --files '**/*.mdx' --check-redirects` (pages, navigation or redirects changed)
- [ ] `python -m unittest discover -s scripts/tests` (`scripts/` or `openapi/` changed)

## Checklist

- [ ] **EN/ZH aligned:** every edited page has its `zh/` counterpart updated, or the reason is stated above
- [ ] **No price figures:** pages describe billing semantics only
- [ ] **Generated files untouched by hand:** root `openapi.yaml` and runtime contract mirrors come from their scripts or workflows
- [ ] **New or moved pages** are wired into `docs.json`, and old URLs have redirects
- [ ] **No secrets:** examples use `$AISA_API_KEY`, never real keys or account data
