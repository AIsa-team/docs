# Frozen timing remediation proposal

This is the concrete configuration proposal required by W0 before implementation.
The external targets remain 60 minutes for a candidate and 4 hours for required
consumer convergence. These are design/acceptance caps, not claims about current
GitHub, hosting or production delivery guarantees. Every overrun is a failure;
unknown effective operator/CDN settings remain unresolved prerequisites.

| Path | Required bounded stages after its defined start | Proposed maximum | Owner / implementation |
| --- | --- | --- | --- |
| Docs candidate | Runtime freshness 5m + scheduled phase 10m + runner queue 5m + compose/validate job 20m | 40m, leaving 20m margin | Runtime/Docs; W2/W3. Pin/evidence the effective public cache; offline CodeReady uses its frozen archive. Candidate discovery must run at least every 10m and disable additional HTTP/CDN stale windows for version discovery. |
| Website recovery | Scheduled phase 30m + dispatch 2m + queue 15m + sync 15m + test/build 30m + publish/deploy 30m + latest-pointer/cache 5m + readback 10m | 137m, leaving 103m margin | Website/release; W1/W3. Set limits on every prerequisite job, bound actual deploy/hosting and remove 24h SWR from version discovery. |
| MCP recovery | Scheduled phase 60m + dispatch 2m + queue 15m + Docs resolve 5m + CI 15m + image build 30m + deploy 15m + homepage proxy/HTTP cache 10m + readback 10m | 162m, leaving 78m margin | MCP/release; W1/W3. Limit currently unset Docs resolution, verify configured push/deploy channel, and make homepage discovery facts use the same fixed contract rather than waiting indefinitely on Website. |
| Router recovery | Scheduled phase 60m + dispatch 2m + queue 15m + lock/update 20m + catalog publish 30m + transfer/verify 10m + sync 1m + process poll 1m + manifest cache 1m + readback 5m | 145m, leaving 95m margin | Router/release; W3. Compatible code must already be installed; bound effective poll/transfer/activation settings and verify remote bytes before pointer activation. |
| Convergence monitor | Scheduled phase at most 60m; explicit timeout failure reported on first observation | At least hourly, no two-cycle delay for a deadline breach | Docs/release; W3. Record budget start, expected SHA, each stage and first overdue observation. |
| Source governance | Automatic acquisition at least daily; manual/pinned evidence due every 30 days | Separate source freshness budget | Source owners; W2. No fabricated unchanged-fetch timestamp or receipt. |

The sums include nominal maximum phase and configured stage acceptance limits.
Queue/deploy/CDN caps need operator evidence and W4 measurements; job timeouts
alone do not establish successful completion or guaranteed scheduling. A missing
or violated cap blocks timing acceptance. Normal dispatch uses the same caps,
without relying on recovery phase as extra allowance. One dropped dispatch must
still fit the same 4-hour external deadline through the scheduled path.
Queue allowances in the table are aggregate across all serial jobs on that
path, not a fresh 15-minute allowance for each job. If separate prerequisites
cannot fit the aggregate, repair that path before accepting the timing plan.

Latest-version discovery must have a maximum 5-minute cache lifetime and no stale
success after a failed version check. Immutable SHA content can remain cached:
its URL identifies that exact version and must not be presented as the latest
accepted release. The actual Next OpenAPI download, llms/card/manifest facts and
detail APIs must use the same expected version. Existing browser sessions need a
bounded version check/invalidation path (at most 5m) or an explicit outdated
state; readbacks must distinguish current release, previously loaded session and
unavailable content. A last-good stale response is not fresh convergence.
MCP's 10-minute homepage proxy/HTTP content window is not authoritative version
discovery. It needs a separate version signal bounded to 5 minutes and content
invalidation or an outdated state on mismatch. Do not use the longer content
cache as permission to report an old version as current.

For each limit, W3 must record the concrete workflow/job/cache/operator setting,
the responsible role and implementation revision. The static proposal can guide
W1/W2 changes; it cannot clear W3 or W4. Human source/source-lock approvals remain
`pending_review`, with actual request/decision latency shown separately; do not
hide those waits behind this automated budget. Re-evaluate an actual serial
dependency or hosting cap before implementation if it exceeds a proposed stage;
the 60m/4h external deadline cannot be expanded after a failed acceptance run.
