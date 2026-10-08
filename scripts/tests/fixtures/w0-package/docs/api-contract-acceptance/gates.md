# Frozen acceptance gate plan

This is a W0 plan derived from the fixed revisions in `checks.json`. It is not a
CI result, approved source-gap baseline, production publication, or timing proof.
Only static files and workflow YAML were read. No project tests, fetches,
workflows, production operations, source locks, or existing workflow files were
changed. The proposed deadlines from completion-spec section 11 stay fixed:
Docs candidate within 60 minutes; every required consumer within 4 hours after
the independently selected publication is available and human release
prerequisites have been satisfied. Neither deadline has been proved.

`checks.json` is the machine-readable gate/case/owner/change-scope mapping.
`budgets.json` records exact cron strings, repository-configured job timeouts,
unset limits, code/config cache windows, assumptions, and required follow-up.
Workflow/job names are local evidence. Actual GitHub check-run contexts, branch
protection/rulesets, app permissions, secrets, environment approvals, external
hosting triggers and effective production cache settings require operator
evidence; they were not inspected live. A workflow job mapping does not assert
that branch protection already requires it.

## Readiness classes

CodeReady requires applicable code checks against independently fixed sanitized
runtime/source/Docs input, full declaration and ref-closure assertions, and
actual consumer paths. Existing tests can be reused, but listing a test or
associating it with C01-C13 does not prove the full case. Every entry is
`not_run_w0`, `planned`, blocked, unavailable, or pending review. Planned checks
need implementation in W1-W3 and future passing evidence. Comparator and manual
review entrypoints are concrete; missing actual adapters or review decisions
remain explicit prerequisites and cannot be treated as success.

ReleaseReady additionally requires formal deployed runtime index/facts, strict
actual generated candidate assessment, independently reviewed request/response
gap and source policies, immutable publication, consumer source-lock release,
build/deploy/activation, and independent reads of every required real entrance.
`not_assessed`, absent inputs, skipped deployment, a preserved last-good file,
successful metadata load, or a diagnostic artifact cannot satisfy it.

A PR containing code and generated publication/source-lock changes needs both
classes. Classification as a code PR cannot bypass formal checks for its real
generated artifacts. Code changes may be reviewed against replayable input
without first deploying unreviewed code or forging a formal evidence cache.
Do not turn candidate exit 3 into success. CodeReady does not authorize
publication or prove deployment.

The final claim that all enabled endpoint documentation is complete also needs
W5: zero enabled required request and response source gaps, with current
maintenance evidence. The historical 12 enabled request, 90 disabled request,
and 62 response gaps remain visible; a reviewed retained-debt baseline permits
only the same scoped debt. It does not prove completeness, source freshness,
or current production inputs. New or changed gaps require a new review.

## Concrete workflow ownership

| Repository and code gate | Existing workflow / job | Owner role and intended evidence |
| --- | --- | --- |
| Runtime three Docs E2E tests and authority rejection | `api-contract-e2e.yml / contracts` | Runtime maintainer: runtime-to-Docs, whole-provider rollout, new-provider discovery and authority drift; extend frozen matrix in W3 |
| Runtime execution/pricing regression | `build-prod-images.yml / go_test`, existing `Test` aggregate and event-specific gates | Runtime service maintainer: preserve mock execution, auth, quote/use, static pricing/bindings and restrictions; existing build gates remain applicable |
| Docs unit and fixed candidate | `test-runtime-contracts.yml / contracts` | Docs compiler/CI maintainers: unit tests plus fixed-input candidate; W3 must split formal public-cache dependency from code checks |
| Cross-repository semantic oracle | Planned extension of `api-contract-e2e.yml / contracts` | Runtime and Docs reviewers: independent expected graph and inventory across real consumer paths; no existing passing full-matrix command |
| Website generated/type/detail/UI/budget | `test.yml / test`; source-lock generation also in `sync-contracts.yml / sync` | Website maintainer: generation, drift, TypeScript, loader/proxy/input/details, actual UI, build and strict homepage budget |
| MCP full validation and root/manifest | `ci.yml / validate`; image steps in `build.yml / build` | MCP maintainer: full validator and pytest, local/router root details, generated manifest, image and smoke; public comparison is currently informational |
| Router generated/static/compiler/bundle/service/shell | `validate.yml / static,test,build,validate`; `build-image.yml / image`; full compile in `update-docs-lock.yml / update-docs-lock` | Router maintainer: immutable full catalog, generated public types, complete opt-in details, compatibility, bundle/service/MCP outer shell, image |
| Source/response/request debt and expiry | `refresh-upstream.yml / refresh`, Docs tests | Source policy owner and independent reviewer: all 67 source files, exact changed debt sets, acquisition failure, manual/pinned receipts and recovery; W2 implementation pending |

