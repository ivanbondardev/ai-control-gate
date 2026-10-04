# Changelog

## 0.2.0 — 2026-10-03

Policy lifecycle, honest accounting and a console, following the
owner's directive to execute the SWE implementation plan (archive reference: `docs/19-swe-implementation-plan.md`).
Real-model work (T06) is deliberately out of this slice and stays an open release condition.

### Configuration is now data with a history

- Added an immutable `ConfigSnapshot`: the six documents are parsed, validated and frozen once, and
  one invocation carries that one snapshot through the parser, grant check, input controls and
  output controls. Nothing on the hot path reads a policy file, so an activation cannot split a call
  across two rule sets.
- Split parsing from file access (`content.validate_documents`, `snapshot.snapshot_from_documents`),
  so the import path and the file path run exactly the same validation.
- `releaseHash` is now the canonical hash of the rules that execute; the raw bundle hash is reported
  separately as `fileHash`. Component hashes use the same canonical form. Hashes recorded by 0.1.0
  are never rewritten.
- Added the lifecycle: drafts, `PUT` at an expected revision, compare, compare-and-swap activation,
  rollback as a new generation, export and import. PostgreSQL holds the active release; the files
  are imported once and are never a second live configuration.
- Activation requires a current **complete and passing** comparison bound to the candidate hash, the
  active hash and generation, the dataset hash and the resolved detector identity. A comparison
  invalidated only by a detector runtime change is refused as stale.
- Added the narrow `budget-only` path: raising existing caps with every other document
  byte-identical is activated deterministically with zero provider calls, so an exhausted evaluation
  budget cannot block its own recovery. It cannot weaken a control, a grant or the model allowlist.
- Refused credentials, endpoints and file paths anywhere in a configuration payload
  (`422 credential_field_rejected`), and excluded the principal table from every export.

### Accounting

- Converted `DETECTOR_PROVIDER_TIMEOUT_MS` to seconds once, bounded it, refused before sending a
  request whose deadline has already passed, and bounded the whole provider exchange in size and
  time instead of only one socket read.
- Reservations now cover input + system instruction + bounded completion, and the output check is
  sized from the target's cap.
- Caps are installed by activation only: `reserve_budget` and `budget_state` no longer rewrite the
  limits of a running generation, and an existing ledger row is never overwritten by a read.
- Admission counts the overdraft, so real consumption above a reservation keeps reducing the next
  available quota instead of being forgiven.
- Added budget provenance: release, generation, pricing identity and principal on every reservation.
- `GET /v1/summary` labels the daily ledger `Current shared budget (UTC day, all callers)` and
  reports `overLimit` instead of a negative remainder.

### Identity and replay

- Idempotency keys are scoped to one principal. Two callers that pick the same client key are two
  different operations; neither can observe or block the other's replay. Migration `0003` recovers
  ownership for existing claims from their invocation rows and leaves unknown legacy claims blocked
  for automatic retry.
- The fingerprint now covers every field that changes execution (service, action, document, text,
  model, detector and budget overrides, timeout, dry-run) and is versioned; the active release hash
  is deliberately excluded, so retrying a completed call after an activation replays instead of
  acting twice.
- A dry run never occupies the key of a real action, and a real call never satisfies a dry run.
- Traces, invocation lists, summaries and exports respect ownership; another principal's trace is
  reported as `404`, so an agent cannot probe which invocation ids exist.

### Reporting

- Every counter, dispatch figure and latency number in `GET /v1/summary` now uses the same validated
  `[since, until)` window, and `dispatch` no longer ignores `until`.
- Naive timestamps, reversed intervals and unparseable bounds are refused with `422` instead of
  silently changing the window. One timestamp format (`…Z`, milliseconds) in both storage backends.
- Added `GET /v1/invocations`: metadata-only pages, newest first, opaque cursor bound to the window
  and filters, with `decision`, `outcome`, `service`, `action` and `dryRun` filters.
- Added nearest-rank latency percentiles (count, p50, p95, max) computed identically in memory and in
  PostgreSQL, with `n: 0` and `null` for an empty window rather than an invented number.
- Counters now separate input block, output withheld, action outcome, dry run and replay.
- `GET /v1/audit/export` returns bounded pages with a next cursor and an explicit truncation flag
  instead of truncating silently; added `GET /v1/audit/events` for the same page as JSON.

### Console

- Added `app/static/{index.html,app.css,app.js}`: Playground, Result, Policies, Dashboard and Trace,
  served from the same origin with no framework, no CDN and no build step.
- Identities are typed in and kept in the tab's memory only — never in the URL, storage or a cookie.
- Dynamic values are written as text nodes; HTML typed into a document, a comment or a policy field is
  displayed, not executed.
- The editor supports validate, save, compare, activate, rollback, history, import and export, and
  refuses to activate a draft whose comparison does not match the revision being activated.
- Assets are served from an allowlist with correct MIME types and `Cache-Control: no-store`.

### Migrations

