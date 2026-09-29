# Runtime contract mirror, first rollout

`openapi/registry.yaml` owns the generated-provider list. Initially it contains
only Similarweb and automatic provider discovery remains off. Existing provider
files outside the registry remain handwritten. No production requests are made
by unit tests.

```sh
python3 -m pip install 'PyYAML>=6,<7'
python3 -m unittest discover -s scripts/tests -v
python3 scripts/pull_openapi.py --facts-dir /path/to/facts       # dry run
python3 scripts/pull_openapi.py --facts-dir /path/to/facts --write
python3 scripts/pull_openapi.py                               # public API dry run
```

Facts files are `<provider>.json`, using OpenAPI 3.1 from
`/info/openapi/<provider>.json`. The generator emits a root server and full
public paths. `info.x-aisa-document.facts_hash` is required. `x-aisa-any` is a
path-item extension, never an invalid HTTP method.

Composition preserves runtime IDs, status, pricing, protocol and capabilities.
It reads upstream parameters/body only when the runtime says `provider` or
`mixed`; gateway declarations win for fields it validates. Missing mirrors,
external or cyclic references, ambiguous ANY identities, or unsafe mixed unions
enter `pending.json`. ANY with exactly one mirrored method preserves the stored
operation ID; multiple methods remain pending until method-specific identities
can be migrated without renaming existing tools.

A previously published route disappearing or changing its ID aborts the entire
pull before files are written. Disabled operations stay in the output. A pinned
registry entry (`pin: <commit SHA>`) restores its committed document explicitly.
The content hash combines runtime facts, mirror, overlay and composer version;
`generated_at` alone never causes a commit. ETags cache public facts under ignored
`.cache/runtime-contracts`, and overlays are recomposed even after a 304.

Page creation reuses existing route references and never overwrites handwritten
prose. New English and Chinese pages and navigation entries are additive. The
existing translation catalog localizes available strings; untranslated strings
remain English and can be translated through the existing localization workflow.
No model translation credentials or paid calls are required by this puller.

The workflow runs every 30 minutes, on dispatch and on source-input changes. It
stages and validates by default. Publishing requires the repository variable
`RUNTIME_CONTRACT_PUBLISH=true`, or an explicit manual `publish=true` dispatch.
Keep publishing disabled until the runtime endpoint is deployed and the initial
identity/page diff has been reviewed. Unavailable runtime facts preserve all
published files. Commits are serialized and rebased before push.

Not activated in this first batch: provider auto-registration/groups, upstream
imports/monthly refresh, cross-repository dispatch, and global hand-edit lint.
These need the corresponding downstream/rollout prerequisites. Existing
`sync-openapi.yml` handles website distribution for user-authored source pushes;
a GitHub-token bot push does not trigger that workflow, so cross-repository
publication must be configured before enabling unattended mirror publication.

The first cutover preserves published operation IDs, page URLs and handwritten
MDX prose. Existing relative OpenAPI references are updated to the runtime's full
public paths. Similarweb editorial overlays retain moving upstream date-window
rules and response descriptions; numerical parameter constraints, dated examples
and billing calculations remain runtime-owned. Runtime response descriptors are
kept as-is: legacy hand-authored response schemas are not copied into the new
contract, and need review before enabling publication.

The pull workflow validates generated page references only. The repository's
existing full slug audit remains available unchanged; historical provider page
names do not all satisfy it. Disabled status updates use a managed notice block
without replacing page prose. A pinned rollback is still subject to page
reference validation: it cannot publish a version missing routes used by retained
pages without an explicit documentation migration.