| Formal gate | Existing workflow / job | Required release evidence and operator owner |
| --- | --- | --- |
| Runtime deployed facts and identity bootstrap | `deploy-prod.yml / deploy`, gated by `build-prod-images.yml` | Runtime deployment operator; identity SQL/import authorization and actual public facts receipts are separate |
| Docs strict actual publication | `pull-openapi.yml / compose` | Docs publication owner; formal facts, independent gap/source baseline, strict candidate, page links and immutable SHA/hash |
| Other generated publication path | `sync-openapi.yml / sync-openapi` | Docs release reviewer; W3 must require the same strict assessment, beyond YAML/path-count validation |
| Website actual source lock and deploy | `sync-contracts.yml / sync`; external Cloudflare release channel | Website release owner; generated bot push is not deployment, external trigger/credentials/cache invalidation unknown |
| MCP same-SHA validation/image/deploy | `build.yml / docs,test,build,deploy`; `ci.yml / validate`; `deploy.yml / deploy` | MCP release/deployment operators; effective `ACR_PUSH_ENABLED`, `MCP_DEPLOY_ENABLED` and production approval evidence |
| Router actual source-lock release | `update-docs-lock.yml / update-docs-lock` | Router release owner; main-reachable SHA/hash, full compile, exact `validate` and `image` checks, matching-head merge |
| Router catalog publish/activation | `publish-catalog.yml / publish` | Catalog operator; `CATALOG_AUTO_PUBLISH_ENABLED`, catalog-production approval/config, strict Git verification, eligible bundle, remote bytes and active-pointer receipt |
| Router compatible code deploy | `build-image.yml / publish,deploy`; `deploy-prod.yml / deploy` | Router deployment operator; reviewed compatible code and production image installation, independently from catalog activation |
| Independent real convergence | `check-contract-revisions.yml / revisions` | Independent acceptance reviewer; extend existing four-surface metadata check to all required content/version/UI entrances and normal/lost-dispatch receipts |
| Source and initial gap baseline review | Human review with immutable input SHA/hash, exact sets and official evidence | Independent source/gap reviewer; record reviewer, request/decision time, owner and due date; no self-approval or automatic waiver |

All command arguments containing angle brackets are required future inputs, not
values to execute verbatim. Formal write/deploy commands are references to
later authorized W4 work. W0 grants no production operation permission.

## Case boundaries

The complete per-case list of gate IDs is in `checks.json.acceptance_cases`.
All fourteen cases remain planned and unaccepted in W0.

| Cases | CodeReady evidence required | Additional ReleaseReady evidence |
| --- | --- | --- |
| C01-C02 | Full endpoint and method/lifecycle accounting, historical exclusions, real ephemeral backend provider then second endpoint, stable identities; consumer sets independently reconciled | Actual deployed facts and automatic generation/activation without consumer allowlist edits |
| C03-C05 | Effective parameter locations/serialization/auth/servers; full scalar/array/map/boolean/composition/conditional schemas; OAS conversion, recursive/escaped refs and bad-ref rejection across real paths | Same fixed declaration graph and readable UI/outer protocol retrieved from deployed details |
| C06-C08 | All public status/default/range/header/link/no-content and media; examples kept distinct from schema; explicit null and invalid examples; no fabricated JSON/schema/example | Same declarations and supported limitations visible from required published details/downloads |
| C09-C10 | Independent exact request and response debt comparison; binding changes invalidate matching approvals; all sources governable; failure/expiry/pinned signal and true recovery fixtures | Approved source/debt evidence on actual publication, with no false freshness or renewal by rereading a local mirror |
| C11-C12 | ID/hash/revision/missing-metadata/fallback fixtures; actual EN/ZH/navigation/llms/cards/downloads/manifests/aliases and opt-in detail references | Normal and one lost dispatch recovery measured; every required entrance uses selected SHA/hash and build revision |
| C13 | Mock auth/routing/quote/use/charging and pricing/bindings unchanged; 251 historical Router execution restrictions remain independently reported | No production behavior claim from document metadata; retain scoped release regression evidence |
| C14 | Code fixtures can test strictness, but cannot pass C14 live acceptance | Independently selected real publication, strict source validation, eligible non-diagnostic artifacts, actual deployment/activation and independent content/version readback |

No oracle may invoke the tested projection/composer to generate its own expected
semantic graph. Shared JSON/YAML parsing is allowed. Full-set comparisons and
refs/field-path expectations are separate from representative real UI/protocol
fixtures. Success counts, top-level properties, a primary response, or a helper
unit test are insufficient substitutes for full declared public semantics.

## Known blockers and timing review

Docs currently combines unit tests with `Check actual candidate readiness` in
one 10-minute `contracts` job. It restores a public runtime cache and reports
missing formal index/facts as `not_assessed` with exit 3. W3 must provide honest
fixed replay input for code work and keep strict real-publication assessment.
No current cache, reviewed baseline, or formal readiness is manufactured here.
Offline CodeReady needs independently fixed/reviewed sanitized input and scoped
debt, not an already deployed production index or approved production publication
baseline. The existing CI coupling is the current blocker to separate in W1/W3.

