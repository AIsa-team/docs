# Source-only input recovery

A stale public publication can prevent reviewing the source inputs needed to
repair the producer. The normal formal-publication reader continues to require
fresh public current. The optional input-only path accepts a recent completed
qualification by the independently pinned Services workflow instead.

An operator explicitly dispatches Services `api-contract-e2e.yml` with the exact
closed request: source-only Docs PR/head/base, five target compiler pins,
independent old API/exporter revisions and an interval of at most one hour. The
qualifier verifies source-only intent, main-reachable Composer source hashes,
exact R/bundle bytes and current source policy/receipts. Both API binaries and
complete authenticated source are acquired before and after the complete
network-denied Composer execution using the existing trusted Go RunSnapshot.
No database/provider execution, image push, formal output or deployment occurs.
The passed receipt records its actual final acquisition clock. If that acquisition
crosses expiry, no passed qualification is issued.

For a normal Docs PR event, an operator may bind that exact reviewed result with
repository variable `CONTRACT_INPUT_RECOVERY_BINDING`. Its closed fields are
`schema_version` (1), `scope`
(`authenticated_current_source_input_qualification_only_not_formal_publication_or_promotion`),
`head_revision`, `base_revision`, `candidate_compiler_inputs` (the five normal
pins), `source_api_revision`, `source_export_revision`, `qualifier_revision`,
`run_id` (string), `run_attempt` (integer), `artifact_id` (string), `archive_sha256`,
`issued_at` and `expires_at`. Revisions and hashes are complete lowercase hex;
the operator interval is at most one hour. This selects only the exact source-only
PR head/base. Other PRs retain their existing acquisition and readiness checks.

Only selected recovery obtains the existing CI Read App token, scoped to
AIsaServices and docs with contents/actions read. Docs needs the existing App's
`AISA_CI_READ_APP_ID` variable and `AISA_CI_READ_APP_PRIVATE_KEY` secret from its
trusted secret store. No PAT, private key, API token or production address is
placed in an input/qualification artifact or in source. A private Services run's
identity is authenticated via the App and GitHub API, not an unsigned public blob.

The reader requires the exact successful workflow revision/run/attempt and its
contracts, MySQL and source-qualification jobs; the exact nonexpired artifact
identity and independent archive SHA; exact Q/R/source pins and unchanged cohort;
zero writes and input-only scope. It separately resolves the old source lock from
the reviewed exporter commit. It reexports R's actual bundle and rechecks current
source policy/receipts, while retaining the original independent Actions
sole-publisher verification of historical formal context F. A successful source
qualification does not replace that historical producer proof.

Qualification completion must be within 15 minutes and within the dispatched
request's interval. Download, Git export and historical producer verification can
be slow: immediately before writing a passed receipt the reader takes a new real
UTC clock and rechecks operator binding, request expiry, qualification age and
all source-policy freshness. GitHub variables are supplied through job/run
context; this is not a live variable-API revocation check. Cancel an active run
when immediate revocation is needed.

This scope proves authenticated source at the qualification instant. It does not
claim a CI-time current-source identity, fresh published current, formal output,
production activation or interface completeness. Warning110 public native files
and stale public artifact identity are never substitutes for acquisition.

Merge the code-only reader first. That advances Docs main: the source-only input
branch must then normally merge the new main, producing a new exact R and bundle
SHA. Recompute and independently review that pair; run a new qualification for
the new R/base and bind only that result. A pre-merge qualification for an older
R/base remains pipeline test evidence and cannot qualify the final input.
