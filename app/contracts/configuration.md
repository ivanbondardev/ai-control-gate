# Configuration contract

The policy lifecycle turns configuration into data with a history. PostgreSQL holds the active
release; the files under `app/policy/` are the bootstrap and import format.

Version: **0.2.0**. Roles: every route below requires the `operator` role. An `agent` principal is a
valid caller and still has no configuration capability; the check happens on the server.

## Identity

| Header | Meaning |
|---|---|
| `X-Action-Gate-Principal` | principal id from the server-side registry |
| `X-Action-Gate-Token` | that principal's token |

The role is read from the registry, never from a body. A request that carries `principal`, `role`,
`token`, `grants`, `isOperator` or `operator` in its body is rejected with
`422 identity_in_body`.

## Documents

A release is six documents. Four are editable through the lifecycle, two are deployment
configuration and are not reachable from any payload:

| Document | Editable | Contents |
|---|---|---|
| `contentPolicy` | yes | controls, thresholds, `allowed_models`, `max_text_bytes` |
| `signatureFeed` | yes | signature id, literal, description |
| `services` | yes | known actions of a known service: id, effect, grants, description |
| `budgets` | yes | caps of known scopes, reserve policy, estimation policy |
| `detectors` | no | adapter catalogue: profile id, mode, detector name, environment references |
| `principals` | no | transport identity registry, including tokens |

The editable set is exact. A payload containing `detectors` or `principals` is refused with
`422 document_not_editable`; a payload that tries to set a base URL, an API key, a file path or an
endpoint anywhere inside an editable document is refused with `422 credential_field_rejected`.

## Routes

### `GET /v1/config/active`

```json
{
  "release": "<canonical hash of the rules that execute>",
  "fileHash": "<hash of the bundle the release was imported from>",
  "schemaVersion": "2",
  "activationGeneration": 3,
  "componentHashes": {"contentPolicy": "…", "signatureFeed": "…", "services": "…",
                      "budgets": "…", "detectors": "…", "principals": "…"},
  "editableDocuments": {"contentPolicy": {…}, "signatureFeed": {…}, "services": {…}, "budgets": {…}},
  "storage": "postgres",
  "source": "bootstrap | files | draft | import"
}
```

`release` is the authoritative identity of a release. `fileHash` is kept so an edit on disk can be
spotted; it is *not* used to decide what is active, because whitespace or key order never changes the
executed rules.

### `POST /v1/config/validate`

Body: `{"documents": {…}}` with any subset of the editable documents. Validates the merge over the
active release, stores nothing, returns `{"valid": true, "candidateHash": "…"}` or
`422 candidate_invalid` with the reason.

### `POST /v1/config/drafts`

Body: `{"documents": {…}}` (optional; omitted documents are taken from the active release).
Returns `201` with `draftId`, `revision: 1`, `candidateHash` and the full editable document set.

### `PUT /v1/config/drafts/{id}`

Body: `{"expectedRevision": 1, "documents": {…}}`.
Returns `200` with the new revision, or `409 draft_changed` when the draft moved on. A save never
changes the active release.

### `POST /v1/config/drafts/{id}/compare`

```json
{
  "expectedRevision": 2,
  "actorRole": "operator",
  "cases": [
    {"id": "pii", "direction": "input", "text": "Contact alice@example.org",
     "service": "document-desk", "action": "documents.comment", "model": "demo-local",
     "family": "sensitive_data", "label": "synthetic address",
     "expected": {"decision": "redact", "disclosure": "redacted", "dispatch": true},
     "requireBlock": false}
  ]
}
```

The runner executes the same evaluator an invocation executes, with exactly one difference: the
effect boundary. The target adapter is never called.

```json
{
  "evaluationId": "…",
  "status": "complete | partial | failed",
  "passed": true,
  "mode": "full | budget-only",
  "previewOfActiveRelease": false,
  "active": {"release": "…", "activationGeneration": 3, "componentHashes": {…}},
  "candidate": {"release": "…", "revision": 2, "componentHashes": {…}},
  "detector": {"profile": "baseline-offline-v1",
               "identity": {"model_id": "…", "endpoint_hash": "…", "detector_version": 1},
               "instructionVersion": 1, "mode": "baseline"},
  "datasetHash": null,
  "cases": [{"caseId": "pii", "dispatched": false, "changed": false,
             "verdict": "passed | failed | observed | not_evaluated",
             "active": {"decision": "redact", "reasons": [], "findings": ["email"],
                        "semantic": {…}, "contentPolicyHash": "…", "dispatched": false},
             "candidate": {…}}],
  "checkedCases": 1, "totalCases": 1, "failedCases": [],
  "modelCalls": 1, "unknownUsageCalls": 0,
  "stoppedBy": null, "targetDispatchCount": 0,
  "budget": {…}
}
```

