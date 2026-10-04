# Protected invocation contract

Release scope: `0.2.0`, matching the [contract index](README.md) and [application version](../action_gate/__init__.py). This is the protected invocation contract, not a separately versioned public API. Implementation: [gateway.py](../action_gate/gateway.py) and [http_server.py](../action_gate/http_server.py); checks: [tests](../tests/). Documentation cleanup does not constitute a new runtime verification.

## Identity

Identity is transport-derived. The caller supplies two headers and nothing else:

| Header | Meaning |
|---|---|
| `X-Action-Gate-Principal` | id from `policy/principals.json` |
| `X-Action-Gate-Token` | matching local token from the same file |

The role comes from the registry entry, never from the request. A body that carries `principal`,
`principalId`, `role`, `roles`, `token`, `grants`, `operator` or `isOperator` is rejected with `422
identity_in_body` instead of being silently ignored. No HTTP endpoint grants or changes a role.

These are synthetic local identities for demonstration. They are not production authentication, and
the token is not a secret-management mechanism.

## `POST /v1/invocations`

```json
{
  "idempotencyKey": "string, 1..200 chars, required",
  "service": "document-desk",
  "action": "documents.read | documents.comment | documents.delete",
  "input": {"documentId": "slug", "text": "optional string"},
  "model": "demo-local",
  "detectorProfile": "baseline-offline-v1",
  "budgetScope": "global-daily",
  "dryRun": false,
  "timeoutMs": 15000
}
```

* `input.documentId` is required for every action and must match `^[a-z0-9][a-z0-9._-]{0,63}$`.
* `input.text` is required for `documents.comment`; it is the untrusted content that passes the
  input controls. For `documents.read` it is optional context.
* `model` must appear in `allowed_models` in `policy.json`. Unknown models are refused, never
  silently replaced.
* `detectorProfile` and `budgetScope` must exist in the pinned release.
* `dryRun: true` runs the full pipeline — including reservation and a real charge for the semantic
  work it triggers — but performs no dispatch and never occupies an idempotency key.
* Unknown top-level or `input` fields are rejected.

### Response

```json
{
  "invocationId": "uuid",
  "replayed": false,
  "dryRun": false,
  "status": "completed | blocked | failed",
  "error": "present only for refusals",
  "policy": {
    "decision": "allow | redact | block",
    "outputDecision": "allow | redact | block | not_run",
    "reasons": ["semantic_threshold"],
    "findings": ["email"],
    "release": "canonical sha256 of the rules this invocation executed",
    "activationGeneration": 3,
    "contentPolicyHash": "canonical sha256 of the content policy",
    "signatureFeedHash": "canonical sha256 of the signature feed"
  },
  "input": {"redacted": false, "bytes": 42},
  "action": {"service": "document-desk", "action": "documents.read",
             "outcome": "succeeded | failed | not_started | unknown",
             "dispatched": true, "detail": {}},
  "output": {"disclosure": "full | redacted | withheld | none", "text": "...", "bytes": 42},
  "semantic": {
    "input": {"status": "available | unavailable | disabled", "mode": "baseline | provider",
              "risk": 0.88, "category": "instruction_hijacking", "usageTokens": 8,
              "usageStatus": "estimated | reported | replayed | unknown", "latencyMs": 0},
    "output": null,
    "profile": "baseline-offline-v1", "mode": "baseline", "replayed": false
  },
  "budget": {"scope": "global-daily", "period": "2026-10-03", "periodKind": "utc_day",
             "limitTokens": 40000, "usedTokens": 120, "reservedTokens": 0,
             "remainingTokens": 39880, "availableTokens": 39880, "overLimit": false,
             "overdraftTokens": 0, "limitCostMicro": 2000000, "usedCostMicro": 0,
             "reservedCostMicro": 0, "limitMs": 900000, "usedMs": 14, "reservedMs": 0,
             "unknownUsageCount": 0},
  "timing": {"totalMs": 3, "inputMs": 1, "dispatchMs": 1, "outputMs": 1},
  "audit": {"events": 9, "trace": "/v1/invocations/<uuid>", "persisted": true}
}
```

Three answers are reported separately and are never merged into one verdict:

