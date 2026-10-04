# Action Gate

The real OpenAI model proxy is available at `POST http://localhost/v1/responses`. See the [supported profile and setup](contracts/model-proxy.md) and [verification evidence](../sources/model-proxy-implementation-2026-10-04.md). It supports text, client function loops and buffered SSE, with server-side credentials, policy checks and durable budget/audit records.

The existing **0.2.0 gateway** at `/v1/invocations` has a protected invocation path and a full
policy lifecycle. Calls on that path pass content controls, a semantic check, a budget reservation,
at most one controlled dispatch and an output check, and leave a sanitized audit record. Gateway
policy is edited as a draft, compared, activated and rolled back; `policy/` files are its bootstrap
format. The restored original control panel adds the separate `/v1/panel/*` policy/runtime surface
described below. PostgreSQL makes both surfaces durable; isolated memory mode is ephemeral.

Scope history: 0.0.1 scaffold (archive reference: `../docs/17-release-0.0.1-handoff.md`),
0.1.0 handoff (archive reference: `../docs/18-release-0.1.0-handoff.md`),
0.2.0 handoff (archive reference: `../docs/20-release-0.2.0-handoff.md`).

## Start locally

Requires Docker with the Compose plugin and Make. Run from the repository root:

```sh
make init
make up
make acceptance
```