- Added `0003_policy_lifecycle.sql`: principal-scoped claims with `COALESCE` uniqueness, full release
  snapshots, `config_draft`, `config_active`, `config_activation`, `config_evaluation`, budget
  provenance columns and reporting indexes. Applied files are never edited.

### Verification

- `make test`: 128 unit and route tests (was 92 plus 10 integration tests pulled in by test
  discovery; `make test` now excludes `tests/integration` by design).
- `make test-integration`: 15 tests against a real PostgreSQL, including caps ownership, overdraft
  admission, principal-scoped claims and the lifecycle surviving a restart.
- `make acceptance`: 145 end-to-end checks through Traefik, including the whole policy lifecycle.
- `make ui-check`: 37 checks that drive the console in a real browser over the DevTools Protocol,
  including that typed HTML is not executed. Four real console defects were found and fixed this way:
  a detached status node that swallowed errors, a lost comparison id, a stale generation in rollback,
  and activation gating on the wrong revision.

## 0.1.0 — 2026-10-03

First functional slice, following the owner's directive to implement the 0.0.1 handoff (archive reference: `sources/release-0.1.0-request-2026-10-03.md`).

- Added the protected invocation pipeline: transport identity, pinned configuration release, grant check, deterministic input controls, reserved semantic check, atomic budget reservation with an output time reserve, exactly one controlled dispatch, output controls, and durable sanitized audit.
- Added `POST /v1/invocations`, `GET /v1/invocations/{id}`, `POST /v1/evaluations`, `GET /v1/summary`, `GET /v1/audit/export`, `GET /v1/config/release`, `GET /v1/services`, `GET /health/ready`; kept `/`, `/health/live` and `/version`.
- Replaced the `501` placeholder with the real call. A policy refusal returns `403` and never dispatches; an unverifiable mandatory check returns `503`; budget refusal returns `429`; idempotency conflict returns `409`.
- Added a configuration bundle that pins and hashes six components per invocation, mounted read-only so policy edits take effect live without a rebuild.
- Added two semantic detector modes: a deterministic offline baseline (labelled as a baseline, not a model) and an opt-in OpenAI-compatible adapter that only environment configuration can enable. Provider failures fail closed and are never logged with content.
- Added PostgreSQL persistence: 11 tables, migrations applied at container start, atomic budget reservations, unique idempotency keys, durable audit, durable dispatch effects and synthetic documents.
- Added Redis as a disposable cache only. `FLUSHALL` (verified live) cannot re-permit an executed action, reset a spent budget or delete audit.
- Added `POST /v1/evaluations` for active-versus-candidate content-policy comparison with semantic observation replay; it never calls the target service.
- Added tests: 92 unit and route tests, 10 PostgreSQL integration tests, and a 72-check acceptance script through Traefik. Fixed an audit-sanitizer bypass that the integration suite found in the direct repository write path.
- Made idempotency an atomic claim taken before any paid work (`invocation_claim`): concurrent calls with one key execute the action once, and an attempt without a recorded outcome is reported as `409 idempotency_unknown` instead of being repeated. Invocation row, audit events and claim state are now written in one transaction.
- Recorded charges above their reservation as `overdraftTokens` instead of letting the daily limit go negative, and charged token cost at the profile rate so the cost limit is enforced.
- Restricted `budgetScope` and `detectorProfile` overrides to the operator role, and required an identity for `GET /v1/summary`, `GET /v1/audit/export` and `GET /v1/invocations/{id}`.
- Charged dry runs for the semantic work they trigger; they still never dispatch.
- Keyed semantic observations by the resolved model, endpoint and detector version, so a detector change cannot replay an older verdict.
- Treated the published `APP_HASH_SALT` placeholder as unconfigured and reported it as such.
- Added regression tests for every defect found by the internal adversarial pass (concurrent claims, unreachable provider, redaction before the provider, dry-run charging, privilege separation, authenticated reporting).
- Documented the [invocation contract](app/contracts/invocation.md), the release handoff (archive reference: `docs/18-release-0.1.0-handoff.md`), the structure map and the migration boundary.

A real trained model, policy activation and rollback, an operator UI, TLS, production authentication, and external channels are not implemented in this release. The offline baseline does not demonstrate hybrid AI defence. No published release or Git tag is created by this file.

## 0.0.1 — 2026-10-03

Local scaffold release, following the owner's iteration request (archive reference: `sources/release-0.0.1-request-2026-10-03.md`).

- Added Docker Compose with Traefik, a minimal Python HTTP service, PostgreSQL, and Redis.
- Added `.env.example`, local initialization, version metadata, healthchecks, and Make commands.
- Routed `ai-control-proxy.localhost` through Traefik on port 80, following the owner's port update (archive reference: `sources/release-0.0.1-request-2026-10-03.md#уточнення-власника-порт-80`); kept database ports internal.
- Configured persistent PostgreSQL storage and disposable Redis runtime storage.
- Preserved the existing content inspection library and tests.
- Documented structure, runtime boundaries, and the next-agent handoff.

Policy execution over HTTP, database clients, domain migrations, real AI inference, and the policy builder are not implemented in this release. No published release or Git tag is created by this file.
