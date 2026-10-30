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
Runtime acquisition, generation and the review PR. It uses this repository's
`GITHUB_TOKEN`; AIsaServices does not generate or write documentation. Review
and merge into dev are required before Mintlify publishes the result.

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

## API environment is a separate configuration

The dev sync fixes its origin in `scripts/sync_dev_runtime.py` and rewrites
generated API and console addresses to dev. Its aggregate OpenAPI and endpoint
navigation include only successfully composed dev contracts. Historic endpoint
files remain for stable links, with an unavailable notice and noindex when they
are outside that set. The registry retains reviewed source configuration; only
dev-indexed catalogs are selected in the private composition candidate.
Source facts remain unchanged during composition, and
production publication receipts are retained as history. The generated OpenAPI
is a dev presentation, not the production canonical artifact. Do not enable the
production Runtime publisher on dev or relabel a production receipt as dev
evidence. Website and handbook links still need the separate dev site's domain
when hosting is configured.

## Dev Runtime acquisition

Dev exposes live facts at `/info/openapi.json` and
`/info/openapi/{provider}.json`; it does not have an enabled durable immutable
release publisher. The gateway's dedicated `dev-runtime-contracts` route allows
only GET, HEAD and OPTIONS on those public paths, forwarded to api-service in
namespace `dev`.

The reader requires the complete index, rejects pending projections, matches
provider facts hashes to index entries, reads each provider twice, and checks
the index and category again. Changed, missing or stale responses reject the
entire candidate. Bounded HTTPS requests use no credentials, redirects or
production fallback. The existing offline Composer and page generator read
configured source mirrors locally; they never call provider business APIs.
Undefined or invalid contracts stay pending in the report and are excluded
from the dev aggregate and endpoint navigation. A partial generation explicitly
records `status: partial` and `blocked_providers`; it does not assert that every
Runtime contract passed composition.

Run locally from `dev` (omit `--write` for a dry run):

```sh
python scripts/sync_dev_runtime.py --write --report /tmp/dev-runtime-report.json
python scripts/check_nav_integrity.py
python scripts/validate_runtime_api_reference_slugs.py --generated-only
```

### Automatic generation from the dev Runtime

Docs owns the same pull-and-generate responsibility as production. Development
uses the live facts reader above because its formal immutable publisher is not
enabled:

```text
AIsaServices/dev -> deploy dev Runtime
  -> Docs timer dispatches generate-dev-docs.yml at ref dev
  -> Docs/dev pulls current dev contracts -> generate and validate
  -> open/update automation/dev-runtime-docs PR with base dev
  -> reviewer merges -> Mintlify publishes aisa-docs-dev.mintlify.site
```

GitHub schedules execute only from the default branch. The main version of
`generate-dev-docs.yml` therefore contains only a ten-minute timer and a dispatch
to the same workflow file at `ref: dev`. It does not check out code, read Runtime
contracts, generate files or write a branch. The dev version contains the actual
generator and accepts manual runs and pushes changing generator scripts,
reviewed schema mirrors or the registry. Merge the generator PR into dev before
merging the timer PR into main. Both changes require review through PRs.

The generator always checks out dev. It compares a fresh, verified snapshot's
content fingerprint against `docs/dev-runtime.json`, rather than waiting for a
particular Services Git SHA or HTTP revision header. New deployments with changed
public contracts are picked up on a later timer run. Missing, stale or changing
responses fail acquisition and preserve published files. This remains a dev
preview, separate from formal production publication and consumer notification.

The generation job requests Contents and Pull requests write permissions for
the Docs repository's `GITHUB_TOKEN`. In repository Actions settings, allow
GitHub Actions to create pull requests. No Services-side App credentials are
required. The token writes only the generated PR branch; the PR targets dev
and is never automatically merged. GitHub may require a reviewer to select
**Approve workflows to run** on a bot-created PR before its normal checks run.

A fresh stable snapshot is acquired even when generation is skipped. Category
cache timestamps are excluded from both fingerprints and snapshot hashes, so
unchanged data cannot add timestamp-only commits to the pending PR. Pushes that
change generator inputs force generation; manual runs can select `force`.
New or changed contracts use the existing Composer; blocked providers remain
explicit in `docs/dev-runtime.json` and the Actions generation report. No
business API or upstream provider calls are made. To retry, run **Generate dev
Runtime docs**, selecting dev, or use the main timer's manual dispatch.

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
