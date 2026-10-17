# Immutable W0 diagnostics and stricter forwarding expectations

`prepare_full_catalog.py` executes the current Composer on the original,
SHA256-pinned sanitized W0 archive. The archive and its original `expected/`
members remain unchanged. This diagnostic run never authorizes publication,
current-source debt, runtime capabilities, or production changes.

The current forwarding guards correctly reject old W0 facts that declare no
forwarding capability for query/header fields present in their frozen sources.
Independent inspection of the original facts and sources confirms 59 concrete
method failures across 55 runtime identities: Apollo 2, Brave 15, Financial 8,
Parallel 7, Polymarket Bridge 2, Relayer 3, Scrape Creators 15, Search 1 and
Twitter 6. Four Brave methods collapse to their original Runtime ANY rows.
Identity preservation then retains each of these nine providers' old documents,
conservatively marking another 119 otherwise composable coverage rows pending.

The separate reviewed `strict-forwarding-expectation-migration.json` records this
one exact diagnostic expectation change. Its own SHA is fixed in code. It binds
the original archive/coverage, all 123 JSON facts/source inputs, the proposed
offline policy fixture, all nine providers' exact pending/root-failure reasons,
and every full row in the 178 removals and 174 additions. It additionally pins
the complete resulting 2024-row coverage graph and entire pending graph,
including every reason, source binding and previously pending operation.
The compressed diagnostic evidence is independently hash bound and supplies
fixed positive test input; the running Composer never generates its own oracle.

Reconciliation requires exactly this closed migration even if code regresses to
the original optimistic composed statuses. Unknown additions, omissions, changed
reasons, binding drift, extra retained providers or pending-to-composed changes
fail. The complete 1930-operation identity comparison, execution/pricing metadata,
global errors, missing inputs, source-policy checks and zero-change repeat run
remain mandatory. The receipt honestly reports that the historical coverage
tuple sets differ and separately identifies the reviewed diagnostic migration.
