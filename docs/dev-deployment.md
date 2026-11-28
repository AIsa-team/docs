# Independent dev documentation

## Branch and hosting ownership

| Environment | Source branch | Hosting |
| --- | --- | --- |
| Production | `main` | Existing Mintlify project at `https://aisa.one/docs` |
| Development | `dev` | A separate Mintlify project connected only to `dev` |

A push to `dev` can update the dev documentation without merging to `main`.
Mintlify's GitHub App publishes the branch selected in each project's Git
settings. There is no GitHub Actions site upload, Docker image, or server
deployment command in this repository. The existing production project must
continue to track `main`.

## Connect the dev site

1. In Mintlify, create a separate project for dev. Select the existing
   `AIsa-team/docs` repository, deployment branch `dev`, and repository root as
   the content directory (`docs.json` is at the root).
2. Verify the new project's default `*.mintlify.app` URL before adding a custom
   domain. Add the dev domain to this new project only and configure the exact
   DNS records shown by Mintlify. A dedicated subdomain can serve docs at `/`;
   it does not need the production website's `/docs` proxy.
3. Push a documentation change to `dev`. Check the `Docs checks` and `Dev docs`
   workflows, then the new project's deployment history and deployed content.
   Mintlify deployment status is independent of these Actions checks; required
   PR checks should be configured on `dev` if changes need review before publish.
4. Verify the production project still tracks `main` and has not published the
   dev commit. Keep the dev branch: it is the persistent source for the dev site.

Preview deployments are an alternative for temporary reviews, but they do not
support custom domains. Use a separate project for a stable dev domain. Project
availability and billing depend on the Mintlify account's plan.

## Repository automation boundaries

`docs-checks.yml` validates navigation, generated endpoint slugs and links on
both `main` and `dev`. `dev-docs.yml` runs the existing composition and
publication regression tests and frozen acceptance fixtures offline on dev
pushes and PRs targeting dev. That test job has read-only repository permissions,
no App credentials, no production Runtime acquisition, no shared source-review
cache, and no downstream notifications. `generate-dev-docs.yml` on dev owns
Runtime acquisition, generation and direct publication to dev after validation.
It uses this repository's `GITHUB_TOKEN`; AIsaServices does not generate or
write documentation. Mintlify publishes the generated dev commit.

These production workflows require `refs/heads/main`, including manual runs:

- `pull-openapi.yml`: acquire and formally publish production Runtime contracts.
- `sync-openapi.yml`: legacy OpenAPI publication and production notifications.
- `refresh-upstream.yml`: production upstream maintenance and review PRs.
- `check-contract-revisions.yml`: production consumer convergence checks.
- `dispatch-contract-consumers.yml`: notify Tool Router, website and MCP.
- `read-merged-input-qualification.yml`: existing main-only diagnostic reader.

Production artifact assessment in `test-runtime-contracts.yml` runs on `main`
and PRs targeting `main`. A manual run from dev cannot acquire live production
evidence. The offline code test job remains usable from other branches.

Consumer dispatch also verifies that its full input commit SHA is reachable
from remote `main` before minting downstream credentials. A dev-only commit
cannot be advertised as a production publication. The production publisher's
concurrency group includes the branch, so an accidental dev invocation cannot
hold or cancel the production publication lock.

Pushing `dev` does not automatically publish a new formal contract, regenerate
production receipts, push to `main`, or notify production consumers. Scheduled
workflows continue to run from the repository's default branch (`main`). Do not
change the default branch to dev.

## Published dev Raw API contracts

The dev workflow runs `sync_dev_runtime.py --source dev-release`. The existing
release reader verifies the dev current pointer before and after fetching the
immutable manifest members, their SHA-256 and ETags, and the complete canonical
graph. Category content is checked for stability by the reader. Raw API pages
use `contracts/native/*.json`; the aggregate comes from `contracts/openapi.json`.
An unavailable, stale or facts-only dev release fails generation.

English and Chinese reference pages bind the published method and path. The
site projects first-party OpenAPI servers onto the dev API and primary reference
links onto the dev Docs site. Historical pages without an available operation
keep their prose and lose their interactive binding. Source release pins and
input hashes are recorded in `docs/dev-runtime.json` alongside the hashes of
the generated contracts. For unchanged inputs the CLI still performs a fresh
verified acquisition before skipping generation.

On a local dev checkout, omit `--write` to dry-run the same path:

```sh
python scripts/sync_dev_runtime.py --source dev-release --report /tmp/dev-runtime-report.json
```