Open [http://ai-control-proxy.localhost](http://ai-control-proxy.localhost). The default HTTP port is
80 (`TRAEFIK_HTTP_PORT`). If the local resolver does not resolve this hostname, use
`curl --resolve ai-control-proxy.localhost:80:127.0.0.1 http://ai-control-proxy.localhost/version`.

### Original control panel connected to the backend

**Implementation facts:** [AI Control Panel](http://ai-control-proxy.localhost/control/) restores
the original screens, layout and editors from the separately developed `ai-control-layer`
prototype (commit `fbf4c03`). The original checkout remains unchanged. The panel now uses the
same-origin `/v1/panel/*` API implemented in [panel_service.py](action_gate/panel_service.py) and
[panel_engine.py](action_gate/panel_engine.py), with state in the configured backend storage.
The [developer workbench](http://ai-control-proxy.localhost/) remains available.

Connect with the configured local operator identity; shipped synthetic defaults are
`operator-local` / `local-operator-token`. Tokens remain in tab memory and are forgotten on
reload or disconnect. Agent credentials can call `/v1/panel/invoke`, with the subject derived
from transport identity, but cannot access the operator panel. Operators can explicitly run a
synthetic request on behalf of a selected test agent.

The restored workflows include:

* Add, edit, reorder and disable checks in the visual pipeline; edit the same draft in YAML;
  import/export YAML files and retain draft edits across reloads.
* Edit agent → service → action rules with parameter conditions, exceptions and default behavior.
* Create and edit test cases; evaluate both content checks and service rules on the server; inspect
  live/candidate impact and explicitly acknowledge any mismatch before activation.
* Inspect real activation history and YAML differences; roll back through a new comparison and
  activation; detect another session's active-policy change and resolve a draft conflict.
* Import typed service schemas and verify the local synthetic adapter schema.
* Run a synthetic request explicitly; inspect its input decision, actual local dispatch and output
  disclosure; mark false positives, add exceptions, save tests and replay sanitized content.
* Review baseline classification examples and export reviewed examples as JSONL. Test-only
  unknown-label/timeout faults exercise configured fallback reactions without altering live calls.

No random traffic, fabricated history, browser-side policy verdict or external asset download is
needed. Requests are polled from the server; summary counts cover loaded audit records. The
vendored YAML library and original CSS are served with the application image.

**Execution boundary:** the restored panel has its own policy and local synthetic runtime.
Activating a panel policy affects `/v1/panel/invoke`; it does **not** change the legacy
`/v1/invocations` gateway or `/v1/config/*` bundle lifecycle described below. These routes share
identity and storage infrastructure but do not share policies, evidence, counters or audit views.
The [control-panel contract](contracts/control-panel.md) records this boundary and the full API.

All panel services are local synthetic adapters. Imported endpoint strings are metadata, and
verification does not test remote reachability. Semantic decisions use the offline baseline
heuristic. Model/instruction settings are retained but do not execute a trained model, use a
provider cache or incur model token charges. Signature feeds are bundled locally. Throttle is
admission refusal with retry-after information, not a delay followed by dispatch. Token budgets
use labelled input-length estimates per synthetic agent and UTC day. Replay uses sanitized
retained content without dispatch, and host YAML files are not watched.

For isolated verification, start a **fresh** backend from `app/` with Python 3.11+ (do not load
`.env`):

```sh
APP_STORAGE=memory APP_RUNTIME_CACHE=off APP_BIND=127.0.0.1 APP_PORT=18082 python3 -m action_gate.http_server
```

Run `make control-ui-check` from the root with a separate Chrome instance listening on
`--remote-debugging-port=9229`. The checker requires loopback, memory storage and the offline
baseline. Restart that isolated backend before another run. This is a verification command, not
a claim that a particular run has passed. The usual `make up` build includes the panel in the API
image; no Node build or frontend container is required.

| Command, from repository root | Purpose | Needs |
|---|---|---|
| `make config` | Validate Compose without printing interpolated values | — |
| `make up` | Build, run migrations, start the stack, wait for healthchecks | Docker |
| `make status` / `make logs` / `make down` | Container state / follow logs / stop (volume kept) | Docker |
| `make test` | 128 unit and route tests; no Docker, packages or network (`15` integration tests are excluded by design) | Python only |
| `make test-integration` | 15 storage tests against the PostgreSQL inside the running stack | the stack |
| `make acceptance` | 145 end-to-end checks through Traefik, including no-dispatch-after-refusal and the whole policy lifecycle | the stack |
| `make ui-check` | 37 checks that drive the console in a real browser over the DevTools Protocol | the stack plus local Chrome with `--remote-debugging-port=9229` |
| `make smoke` | `make test` followed by `make acceptance` | both |

`make init` creates `.env` from [.env.example](../.env.example) only if absent; the local file is
ignored by Git. Its credentials and hash salt are synthetic local defaults, not production secrets.
Existing PostgreSQL volumes keep their original credentials after `.env` changes: editing
environment values is not a credential migration. Do not add `--volumes` to shutdown commands
unless you intend to delete local data.

## What one invocation does

```text
POST /v1/invocations
  -> identity from headers (role from the registry, never from the body)
  -> one pinned ConfigSnapshot (release hash + activation generation)
  -> grant check for service + action
  -> deterministic input controls (signatures, sensitive patterns, size, model allowlist)
  -> reserved semantic input check (baseline offline, or the opt-in provider)
  -> atomic reservation for the output check and the target call + output time reserve
  -> exactly one dispatch to the synthetic Document Desk service
  -> output controls on whatever the service returned
  -> durable budget commit and sanitized audit
```

**One invocation, one snapshot.** The snapshot is parsed, validated and frozen once and handed
explicitly to the parser, the grant check, the input controls and the output controls. No stage on
this path reads a policy file, so an activation that lands mid-call cannot split one invocation
across two rule sets. The release hash is the canonical hash of *the rules that execute*; the raw
file hash is reported separately as `fileHash`.

### Three answers, never merged

| Field | Question |
|---|---|
| `policy.decision` | what the **input** controls decided (`allow`, `redact`, `block`) |
| `action.outcome` | what happened at the **effect boundary** (`succeeded`, `not_started`, `failed`) |
| `output.disclosure` | what was **disclosed** (`full`, `redacted`, `withheld`) |

`withheld` with `succeeded` is a correct result: the action ran and the poisoned answer was not
handed back. Withholding is not a rollback and the response never claims to undo an executed action.
`200` means the call was processed, never that the content was safe.

Invariants this release enforces, each with tests:

* A refusal — grant, signature, sensitivity, model, semantic threshold, budget, output reserve,
  expired deadline or unavailable mandatory check — never reaches the service adapter.
  `action.outcome` stays `not_started` and the dispatch counter is unchanged.
* Sensitive values are replaced with `[REDACTED]` before any detector sees the text, and the
  sanitized projection is what reaches the target service.
* Idempotency is durable, claimed and **principal-scoped**: two callers that pick the same client key
  are two different operations, and neither can observe or block the other's replay. Two concurrent
  calls from one principal execute the action exactly once; the loser receives
  `409 idempotency_in_progress`, or a replay if the winner already finished. A key whose earlier
  attempt never recorded an outcome is `409 idempotency_unknown` and is never executed again
  automatically. A dry run never occupies the key of a real action.
* The fingerprint covers everything that changes execution (service, action, document, text, model,
  detector and budget overrides, timeout, dry-run) and is versioned; the active release hash is
  deliberately **not** part of it, so retrying a completed call after an activation still replays
  instead of acting twice.
* The invocation row, its audit events and the claim state are written in one transaction.
* A charge above its reservation is recorded as `overdraftTokens`, stays part of the next admission
  check instead of pushing the limit below zero, and `overLimit` is reported rather than a negative
  remainder.
* `budgetScope` and `detectorProfile` are operator-only knobs.
* Dry runs are charged for the semantic work they trigger and never dispatch.
* Audit never stores raw untrusted text; repositories sanitize again on write so a direct database
  call cannot bypass the check.

The full contract, response shape and status mapping are in
[contracts/invocation.md](contracts/invocation.md).

```sh
curl http://ai-control-proxy.localhost/health/ready
curl http://ai-control-proxy.localhost/v1/config/release
curl -X POST http://ai-control-proxy.localhost/v1/invocations \
  -H 'X-Action-Gate-Principal: agent-local' -H 'X-Action-Gate-Token: local-agent-token' \
  -H 'Content-Type: application/json' \
  -d '{"idempotencyKey":"read-1","service":"document-desk","action":"documents.read",
       "input":{"documentId":"field-report"},"model":"demo-local"}'
```

That last call returns `200` with `output.disclosure: withheld`: the synthetic `field-report`
document contains an injected instruction, and the output control keeps it away from the calling
agent while reporting honestly that the read itself happened.

## Policy lifecycle

PostgreSQL holds the active release, the immutable releases, the drafts, the activation log and the
comparisons. The files are imported once, on the first start; a second start reads the database and
never re-imports.

```text
GET  /v1/config/active                      editable documents, release hash, generation
POST /v1/config/validate                    validate documents, store nothing
POST /v1/config/drafts                      create a draft from the active release
PUT  /v1/config/drafts/{id}                 replace documents at an expected revision
POST /v1/config/drafts/{id}/compare         run the invocation evaluator, never the target
POST /v1/config/activations                 activate with expected revision + generation
POST /v1/config/rollbacks                   re-activate a stored snapshot as a new generation
GET  /v1/config/export                      one portable bundle, credentials excluded
POST /v1/config/import                      validate a bundle into a draft
GET  /v1/config/releases, /activations      release history and the append-only activation log
GET  /v1/config/evaluations/{id}            stored comparison summary
```

Rules the tests enforce, not just document:

* **A draft is not live.** Saving one changes nothing until an activation commits it.
* **Activation is a compare-and-swap.** The caller states the draft revision and the active
  generation it saw; two racing clients produce one activation and one `409 active_changed`.
* **A content change needs a current, complete comparison** bound to that candidate hash, that active
  hash and generation, the dataset hash and the resolved detector identity. A comparison invalidated
  only by a detector runtime change is refused as stale.
* **Only raising existing caps may skip the comparison**, and only when a structural diff proves
  every other document is identical (`mode: budget-only`, zero provider calls). That narrow path
  exists so an exhausted evaluation budget cannot block its own recovery; it cannot weaken a
  control, a grant or the model allowlist.
* **`complete` and `passed` are different answers.** `complete` means every case ran; `passed` means
  the candidate matched the expectations the editor stated. Activation requires both.
* **Rollback restores rules, never consumption.** Usage, reservations, claims, observations, audit
  and effects are untouched, and a revoked credential is not restored. A release stored without a
  full snapshot reports `rollbackAvailable: false`.
* **Caps change in exactly one place.** A reservation or a report read may create the ledger row for
  a new UTC day, but it can never rewrite an existing limit.
* **Credentials and endpoints are not editable and not exportable.** A payload that tries to set a
  base URL, a key or a file path is rejected with `422 credential_field_rejected`; an exported
  bundle never contains the principal table.

Editing `app/policy/*.json` on the host no longer changes live behaviour after the first start: the
change must be exported, imported and activated. `/version` reports `configSource: database` and the
release the service is actually running. Details:
[contracts/configuration.md](contracts/configuration.md).

## Semantic detection

`policy/detectors.json` defines two profiles and the gate never confuses them:

* `baseline-offline-v1` — a deterministic offline scorer. It is labelled `baseline` everywhere:
  a heuristic on risk cues with defensive-framing damping and an obfuscation floor. **It is not a
  trained model and it does not prove hybrid AI defence.**
* `provider-chat-v1` — an opt-in OpenAI-compatible chat adapter. It stays `unavailable` until
  `DETECTOR_PROVIDER_BASE_URL`, `DETECTOR_PROVIDER_API_KEY` and `DETECTOR_PROVIDER_MODEL` are set in
  the environment. Request data can never enable, rename or redirect it. Supply credentials only on
  the owner's explicit instruction; the repository ships none.

Only already-redacted text is sent. Prompts, responses and credentials are never logged, provider
output is parsed strictly, and every failure mode — unreachable, HTTP error, oversized or invalid
response, missing usage, expired deadline — becomes `semantic_unavailable`. Under the shipped policy
(`semantic_unavailable: block`) that is a refusal with HTTP `503`, never an allow. The provider
timeout is read as milliseconds (`DETECTOR_PROVIDER_TIMEOUT_MS`, clamped to 200–30000 ms), the whole
exchange is bounded in size and time, and a request whose deadline has already passed is not sent.

For `gpt-5-nano` and its dated snapshots, the adapter uses `reasoning_effort: minimal`, JSON mode
and `max_completion_tokens: 1024`, omitting `temperature` and `max_tokens`. The allowance includes
reasoning and visible output; input, output and evaluation reservations include this allowance
before the call. Other providers retain the existing 96-token completion cap. Truncated or
content-filtered responses fail closed, even when their partial content looks like valid JSON.
The 1024-token cap is an initial bounded configuration, not a measured guarantee that every request
will finish within it. Setting credentials does not switch the database's active detector profile.

Semantic results are stored as observations keyed by profile, resolved model, endpoint, direction,
instruction version and a keyed projection hash. Compare and evaluation reuse them without a second
model call; a genuinely new projection still reaches the detector.

## Configuration bundle

`policy/bundle.json` references `policy.json`, `signatures.json`, `services.json`, `budgets.json`,
`detectors.json` and `principals.json` by relative name. Every component is validated — unknown
fields, types, sizes and duplicate JSON keys are all rejected — and hashed in canonical form.

Editable through the lifecycle: content policy, signature feed, grants of known actions, caps of
known budget scopes, selection of a known detector profile. Not editable: the adapter catalogue,
endpoints, credentials, transport identity and arbitrary environment references.

Invalid configuration never degrades silently: a call against an invalid active release is refused
with `configuration_invalid` and HTTP `503`, and an invalid draft or import is refused without
touching the active release.

## Data and durability

| Store | Contents | If it is lost |
|---|---|---|
| PostgreSQL (named volume) | Active release and generation, immutable releases, drafts, activation log, comparisons, invocations, audit events, budget ledger and reservations with provenance, semantic observations, dispatch effects, synthetic documents | Real data loss; the source of truth |
| Redis (no RDB/AOF, tmpfs) | Cached semantic observations only | A cache miss; nothing else changes |

Without a reachable PostgreSQL the gate refuses to serve rather than dispatching without a durable
record. `APP_STORAGE=memory` exists for tests and Docker-less runs; `/version` reports
`durable: false` for it and it must not be used to claim durability. In memory mode the policy
lifecycle works for a single process and is lost on restart.

Migrations are applied in filename order and recorded in `schema_migrations`; an applied file is
never edited. `0003_policy_lifecycle.sql` adds the lifecycle tables, principal-scoped claims, budget
provenance and reporting indexes, and recovers ownership for pre-existing claims from their
invocation rows. A claim with no trustworthy owner stays blocked for automatic retry.

## Run the tests

```sh
make test                 # Discover unit and route tests; optional dependencies affect skips
make test-integration     # Storage tests inside the stack (require PostgreSQL)
make acceptance           # End-to-end checks through Traefik
make ui-check             # Browser checks (optional, needs a local Chrome on port 9229)
```

The unit suite includes fail-closed tests for detector outages, budget refusal and dry-run charging,
claim-based concurrency, principal-scoped replay, output withholding, operator-only overrides,
snapshot immutability under a concurrent edit, caps ownership, and audit sanitization. Doubles are
used only for failure mechanics; detector behaviour, redaction-before-provider and cache identity are
tested against stub providers over loopback. Concurrency of the PostgreSQL reservation, the claim
itself and the lifecycle across a restart live in the integration suite.

## MCP slice: three dummy services behind one client-facing ingress

The `demo-mcp` Compose profile adds what the implementation plan (archive reference: `../docs/21-dummy-mcp-implementation-plan.md`)
describes and the handoff (archive reference: `../docs/22-mcp-implementation-handoff.md`) records as verified:

* `gate-mcp` — the only MCP endpoint a client talks to (`/mcp` through Traefik) and the only owner of
  network dispatch. It resolves transport identity through the same principal registry the API uses,
  filters `tools/list` per principal and policy version, and runs every call through the
  `ExecutionCoordinator`.
* `documents-mcp`, `outbox-mcp`, `tickets-mcp` — one image, three commands, one SQLite volume each,
  on separate `internal` networks. No published port, no route from the client network, no database
  credential, no internet.
* Durable state per operation: one `mcp_operations` row carrying the policy/catalog snapshot
  identity, the request fingerprint, the effect outcome and the disclosure; rate accounting that
  counts refused attempts; a sanitized audit trail; and a receipt at the service that is the
  independent proof.

```sh
make demo-mcp-up                                   # credentials, stack, registry, policy, identities
make demo-mcp-client ARGS="--principal support-agent scenario"
make demo-mcp-inspect                              # Gate decisions next to stored service state
make demo-mcp-test                                 # acceptance matrix, writes evidence/
make demo-mcp-scenario-update                      # allow updating exactly one document
make demo-mcp-reconcile                            # read receipts for unknown outcomes
make demo-mcp-reset DEMO_RUN_ID=run-0002            # move Gate and services to a new run
```

Contracts: [protocol profile](contracts/mcp-protocol-profile.md),
[tool contracts](contracts/mcp-tool-contracts.md), [operations, idempotency and evidence](contracts/mcp-operations.md).

What the slice deliberately does **not** claim:

* the idempotency metadata (`params._meta["actiongate.demo/operation_key"]`) is **our extension**, not
  an MCP guarantee. A third-party host without it can read; a mutation without a key is refused with
  a typed error instead of being executed twice.
* a lost response is reported as `outcome_unknown` and is never re-sent automatically; the receipt is
  read by the operator path or after a restart. A timeout is not "no effect".
* a schema that changed at a service blocks the affected tool until an operator re-publishes with
  `--approve-drift`.
* the client tokens in `policy/principals.json` are local synthetic placeholders; only the
  Gate→service credentials in `secrets/credentials.json` are generated outside Git, one scope per
  service.

## Boundaries of this release

This is a local demonstration environment, not a production deployment:

* Identity is a static local registry with synthetic tokens; there is no TLS, secret manager, OIDC,
  multi-tenancy, SIEM export or rate limiting. `/`, `/health/*`, `/version`, `/v1/config/release`
  and `/v1/services` are public by design because they expose no invocation content; everything that
  returns caller data or changes configuration requires a configured principal, and configuration
  additionally requires the operator capability — checked on the server, not by hiding a button.
* The stored response is the *disclosed* result: a withheld output is stored as `null`, a redacted
  one as its redacted text. It is never raw untrusted input, and the trace route that serves it
  requires an identity that owns it.
* `APP_HASH_SALT` ships as a public placeholder in `.env.example`. Until a deployment substitutes its
  own value, `/version` reports `hashSalt: development-default` and the stored digests must be
  treated as brute-forceable.
* The legacy invocation path uses the synthetic `document-desk` adapter. The MCP ingress adds
  Documents, Outbox and Tickets; the Responses proxy adds a real provider hop when configured.
  Each path has its own [contract and limits](contracts/README.md).
* The offline baseline is not a trained model. No real local model profile was connected in this
  iteration: semantic quality is **unverified** and remains an open release condition, not a result.
  See [open questions](../docs/07-open-questions.md).
* No production throughput or latency claim is made. The numbers in the evidence report are one
  laptop, one process, synthetic traffic.
* Image tags pin versions but not digests, so byte-identical rebuilds are not claimed.

## Continue implementation

Start with the [documentation map](../docs/00-documentation-map.md) and [transfer limits](../docs/transfer.md), then the [structure map](docs/structure.md), [contracts](contracts/README.md) and [migration guide](migrations/README.md). Follow [decisions](../docs/01-decision.md) and [open questions](../docs/07-open-questions.md) for current work. Earlier release handoffs belong to the omitted archive; they are not prerequisites for navigating this copy.
