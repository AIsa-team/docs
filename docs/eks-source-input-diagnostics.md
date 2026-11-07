# Reviewed source inputs from the existing EKS export

This lane qualifies only an exact source-input PR against an independently
selected diagnostic. It does not publish a contract, approve a full Runtime
release, refresh an acquisition timestamp, change `current`, or notify consumers.
The strict compiler still rejects incomplete definitions with typed exit 78.
The separate receipt says `source_input_diagnostic_compatible`,
`strict_verdict: readiness_rejected`, `formal_publication: false`, and zero artifacts.

The public production `/info/openapi.json` can serve the last formal artifact.
Use the existing protected `aisa-infra` `integration-catalog-export.yml`
publication export for current production observations; do not turn off Runtime
publication serving to obtain fresh facts.

## Ordering and authority

1. Merge the reader code through its own normal code PR first.
2. Merge that main commit **B** into the source branch without rewriting reviewed
   source ancestors. Freeze the resulting exact source head **R**. The reader's
   trusted code **Q must equal B**, and B must be an ancestor of R.
3. Independently review B..R and run the full existing strict compiler against the
   authenticated export. Record the actual v3 bundle manifest hash and complete
   typed diagnostic hash and counts. The diagnostic hash includes all provider,
   operation, path, reason, and summary details; matching counts alone is invalid.
4. An authorized operator sets `CONTRACT_EKS_INPUT_DIAGNOSTIC_BINDING` as a Docs
   repository variable, outside the source PR. Never obtain an expected verdict
   or authorization from a file supplied by R. Issue a real UTC lease of at most
   one hour after preparation; do not relabel capture or source-review clocks.
5. Re-run the exact source PR checks. Only a matching operator selection uses the
   EKS lane. Invalid matching selections fail closed. An unrelated selection is
   inert. After assessment, clear the one-use repository variable.

The existing `AISA_CI_READ_APP_ID` / `AISA_CI_READ_APP_PRIVATE_KEY` installation
must allow **read-only contents and Actions** access to `AIsa-team/docs`,
`AIsa-team/AIsaServices`, and `AIsa-team/aisa-infra`. No new App, secret, producer
signature service, or write permission is needed. An access failure is not a
reason to bypass authentication.

## Exact operator binding

`scripts/read_eks_source_input.py:validate_binding` defines a closed v1 object:

- `schema_version: 1`, `scope: eks_source_input_diagnostic_compatibility_only_not_formal_readiness`.
- `docs_pr`, `base_revision`, `head_revision`, `trusted_code_revision` (B, R, B).
- `changed_paths_sha256`: SHA256 of the sorted B..R path list encoded with
  `schema_input_bundle.canonical` (compact sorted-key JSON plus one newline).
- `bundle_manifest_sha256`: the actual v3 bundle exported from exact R.
- `infra_source`, `workflow_sha256`: protected infra main and the exact workflow
  bytes there. The reader requires main to remain at this source during checking.
- `run_id`, `run_attempt`, `jobs`: exact successful `tests` and `collect` job IDs
  and names. A rerun or skipped prerequisite invalidates the selection.
- `artifact_id`, `artifact_zip_sha256`, `artifact_gzip_sha256`: GitHub archive
  identity/digest and original compressed transport digest, independently checked.
- `snapshot_pins`: `snapshot_sha256`, `generation`, `source_digest`,
  `compiler_revision` from original Go-validated materialization.
- `diagnostic_expectation`: `normalization: complete_readiness_multiset_v1`,
  `diagnostic_sha256`, `provider_count`, `blocked_provider_count`,
  `diagnostic_entry_count` from an actual completed strict rejection.
- `issued_at`, `expires_at`: actual UTC operator selection times, not acquisition.

Use the existing local tools from trusted Q for preparation:

```sh
python "$DOCS_Q/scripts/export_schema_input_bundle.py" \
  --repo "$DOCS_REPO" --docs-ref "$DOCS_R" \
  --baseline-ref 78ef376841ead8cde10a79651958790be5a0531c \
  --bundle-version 3 --output "$NEW_BUNDLE"

# Run in the exact Services compiler_revision checkout, with original export JSON.
GOWORK=off GOFLAGS=-mod=readonly go run "$DOCS_Q/scripts/materialize_eks_snapshot.go" \
  "$ORIGINAL_SNAPSHOT_JSON" "$NEW_SNAPSHOT"

python "$DOCS_Q/scripts/internal_publication_snapshot.py" \
  --bundle "$NEW_BUNDLE" --bundle-sha256 "$BUNDLE_SHA256" --docs-ref "$DOCS_R" \
  --snapshot "$NEW_SNAPSHOT" --snapshot-sha256 "$SNAPSHOT_SHA256" \
  --generation "$GENERATION" --source-digest "$SOURCE_DIGEST" \
  --compiler-revision "$SERVICES_REVISION" --output "$NEW_SHADOW_OUTPUT"
```

The final command must really finish and return the closed typed rejection and
exit 78 before its diagnostic can be reviewed as an expectation. A timeout,
crash, generic exception, unknown diagnostic field, or an incomplete log is not
an expected readiness rejection. An unexpected strict success also fails this
diagnostic lane; use the ordinary full readiness flow for success.

## CI guarantees and limits

The workflow checks out B separately and runs its reader with isolated Python
imports. R cannot supply executable code, tests, CI, deferral-policy or rebinding
changes through this lane; the existing source-only classifier is further
restricted for these cases. The exact diff and current PR/main are rechecked.
Source governance is assessed before and after compilation using the existing
policy; no source age, receipt, reviewer, or readiness requirement is loosened.

The reader independently authenticates GitHub producer metadata and archive
digest, accepts exactly four bounded regular artifact files, validates original
Go types and `ValidatePublicationSnapshot`, then calls the existing Python
snapshot loader and strict compilation core. It rechecks producer attempt,
protected source, PR identity, source governance, and selection lease after the
slow compile. Only the final narrow receipt is uploaded; private snapshot
contents and credentials are not uploaded by this workflow.

Only a PR head matching the independent EKS variable receives a 20-minute CI
job limit (including acquisition and cold Go compilation); unselected checks
retain 10 minutes. This does not change the production compiler's timeout or the
separate proposed worker budget. The measured local production replay took
396.93 seconds before Go/toolchain setup, so 10 minutes left little total margin.

No selection means the original public Runtime acquisition and formal/source
checks run unchanged. A later push to main still runs ordinary strict checks;
this input-only receipt does not promise those are green or update formal
exports. Human-facing reference pages remain a separate existing
`sync_prod_runtime.py` update from a verified export, with pending pages labeled
honestly until their definitions are complete.
