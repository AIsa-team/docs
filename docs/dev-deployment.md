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

## Production contract preview on dev

The documentation deployment and API contract source are separate. The dev
workflow currently runs `sync_dev_runtime.py --source production`: it reads
public production metadata and publishes the generated preview only to `dev`.
The normal timer uses the same source, so a later refresh cannot replace the
preview with the smaller dev catalog.

This is an explicit preview configuration. It does not enable production
publication on dev, change the default branch, approve source evidence, or
notify consumers. All source acquisition is read-only; no business API or
upstream provider calls are made.

Dev navigation checks use `regroup_api_reference.py --check --preserve-navigation`
to match the generator's retained directory hierarchy. The check still requires
unique English and Chinese page sets to mirror each other, and verifies the
platform index and Data APIs cards against that navigation. Page, slug and link
checks also run. Production retains the default regrouping and translation checks.


The production source uses the existing `fetch_runtime_release` reader:

1. Discover the fresh published release at `https://api.aisa.one/public/api-contract/current`.
2. Download its immutable manifest members and verify hashes, ETags, complete
   provider coverage, canonical graph consistency, byte bounds and freshness.
3. Require the current release and category content to remain stable across
   acquisition. A missing, changed or invalid release aborts the run; there is
   no fallback to old files or a mixture of live provider responses.
4. Recompose the verified raw provider facts with the dev generator and reviewed
   source configuration. The preview uses new presentation code; it does not
   claim to be a production canonical publication.

`docs/dev-runtime.json` records the production origin, release revision,
compiler, generation and input hashes, alongside `environment: dev` and
`formal_publication: false`. The fixed reader from main is reused with its
bounded parallel acquisition and complete-release size limits.

API URLs remain production URLs because those are the contracts being
previewed. They must not be rewritten to dev endpoints which may not exist.
Schema/download links point to the dev branch's generated files. This preview
requires a production API key for an actual request; generation and validation
never make such requests.

The private generation candidate normalizes existing native document URLs to
the selected source before composing and hashing retained operations. Repeating
generation with the same inputs after a source switch therefore preserves both
page content and document hashes. The source checkout and acquired facts remain
unchanged until the validated output is explicitly written.

Existing reference links are retained. Explicitly disabled operations are
identified as historical; unsupported old pricing labels such as `cost_tier`
and `model` do not turn an unpriced disabled endpoint into an unknown active
billing rule. Other unverified references remain marked as unverified; changing
the input source does not waive identity, schema or source-review checks.

For a local dry run on the dev branch:

```sh
python scripts/sync_dev_runtime.py --source production --report /tmp/dev-runtime-report.json
```

Add `--write` to apply validated outputs. The command rejects every branch
except dev before acquisition or writes. `--source dev` remains available for
explicit dev API checks; its complete live-facts reader retains double reads,
provider hashes, a stable catalog and no redirects.

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