* `complete` — every case ran. `partial` — budget or a provider failure stopped the run.
  `failed` — the candidate could not be evaluated at all.
* `passed` — the candidate matched every expectation the editor stated *and* the run is complete.
  `changed: true` alone is neither a pass nor a failure.
* `verdict: observed` means the case stated no expectation; it is reported, not scored.
* Omitting `candidate.documents` previews the active release against itself
  (`previewOfActiveRelease: true`). That is a regression check, not a comparison of two releases.
* A case that is expected to be blocked is a *passing* test when it is blocked.

### `POST /v1/config/activations`

```json
{"draftId": "…", "expectedRevision": 2, "expectedActiveGeneration": 3,
 "evaluationId": "…", "operationKey": "…", "reason": "…"}
```

Returns `200` with the activation id, the new active release, its generation and the previous
release, or:

| Status | Error | Meaning |
|---|---|---|
| `409` | `active_changed` | the active generation is not the one the caller stated |
| `409` | `draft_changed` | the draft revision is not the one the caller stated |
| `409` | `evaluation_required` | a content change without a current passing comparison |
| `409` | `evaluation_stale` | the comparison belongs to another candidate, active release, generation or detector identity |
| `409` | `no_change` | the candidate is identical to the active release |
| `409` | `operation_conflict` | the operation key was used with a different payload |

Repeating the same operation key with the same payload returns the earlier result with
`replayed: true`. A **caps-only** change (only raising existing limits, every other document
byte-identical in canonical form) is activated without a provider call and is recorded with
`mode: budget-only`; it cannot weaken a control, a grant or the model allowlist.

### `POST /v1/config/rollbacks`

```json
{"targetReleaseHash": "…", "expectedActiveGeneration": 4, "operationKey": "…", "reason": "…"}
```

Activates a stored complete snapshot as a **new** generation. Usage, reservations, claims,
observations, audit and effects are not rewound, and a revoked credential is not restored. A release
recorded without a full snapshot is refused with `409 release_not_rollbackable`.

### `GET /v1/config/releases`, `GET /v1/config/activations`

Bounded history (`limit`, `before`). Each release reports `rollbackAvailable`, which is `false` for
records from 0.1.0 that carry component hashes but no stored documents. The activation log is
append-only and includes bootstrap and rollback events.

### `GET /v1/config/export`, `POST /v1/config/import`

The export is one bundle:

```json
{"schemaVersion": "2", "bundleId": "local-default", "release": "…", "fileHash": "…",
 "documents": {"contentPolicy": {…}, "signatureFeed": {…}, "services": {…}, "budgets": {…}},
 "note": "Editable documents only. …"}
```

It never contains the principal table, so it cannot leak a token. Import validates the bundle as a
draft and never activates it; an unsupported `schemaVersion` is refused with `422 unsupported_schema`.

## Bootstrap rules

1. First start with no active release: the file bundle is validated and imported transactionally as
   generation 1 (`source: bootstrap`). An invalid bundle leaves the service not-ready and it refuses
   to serve rather than running with partial rules.
2. Later starts read the active release from PostgreSQL. Files are never re-imported and the active
   generation is never reset.
3. A release whose stored snapshot is missing cannot be activated or rolled back; the service says so
   instead of guessing.

## Portable JSON bundle (files)

```json
{
  "version": 1,
  "bundleId": "local-default",
  "components": {
    "contentPolicy": "policy.json",
    "signatureFeed": "signatures.json",
    "services": "services.json",
    "budgets": "budgets.json",
    "detectors": "detectors.json",
    "principals": "principals.json"
  }
}
```

Component references must be bare file names ending in `.json`; a path separator is refused, so a
bundle cannot point outside its directory. Duplicate JSON keys, unknown fields, wrong types and
oversized documents are all rejected.