| Field | Question it answers |
|---|---|
| `policy.decision` | what the **input** controls decided (`allow`, `redact`, `block`) |
| `action.outcome` | what happened at the **effect boundary** (`succeeded`, `not_started`, `failed`) |
| `output.disclosure` | what was **disclosed** to the caller (`full`, `redacted`, `withheld`, `none`) |

An output block is not a rollback: the action may already have happened, and
`output.disclosure: withheld` plus `action.outcome: succeeded` states that honestly. `200` means the
call was processed — it is not a claim that the content was safe.

`policy.release` is the canonical hash of the rules this invocation executed and
`policy.activationGeneration` is the generation that was active when it started. One invocation
pins exactly one release: a concurrent activation cannot change the rules used by an in-flight call,
and the response reports the release it actually used.

### HTTP status mapping

| Status | Meaning |
|---|---|
| `200` | evaluated; dispatched unless `dryRun` |
| `401` | identity header missing or unknown |
| `400` | `malformed_json`: the body is not valid JSON, or `Content-Length` is unusable |
| `403` | policy refusal: `grant_denied`, `input_blocked` (signature, sensitivity, model allowlist, semantic threshold), `budget_scope_override_denied`, `detector_profile_override_denied` |
| `404` | unknown service, action, invocation id or path |
| `405` | method not allowed |
| `409` | `idempotency_conflict` (same key, different content), `idempotency_in_progress` (the same key is being executed right now) or `idempotency_unknown` (an earlier attempt never recorded an outcome) |
| `413` | body above 64 KiB |
| `422` | schema violation, including identity in the body |
| `429` | budget refused the call before any paid work |
| `503` | a mandatory dependency could not be verified: `semantic_unavailable`, `configuration_invalid`, `storage_unavailable`, `output_reserve_unavailable`, `deadline_exceeded`, `audit_not_persisted` |

A refusal caused by an *unverifiable mandatory check* is `503`, not `403`, so a client can tell
"the policy said no" apart from "the gate could not check".

Two response shapes exist, and the difference is deliberate:

* Once a request has been parsed against a valid release, every outcome uses the full invocation
  response above — including refusals, which carry `action.outcome: not_started`.
* Failures that happen *before* the pipeline starts — unknown identity (`401`), a schema violation
  (`422`), a body that is not JSON (`400`) or an unreadable configuration bundle (`503
  configuration_invalid`) — return the short envelope `{"error": "...", "message": "..."}`. There is
  no pinned release to report against, and nothing was evaluated.

### Idempotency

`idempotencyKey` is claimed **atomically before any paid or irreversible work**
(`invocation_claim.idempotency_key` is the lock). Consequences:

* Two concurrent calls with the same key execute the action exactly once. The loser gets
  `409 idempotency_in_progress`, or a replay if the winner already finished.
* Replaying a completed key returns the stored response with `replayed: true` and performs no second
  dispatch, no second semantic call and no second budget charge.
* The same key with different request content returns `409 idempotency_conflict`. The comparison uses
  a keyed hash (HMAC-SHA256 with `APP_HASH_SALT`) over `service`, `action`, `documentId`, `text`,
  `model`, `detectorProfile`, `budgetScope`, `timeoutMs`, `dryRun` and a fingerprint version; raw
  text is never stored. The active release hash is deliberately **not** part of the fingerprint, so
  retrying a completed call after an activation replays instead of acting twice.
* The key is scoped to the **principal**: two callers that happen to choose the same client key are
  two different operations, and neither can observe or block the other's replay. A dry run never
  occupies the key of a real action, and a real call never satisfies a dry run.
* A claim older than 120 seconds whose outcome was never recorded is reported as
  `409 idempotency_unknown` and is **not** executed again automatically: the earlier attempt may have
  dispatched. An operator must decide, using the trace, what happened.
* Only a caller that owns the claim occupies the key. A refusal that lost the race is still audited,
  under a namespaced key, so it cannot overwrite the authoritative outcome.
* The invocation row, its audit events and the claim state are written in one transaction. A
  dispatched action therefore never ends up without a durable record; if that write fails, the call
  returns `503 audit_not_persisted` and the claim stays unresolved rather than looking successful.

