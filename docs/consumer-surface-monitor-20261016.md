# Public consumer acceptance coverage

The existing `check_contract_revisions.py --all-surfaces` check now compares
`https://api.aisa.one/openapi.json` with the **payment subset** at
`discovery/openapi.json` in the independently selected formal Docs commit.
It never compares that payment endpoint with the full ordinary API catalogue.
The expected bytes must match that commit's passed publication manifest.

The static consumer is a byte-for-byte mirror, so serialization changes fail
the exact-byte check. An additional complete JSON comparison distinguishes
formatting drift from endpoint, HTTP method, parameter, payment amount, currency,
or other contract drift. Business schema properties are not filtered by name.
Absent formal payment evidence or an unavailable public endpoint cannot pass.

An unavailable Website no longer suppresses independent Runtime/Router
comparisons. The overall assessment remains `not_assessed` when evidence is
missing; independently detectable mismatches are retained in the same report.
Existing timing, two-observation escalation and last-good publication policies
are unchanged. No new monitor or service is introduced.

This check still verifies MCP loaded-source provenance and its llms index,
not authenticated MCP `get_details` output. Router native/executable schema
checks and MCP adapter checks must report their own field-level scope rather
than treating source hashes as complete execution evidence.

Validation:

```sh
python3 -m unittest scripts.tests.test_public_surface_checks scripts.tests.test_contract_revisions
```

Regressions cover payment price, parameter, HTTP method and path drift, exact
mirror bytes, missing evidence, and Router drift while Website is unavailable.
The release acceptance command continues to require the independently recorded
formal SHA, selection file and original budget start. Never reset that clock to
make a delayed deployment pass.

## Visible bilingual documentation

`--all-surfaces` also reads the actual public HTML for 16 evenly spaced pages
per locale, including both ends of the sorted inventory, plus every disabled
page. It compares the complete visible request JSON and pricing summary with
the hash-bound MDX in the selected formal publication. Disabled pages must also
show the explicit localized notice. Script, style, template and hydration data
cannot satisfy this check. The report states the inventory, selected and
observed counts per locale; a successful sample is not full-page acceptance.
HTML `hidden` attributes and inline `display:none` / `visibility:hidden` are
excluded with their descendants. This is a server-rendered HTML audit, not a
browser computed-style or screenshot audit: external CSS and client-side DOM
mutations require separate browser verification. Each fetch has a 16 MiB cap,
a 20-second socket timeout and a 30-second read budget checked between chunks.

Use `--all-doc-pages --all-surfaces` for an explicit complete rendered-page
audit. This reads thousands of public HTML documents, so it is not the hourly
default. Offline HTML evidence uses `docs-page-<sha256(MDX path)>.html` names.
The existing hourly workflow automatically includes the bounded bilingual
sample; no new credentials, deployment service or scheduled workflow is needed.

The October 16 check found a real deployment gap: the 3,998-page status update
was visible through changed page 3,000, while sampled pages from 3,001 onward
retained old MDX even with cache Age 0. The precise boundary matches GitHub's
3,000-file commit API limit. This is evidence of an incremental deployment
truncation, not proof of Mintlify's internal implementation. Revalidating URLs
did not rebuild those stale page bodies. JSON and llms agreement alone therefore
cannot certify rendered documentation convergence.

Recovery requires a complete source rebuild or platform repair, followed by
the same public HTML checks. Mintlify's documented update API queues a deployment
but does not document a force-full-rebuild parameter. The repository currently
has no Mintlify admin API secret; this change detects the fault and does not
claim to have repaired the external deployment.

```sh
python3 -m unittest scripts.tests.test_rendered_page_checks scripts.tests.test_public_surface_checks scripts.tests.test_contract_revisions
```

Tests reject correct hydration hiding stale HTML, missing localized notices,
stale visible duplicates, and drift in method, path, parameters, price and schema
values. They cover Mintlify's actual heading anchors and nested paragraph spans.