## Task pages on dev

Task pages preview the dev API using their own release acquisition. `scripts/sync_tasks.py` reads the dev worker's immutable
`tasks/catalog.json` through `https://dev-api.aisa.one/public/api-contract/current`.
It verifies the release manifest, file hashes and freshness, then writes:

- `tasks/overview.mdx` and one page per task, mirrored under `zh/tasks/`;
- `tasks/openapi.json` and `zh/tasks/openapi.json`, one `POST` per task, with
  the dev API as server;
- a `Tasks` / `任务` group in the API Reference tab, after `Overview`.

The Task generator owns the pages outside `api-reference/` and `openapi/`. `generate-dev-docs.yml` runs the script
after the Runtime step on every run, and each run rewrites all Task files, so
a disabled or removed task disappears after the next successful worker publication
and documentation generation. Missing, stale or invalid artifacts preserve the
saved pages and fail the run. Request, response and error schemas come from
AIsaServices `packages/tasklayer/taskdoc`; effective V2 prices and enable state
are included in the same worker release. There is no fallback to live Task
detail requests. `docs/task-runtime.json` records the source release. The
overview copy is in the script. Local run:
`python scripts/sync_tasks.py --api https://dev-api.aisa.one`.

## Automatic preview generation

The default-branch timer only dispatches `generate-dev-docs.yml` at `ref: dev`.
The dev workflow owns acquisition and generation, checks navigation and slugs,
and commits only its generated-file allowlist. Mintlify publishes the generated
dev commit at `https://aisa-docs-dev.mintlify.dev/docs`.

A fresh verified release is required even when `--if-changed` skips generation.
Switching the source, release or input fingerprint prevents a skip. Generator
changes force regeneration. No timestamps are added to committed output; the
run artifact carries the observation time.

If acquisition or validation fails, the current site remains intact. If dev
moves during generation, publication fails and a later run regenerates from the
new tip; it never force pushes or rebases a validated candidate. The workflow
cannot commit or publish to main.

## Work on dev

```sh
git fetch origin
git switch -c docs/my-change origin/dev
# Edit MDX or other documentation sources.
git add <changed-files>
git commit -m "docs: describe a development change"
git push -u origin docs/my-change
# Open a pull request with base dev; publish only after review and merge.
```

For local preview, use Node.js 22 and `npx mint@4.2.1006 dev`. The preview defaults
to `http://localhost:3000`. For validation matching Actions:

```sh
python -m pip install 'PyYAML>=6,<7' 'jsonschema>=4.23,<5' 'openapi-spec-validator>=0.7,<0.8'
npm install --prefix /tmp/runtime-yaml-reader --no-audit --no-fund --ignore-scripts js-yaml@4.1.1
export RUNTIME_YAML_READER_MODULE=/tmp/runtime-yaml-reader/node_modules/js-yaml
python scripts/check_nav_integrity.py
python scripts/validate_runtime_api_reference_slugs.py --generated-only
python -m unittest discover -s scripts/tests -v
python scripts/tests/fixtures/w0-package/scripts/api-contract-acceptance/verify.py
python -m unittest discover -s scripts/tests/w3_verification -v
npx --yes mint@4.2.1006 broken-links --files '**/*.mdx' --check-redirects
```

References: [Mintlify Git source settings](https://www.mintlify.com/docs/deploy/github),
[custom domains](https://www.mintlify.com/docs/customize/custom-domain), and
[preview deployments](https://www.mintlify.com/docs/deploy/preview-deployments).

### Public Task schema validation

The dev workflow uses the same `sync_tasks.py` generator as the proposed
production publisher, with `--api https://dev-api.aisa.one`. It consumes the
complete public request, response, and error schemas, preserving conditions,
references and nullability in OpenAPI 3.1. Social compatibility reads the
published input fields when a full request schema is absent. No Task is executed.

New Task IDs and domains generate bilingual pages automatically. An authoritative
empty catalog removes pages; a failed acquisition or invalid schema fails the run
before replacing the previous Task pages. Repeated generation is deterministic.
Task page slugs preserve underscores to avoid collisions between valid Task IDs.
The dev workflow and Mintlify project remain isolated from main.

Validate offline with `python -m unittest discover -s scripts/tests -p test_sync_tasks.py`.

Dev CI and generation pin PyYAML 6.0.3: 6.0.4 changes nested YAML merge
precedence and fails the existing official-source anchor/override tests. Keep
those tests as the upgrade gate; do not accept changed source field values.