### Authentication

Every route that returns caller data requires the two identity headers:

| Route | Identity |
|---|---|
| `POST /v1/invocations`, `POST /v1/evaluations` | required |
| `GET /v1/invocations`, `GET /v1/invocations/{id}`, `GET /v1/summary`, `GET /v1/audit/export`, `GET /v1/audit/events` | required |
| `GET /v1/me` | required; returns the caller's own principal id, role and capabilities |
| `GET/POST/PUT /v1/config/…` | required **and** the `operator` role |
| `GET /`, `GET /health/live`, `GET /health/ready`, `GET /version`, `GET /v1/config/release`, `GET /v1/services` | public; they expose no invocation content |

`budgetScope` and `detectorProfile` in a request are operator-only. An agent that sends them is
refused with `403 budget_scope_override_denied` or `403 detector_profile_override_denied`, because a
caller must not be able to pick a cheaper ledger or a weaker detector.

### What is stored

The invocation row stores the **disclosed** response: a withheld output is stored as `null`, a
redacted one as its redacted text, and a blocked call stores no output at all. Raw untrusted *input*
is never stored anywhere — not in the invocation row, not in audit events, not in semantic
observations (only a keyed projection hash), not in logs. Hashes are keyed with `APP_HASH_SALT`; the
placeholder shipped in `.env.example` is treated as unconfigured, and `/version` reports
`hashSalt: development-default` until a deployment substitutes its own value.

## Other routes

| Route | Purpose |
|---|---|
| `GET /` | English status page: endpoints, storage, runtime cache |
| `GET /health/live` | process liveness only |
| `GET /health/ready` | configuration valid + storage reachable + runtime cache state |
| `GET /version` | version, stage, storage backend, durability flag, hash-salt source |
| `GET /v1/config/release` | bundle id, release hash, per-component SHA-256, detectors, budgets |
| `GET /v1/services` | service catalog with actions, effects and grants |
| `GET /v1/me` | the caller's principal id, role, capabilities and the active release |
| `GET /v1/invocations?limit=50` | invocation metadata page, newest first, opaque cursor; never a response body |
| `GET /v1/invocations/{id}` | sanitized trace: invocation row + audit events; another principal's id is `404` |
| `POST /v1/evaluations` | legacy content-only preview over cases; never dispatches, and never authorises an activation |
| `GET /v1/summary?window=1440` | reporting view; see [reporting.md](reporting.md) |
| `GET /v1/audit/export?limit=200` | sanitized audit as bounded NDJSON pages with a cursor |
| `GET /v1/audit/events?limit=50` | the same page as JSON |
| `GET /v1/config/active`, `/releases`, `/activations`, `/export` | policy state, history and bundle; see [configuration.md](configuration.md) |

### `POST /v1/evaluations`

Legacy content-only preview, kept for compatibility:

```json
{
  "cases": [{"id": "pii", "direction": "input", "text": "Contact alice@example.org"}],
  "detectorProfile": "baseline-offline-v1",
  "candidate": {"contentPolicy": { ...same shape as policy.json... }}
}
```

Returns per case `active` and `candidate` decisions with `changed`, the list of `changedCases`,
`modelCalls`, `targetDispatchCount` (always `0`) and the evaluation budget state. It validates the
candidate with the same loader as the active release, never calls the target service and **never
authorises an activation**: an activation needs a stored, current comparison from the editor path,
and the status here does not distinguish `complete` from `passed`. A repeated projection reuses the
stored semantic observation (`usageStatus: replayed`), so it does not buy a second model call — and a
genuinely new text still reaches the detector.

For the editor path — full documents, expectations, freshness and the `budget-only` recovery mode —
see [configuration.md](configuration.md).

## Audit content

Audit stores decisions, reason codes, finding labels, signature ids, release hashes, model
provenance, latency, usage status and budget movements. It never stores raw untrusted text: the
writer keeps a denylist (`text`, `body`, `raw`, `prompt`, `content`, `secret`, `token`, `password`,
`key`, …) and a structural sanitizer, and the repositories sanitize again on write so a direct
database call cannot bypass it. Hashes are keyed, so a stored digest of low-entropy input cannot be
brute-forced offline.