Website has 24 spec-reported historical full-suite failures and a recorded
homepage script total of 1,102,487 bytes against a strict less-than 850,000-byte
budget. These were not rerun in W0. File/cause grouping and impact review remain
W3 work; no unrelated-failure exception has been granted. Project checks and
homepage raw/gzip/combined budgets must pass. Full-suite failure must still be
reported even if an independent scoped historical exception is later approved.

`budgets.json` retains every inspected job's configured limit and marks unset
timeouts separately. The 360-minute GitHub default used in conservative sums
is an explicit platform assumption, not verified repository configuration.
Reusable wrapper jobs use called jobs' limits and are not double-counted.
Timeouts bound cancellation/failure, not successful completion; cron expresses
nominal phase, not guaranteed dispatch or runner availability.

| Path | Static conservative sum | Gap against frozen target |
| --- | --- | --- |
| Reviewed effective input to Docs candidate | 300s default runtime server cache + 60s HTTP freshness + 600s SWR + 30m phase + 10m compose = 56m | Only 4m nominal margin; live cache override, CDN, runner/backlog and generation recovery unknown; 60m unproved |
| Website, lost dispatch | 30m phase + assumed 360m unset sync + 30m test/build + 60m discovery shared cache + 24h SWR + 5m browser = 32h5m | Discovery shared freshness plus SWR alone is 25h; W1/W3 fixed version, cache/deploy/timeout changes required for 4h |
| MCP, lost dispatch | 60m phase + assumed 360m unset docs resolver + 15m CI + 30m image + 15m deploy + 10m homepage proxy/HTTP branch = 8h10m; manifest/llms/card branch alone 8h5m | Explicit resolver limit, configured push/deploy channel and actual replica/readback evidence required; homepage facts also depend on Website propagation |
| Router, lost dispatch with compatible code already installed | 60m phase + 60m lock update + 30m publish + 30s sync + 30s process poll + 60s manifest = 2h32m | Nominally under 4h; source-lock check wait is already within 60m; transfer/verify, scheduler/queue, operator settings still unbounded |
| Router at maximum allowed poll/sync configuration | Above path with both 10m intervals = 2h51m | Production effective intervals unknown; interval is not a transfer completion limit |
| Normal dispatch | Dispatch job timeout unset; same subsequent consumer work | Default assumption alone can exceed 4h; separate normal-path proof required |
| Revision monitor | Daily 03:35 UTC; two-consecutive escalation; job timeout unset | At least hourly target unmet; nearly 48h phase for escalation before execution/queue, not prompt deadline failure |
| Source refresh | Monthly on day 1, 04:20 UTC; job timeout unset | Daily acquisition proposal and evidenced 30-day manual/pinned review are W2 work; upstream-change discovery remains a separate limitation |

Budget sums add serial cache windows conservatively. Independent route branches
are not all stacked into one path: Website's 30-minute client detail cache is
recorded separately from discovery's long SWR. Immutable SHA caches may safely
retain old immutable bytes; they do not cause an old loaded page/process to
adopt a new release. A new entry/reload and an existing old session require
separate observation boundaries. Last-good fallback may persist under failure
and cannot be treated as fresh convergence. MCP server cards and connect module
discovery have 5-minute HTTP caches; the MCP homepage can also hold Website HTML
for 5 minutes and retain it after failed fetches. Website hashed static JS/CSS
has one-year immutable caching and static incremental-cache interception; this
is a distinct existing-session and build-invalidation observation, not a
one-year delay added to a new-version route. These paths are recorded explicitly
in the budget cache inventory.

W3 must freeze actual bounded job/monitor/cache/deploy configuration before W4.
Missing external CDN, Docs hosting, Cloudflare, S3, reverse-proxy, GitHub runner,
environment approval and app configuration is a gap, not a zero-duration stage.
Compatible code deployment, Docs hosting and catalog/source-lock activation are
distinct release events. Human source/lock review is reported as
`pending_review` with owner/request/due/decision timestamps and a one-business-
day reminder; human waiting never becomes an automatic recovery bound and the
real total elapsed time stays visible.

W4 must collect one normal update and one dropped-dispatch scheduled recovery,
timestamp each stage, read the slowest required real consumer including content,
and fail on the frozen deadline. No deadline expansion after a failure and no
automatic waiver is permitted. An hourly monitor must report the first explicit
budget overrun; ordinary repeated-mismatch escalation cannot hide that failure.

The W0 comparator entrypoint is
`python scripts/api-contract-acceptance/verify.py --consumer-output <actual-adapter-results.json>`.
It compares actual adapter results to independently identified oracle IDs;
adapters remain planned W1 work, and invoking a comparator without actual
consumer output does not prove consumer correctness or oracle independence.
The independent source/gap review entrypoint is the documented manual procedure
in `checks.json`: an independent reviewer records an attributable decision for
the frozen SHA/hash, exact gap sets, binding/policy and official-source evidence.
No automatic approval command is provided.
