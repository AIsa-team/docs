# API contract W0 acceptance package

This package freezes the evidence and expected results required by
`docs/api-contract-completion-spec.md`. W0 completion means the acceptance basis
is reproducible. Product CodeReady, ReleaseReady and complete enabled content
remain separate, unaccepted stages. No business implementation, workflow, source
lock, production baseline, database or provider account was changed here.

## Contents and authority

- `manifest.json`: exact five code revisions, archive and file byte hashes,
  endpoint accounting oracle, draft gap identities and known blockers.
- `../../scripts/api-contract-acceptance/data/full-catalog.tar.gz`: selected full
  inputs, sanitized public source/old-document inputs, portable proposed identity
  evidence and diagnostic composed outputs. No external temp directory is needed
  to verify it. Every included file is enumerated and hashed in the manifest.
- `inputs-audit.md`: source lineage, privacy selection and exact denominator
  reconciliation. The index was reconstructed from saved inventory; this is not
  a full live HTTP extraction from the new runtime or an approved identity import.
- `../../scripts/api-contract-acceptance/fixtures`: independent handwritten
  declaration assertions, schema examples, normalized graphs, conversion and
  explicit unresolved-reference expectations. Expectations never import target
  converter/resolver code.
- `scenarios.json`: C01-C14 input procedures, fixed expected results, ownership
  roles and unassessed execution state. Procedures requiring later code adapters
  or real release evidence are explicitly pending.
- `checks.json`, `gates.md`: code/release gate entrypoints and owner roles.
- `budgets.json`: inspected jobs, schedules/caches, frozen 60-minute candidate and
  4-hour convergence targets; both remain unproved by the current implementation.
- `timing-remediation.md`: concrete per-stage limits and cache/schedule changes
  proposed before implementation, with unknown operator caps left pending.

Hashes have different meanings. Archive SHA values bind literal fixture bytes;
runtime facts hashes, source hashes and Docs document hashes bind their own
semantic scopes. Sanitization does not approve or refresh a source. One ambiguous
personal email example is replaced with `example@example.invalid`; the archive's
`sanitization.json` records pointers and original/sanitized hashes. Diagnostic
expected outputs were regenerated using sanitized inputs. Original embedded
source metadata remains lineage, not a new reviewed source version.

## Reproduce W0 verification

Run from this repository using Python 3.11 or newer. Installation is local; all
subsequent acceptance commands are offline and do not call a supplier.

```sh
python3 -m venv /tmp/aisa-contract-acceptance-venv
/tmp/aisa-contract-acceptance-venv/bin/python -m pip install -r scripts/api-contract-acceptance/requirements.txt
/tmp/aisa-contract-acceptance-venv/bin/python scripts/api-contract-acceptance/verify.py --report /tmp/aisa-w0-report.json
/tmp/aisa-contract-acceptance-venv/bin/python -m unittest discover -s scripts/api-contract-acceptance -p 'test_*.py' -v
```

The verifier checks package/archive integrity, full inventory partition,
operation ID set, exact lifecycle expansion, request/response debt identities,
fixture assertion/example consistency, positive OpenAPI structure,
declared-reference accounting and gate
mapping. Negative tests demonstrate rejection of omissions, duplicate IDs,
changed bindings at the same debt count, dropped response headers, boolean/number
drift, invalid examples and damaged/unsafe archives. A successful result is
`package_status=passed` with `consumer_status=not_assessed` and
`release_status=not_assessed`.

To replay through the frozen Docs implementation, first obtain a clean worktree
at the full Docs revision listed in `manifest.json`; it may reside anywhere.

```sh
/tmp/aisa-contract-acceptance-venv/bin/python scripts/api-contract-acceptance/replay.py --docs-worktree /path/to/locked-docs --output /tmp/aisa-w0-fresh-replay
```

The output directory must be new. This compares 42 composed documents plus
coverage/pending with the archived sanitized diagnostic outputs and checks that
a second pass changes nothing. The replay uses the same composer and a draft
saved debt input, so it is an implementation reproducibility check, not the
independent semantic oracle or a production readiness decision.

## Run later product acceptance

W1 adapters must emit actual normalized consumer outputs keyed by the handwritten
oracle IDs; W1/W3 must add full-catalog field/reference-closure comparisons and
unchanged default executable-schema checks. The adapter contract is documented
in the fixture README. Compare supplied results with:

```sh
/tmp/aisa-contract-acceptance-venv/bin/python scripts/api-contract-acceptance/verify.py --consumer-output /path/to/actual-adapter-results.json
```

This checks only supplied oracle outputs. It cannot establish their provenance,
all-consumer coverage, all C01-C14 scenarios, CodeReady or ReleaseReady by itself.
Do not copy expected values into adapter outputs. Inspect adapters independently
and run the required cross-repository gates against the same locked inputs.
Missing adapters or inputs are unassessed, never a pass.

## Exit conditions and next implementation

The frozen catalog accounts for 2,162 endpoints: 1,979 projected, 183 excluded,
zero pending in the inventory partition. Eight derived lifecycle paths and four
extra base-path methods produce 1,991 facts operations. Docs has 1,926 composed
coverage rows plus four retained historical output operations, totaling 1,930;
1,918 output operations are enabled. Counts are checked against fixed identity
sets rather than accepted on their own.

The archived content debt is 102 request gaps (12 enabled, 90 disabled) and 62
response gaps. These exact rows are diagnostic draft review inputs, not an
approved publication exemption. All enabled required content must be completed
before declaring the overall requirement complete.

Next is W1 consumer completeness/version consistency and W2 source/debt
governance, followed by W3 code acceptance. Known website full-suite failures and
homepage budget failures require disposition/fixes under their required gates.
Daily revision monitoring, long cache staleness and unset job bounds cannot
justify the 4-hour promise; repair and measure normal/drop-dispatch paths before
W4. W4 requires separately authorized formal inputs/publication/deployment and
real-entry receipts. W5 settles the deferred concrete source definitions.

`result.json` records this package's local verification and implementation replay
only. No production acceptance, approval, publication or deployment is implied.
