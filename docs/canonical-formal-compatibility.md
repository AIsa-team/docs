# Canonical formal assessment compatibility

This increment makes the exporter and historical origin verifier understand two
precise assessment modes. It does not change workflow selection, generate a
production canonical report, change consumer pins or deploy Runtime.

The existing `actual_publication_graph_and_offline_composed_candidate` mode keeps
its existing requirements. The new `actual_publication_graph_and_runtime_canonical`
mode requires `scope: formal_publication_graph_and_runtime_canonical`. Candidate
reports from [the importer](canonical-import-candidate.md) remain rejected: changing
only the evaluation string cannot authorize publication.

## Exact report and replay boundary

`scripts/formal_assessment.py` is the shared structural check for export and
historical origin validation. The canonical mode requires all of these:

- Outer readiness, canonical import, input assessment, publication surfaces and
  payment discovery pass with no blockers. A canonical report cannot contain a
  fabricated `composed_candidate` or `candidate_source_authorization`.
- The input assessment retains its explicitly limited scope. Its five build pins
  are exact, typed fields; Runtime identity has exactly artifact revision, source
  digest, compiler revision and a positive integer generation. The input Runtime
  and acquisition receipt hash agree with the outer report.
- Original current-before/current-after, canonical manifest, source pointer and
  source receipt hashes are present. Current observations need not have identical
  serialization; replay checks their parsed identity and independent build pins.
- Source observations and their original assessment time agree with final source
  governance. Frozen schema input hashes are nonempty and the current input hash
  set is a matching subset. Final source scope and expiry are still computed from
  the new native graph and derived coverage, not copied from input assessment.
- `previous_formal_ref` identifies the authenticated registry predecessor;
  `assessed_base` is this run's Git HEAD and equals the publication graph's
  `published_ref`. Registry lineage binds the former and its fixed registry hash.
- Native hashes exactly match the publication's native file set. The aggregate
  hash matches `openapi/openapi.json`. When the saved Runtime receipt is available,
  its complete canonical member/hash set must match these hashes and the canonical
  manifest hash, with a separate readiness member. No extra canonical files are
  ignored. Existing source metadata, policies and complete publication hash gates
  continue to apply.

These fields are producer declarations, not self-authenticating approvals.
`assess_formal_canonical` reconstructs the pre-import schema view from the exact
assessed Git HEAD and replays the complete candidate gate, including previous
formal GitHub provenance, independent live build binding, acquisition, metadata,
byte-preserving projections and final source authorization. It adds the existing
formal artifact fields for source metadata, source hashes and assessment scope.
It cannot silently reinterpret a current projected registry as schema authority.

`prepare` runs this full reconstruction again for canonical reports and compares
the complete typed result before writing or retaining any pointer. Missing proof,
changed acquisition, source/configuration changes, graph drift or a different
assessed HEAD fail. The exporter still checks the original acquisition receipt,
payment catalog, source expiry and all deferrals. Canonical deferrals are checked
against the independent outer readiness report; there is no second local Composer
result. Legacy mode continues checking both original report scopes.

The historical origin verifier validates the authenticated producer artifact and
its immutable graph. It does not fetch live Runtime state or renew source clocks.
The `compose` job, original publish-step identity, single assessed parent and
original clock remain unchanged. Conservative retention may choose a new receipt
when nested lineage differs; the existing `first_contract_ref` still preserves
the original budget start for an unchanged contract release C.

## Consumer handoff and deployment order

Consumer implementations retain their existing legacy acceptance and add the
strict canonical shape, never just an evaluation allowlist. Their existing
GitHub artifact, exact publication graph, archive safety, policy and expiry gates
remain mandatory. The consumer proves an authenticated producer assessment; it
does not claim to rerun Runtime compilation or to acquire live build pins.

| Consumer | Verifier code | Data/code pin and normal delivery |
| --- | --- | --- |
| Website | `scripts/verify-producer-receipt.mjs` | `client/src/data/docs-contract.lock.json`; normal source PR, auto-merge and Cloudflare build. Verifier code comes from Website main. |
| MCP | `scripts/verify_producer_receipt.py` | `.github/docs-contract-ref`; normal update-docs-pin, CI/image build and release. Verifier code comes from MCP code. |
| Tool Router | `scripts/verify_formal_docs.py` | `catalog/docs.lock.yaml`; normal update-docs-lock and publish-catalog. Verifier code comes from Router code. |
| MPP | Pinned Docs `scripts/publication_origin.py`, invoked by Services `scripts/payment-discovery/prepare.py` | Both `scripts/payment-discovery/docs-verifier.lock.json` and `.github/workflows/sync-payment-discovery.yml` pin verifier code. They currently reference `5b6736dc4c9d27712e763146252ff62f1f6369c3`; changing the formal data ref does not update this code. |

Ship compatible Docs code without selecting the new workflow mode. Update the
three application verifiers and prove old formal consumption still succeeds.
Update MPP's two verifier pins together to the reviewed, merged compatible Docs
commit and test its existing source selection. Only then enable actual canonical
acquisition/import through the normal producer and allow normal consumer source
PRs and release gates to progress. Same-YAML/different-graph receipt selection and
archive safety must retain their current behavior. A stable publication window
is required; no main merges or publisher dispatches are part of this increment.

## Validation

```sh
PYTHONPATH=scripts/tests python -m unittest \
  scripts.tests.test_canonical_formal \
  scripts.tests.test_contract_publication \
  scripts.tests.test_publication_origin \
  scripts.tests.test_deferred_definitions \
  scripts.tests.test_canonical_import \
  scripts.tests.test_canonical_input_assessment
```

Tests reject candidate/unknown mode, omitted subgates, wrong/extra/typed pins,
missing Runtime identity, changed source observations, altered original hashes,
wrong predecessor or assessed base, incomplete or duplicate receipt members,
unapproved deferrals and concurrent Git HEAD changes. Export must replay before
touching last-good metadata. Real temporary Git history demonstrates that a second
canonical metadata publication with unchanged C retains the first contract clock.

The full historical fixture uses the actual authenticated 6fb origin and original
source observations, 74 exact native files and the 2,007-operation aggregate. Its
future canonical Runtime acquisition and compiled-lock fields remain synthetic.
In-memory formal preparation and consumer compatibility tests are not evidence
of a successful production canonical publication or renewed source approval.
