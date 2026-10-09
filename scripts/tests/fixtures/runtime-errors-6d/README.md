# Actual gateway error presenters

`presenters.json` contains controlled calls to the actual API-service presenter
functions at Runtime revision `6d9648811441d08232096808fae7ac96e6816f64`.
The five owning source files were byte-compared to that Git revision before
capture. `files_sha256` pins them; `capture_sha256` pins the capture test.
Messages remain in their wire language in both documentation locales.

These are direct presenter tests with no database, Provider request, or production
access. They establish the documented status/body shapes and the one explicitly
emitted request-ID header. They do not establish route selection, full middleware
correlation, settlement, or production acceptance. The native parameter and
transport cases call the exact `writeIntegrationJSON` payload from their handler
branches; they do not inject a fault into those handlers.

To reproduce in a clean Runtime checkout at the pinned revision, create a Go
`-overlay` JSON mapping a new absolute path
`services/api-service/internal/httpapi/ac19_export_presenters_local_test.go` in
that checkout to this fixture's absolute `capture_test.go` path. Then run:

```sh
AC19_PRESENTER_OUTPUT=/absolute/temporary/capture.json go test \
  -overlay /absolute/temporary/overlay.json \
  ./services/api-service/internal/httpapi \
  -run '^TestAC19ExportActualPresenters$' -count=1
```

Compare the resulting `cases` and `scope` to `presenters.json`. Source/provenance
fields are recorded separately, not generated from documentation examples.
Documentation regression test:

```sh
python3 -m unittest discover -s scripts/tests -p test_error_declarations.py -v
```
