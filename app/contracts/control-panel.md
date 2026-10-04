# Original control-panel HTTP contract

**Implementation facts:** this document describes the restored visual panel at `/control/`,
implemented by [panel.js](../static/control/panel.js), [panel_service.py](../action_gate/panel_service.py)
and [panel_engine.py](../action_gate/panel_engine.py). The original prototype is preserved in
ai-control-layer (archive reference: `../../ai-control-layer/`). This document describes code behavior; it does not
claim that a verification run has passed.

## Boundary and identity

`/v1/panel/*` is the execution and persistence surface for the original visual/YAML policy format.
It shares the HTTP server, configured identity registry and storage backend with the existing
application. It has its own policy, history, tests, counters, audit, idempotency claims and local
synthetic effects.

**A panel activation does not change `/v1/invocations` or `/v1/config/*`.** Those existing routes
remain the developer workbench's separate gateway and bundle lifecycle, documented in
[invocation.md](invocation.md) and [configuration.md](configuration.md). The policy formats and
comparison evidence are not interchangeable. Existing gateway records do not become panel events.

Every panel request requires these transport headers:

```http
X-Action-Gate-Principal: operator-local
X-Action-Gate-Token: local-operator-token
Content-Type: application/json
```

These are shipped local synthetic credentials. The panel UI requires an operator account and
keeps credentials only in memory. Reload and disconnect forget them. The server checks the
configured capability and operator role for management routes. `POST /v1/panel/invoke` also accepts
an authenticated agent: its subject is replaced with the transport principal, regardless of a
body-supplied agent. Only an operator can choose a synthetic agent for an on-behalf-of invocation.
The recorded `actor` remains the authenticated principal.

## Routes

All paths below are relative to `/v1/panel`. JSON mutations require an object body. Successful
operations return HTTP 200; a policy block is a processed invocation with an explicit decision,
not an authentication or HTTP transport failure.

| Method and path | Request | Response and effect |
|---|---|---|
| `GET /state` | — | Active policy, shared draft, schemas, tests, history, bounded event/training views and metadata |
| `POST /draft` | `{policy, expectedRevision}` | Saves the shared draft using its own revision; returns full state; does not activate |
| `PUT /tests` | `{tests}` | Replaces the saved synthetic corpus; returns full state |
| `POST /compare` | `{policy, tests?, expectedVersion, faults?}` | Evaluates live and candidate policies, persists comparison evidence; no target dispatch |
| `POST /activate` | `{policy, tests?, expectedVersion, evaluationId, reason?, source?, overrideMismatches?}` | Validates bound evidence, creates the next active version and resets the shared draft; returns full state |
| `POST /services` | `{service}` | Imports a typed local schema; returns full state |
| `POST /services/{id}/verify` | `{}` | Verifies the schema against the local synthetic adapter; returns full state |
| `POST /invoke` | `{request, idempotencyKey, onBehalfOf?}` | Returns the persisted event; may execute one local synthetic action |
| `POST /events/{id}/replay` | `{policy?}` | Returns `{current, draft?, sanitizedReplay:true, note}`; reevaluation only |
| `POST /events/{id}/review` | `{fp:true, comment?}` | Saves a false-positive review and flags related training examples; returns event; `fp:false` clears the flag |
| `PATCH /training/{id}` | `{review, corrected?}` | Saves review; returns the example |
| `GET /training/export` | — | `{jsonl, count, semanticMode:"baseline"}` containing confirmed/corrected examples |

The full state includes:

```text
policy: {version, default_reaction, checks, rules}
draft: {policy, revision, id, baseVersion}
services, tests, history, events, training
revision, registryRevision, semanticMode: "baseline"
storage, durable, runtime: "panel-local-synthetic"
effectCount, eventCount, trainingCount, usage, usageNote, note
```

`revision` advances on stored panel mutations. `draft.revision` is the draft compare-and-swap
value; it is not the global revision. `registryRevision` changes when a service is imported.
The state response returns the latest 500 events and 1,500 training examples. Request summary
counts in the browser cover loaded records. This interface does not provide cursor pagination or
an all-time percentile query; global record totals are separate metadata.

History entries contain `v`, `policy`, `author`, `source`, `at`, structured `ops` and `summary`.
Activations additionally record comparison identity and any explicit mismatch override.

## Draft, comparison and activation

Draft and test editing can retain incomplete form values. The draft must still have a renderable
structure. Strict policy/catalog/request validation runs before comparison, activation and
invocation. Saving does not imply that a draft is executable.

The browser autosaves validly parsed YAML and visual edits. YAML is parsed locally using the
vendored `js-yaml` dependency; the API accepts the resulting JSON policy. File import changes the
draft, and file export downloads that draft. Neither writes a server policy file.

`Check external changes` and polling compare actual server versions. The editor offers active
policy replacement or rebasing of local edits after another session activates a policy. There
is no filesystem watcher, simulated external edit, or automatic activation of a host YAML file.

A comparison returns:

```json
{
  "id": "comparison-uuid",
  "version": 1,
  "candidateHash": "canonical-policy-hash",
  "results": [
    {"id": "test-id", "live": {}, "draft": {}, "expected": "allow", "passed": true, "changed": false}
  ],
  "complete": true,
  "passed": true,
  "targetDispatchCount": 0,
  "semanticMode": "baseline",
  "modelCalls": 0,
  "registryRevision": 1,
  "faults": {}
}
```

`live` and `draft` are evaluation results with decision, triggering check/rule, ordered check
trace, processed content and version. Comparison checks both content controls and service access
rules. `monitor` counts as allowed when matching expectations. An explicit `expected_output`
also compares the processed string. Comparison output is sanitized before returning.

Evidence binds the candidate policy hash, active version, supplied test corpus, saved corpus and
service registry revision. Activation refuses stale or absent evidence. A complete comparison
with failed expectations requires `overrideMismatches:true`; this applies to existing failures as
well as newly broken cases. The browser requires explicit acknowledgment and records a reason.

`faults` maps check IDs to `unknown` or `timeout` for a test-only baseline failure. Fault
comparisons cannot authorize activation. The apply dialog always obtains a normal comparison,
even when the test tab has fault injection selected. Invocation never accepts runtime fault or
counter overrides.

For an existing semantic check ID, the server sets `instruction_version` to the active check
version when instruction text is unchanged, or to that version plus one when text changes. Draft
save, comparison and activation apply the same normalization; the browser cannot forge that
existing check's instruction version by editing the field alone. This metadata still does not
mean that the baseline executes the instruction.

Activation increments the version, adds immutable history and resets the draft at a new draft
revision. `source` may be `Console`, `Rollback` or `Import`. Rollback uses a historical policy as a
new candidate and goes through the same comparison and activation path. It does not delete
history, refund usage, undo synthetic actions or restore an old idempotency namespace. An
unchanged candidate is rejected with `no_change`.

## Policy and execution semantics

Policy checks execute in the saved order. Available types are secrets detection, personal-data
detection, custom regex, allowed models, denied paths, service access, bundled exploit
signatures, rate limit, loop detection, estimated token budget and semantic baseline checks.
Disabled checks appear as off; checks after a block appear as skipped. Results distinguish
`allow`, `monitor`, `redact`, `throttle` and `block`.

Service rules match an agent, service, action and zero or more parameter conditions. A named
agent outranks a wildcard agent, then a named action outranks any action. Block wins a tie at the
same specificity. Supported conditions are `eq`, `neq`, `contains`, `not_contains`, `starts_with`,
`lte` and `gte`. Unmatched calls use `default_reaction`. The service-access check can enforce,
monitor or be disabled. Exceptions are check-specific, case-insensitive text matches, optionally
restricted to an agent; other checks continue to execute.

Custom regex supports a bounded subset. Groups, alternation, lookarounds, backreferences,
unbounded quantifiers and multiple variable repeats are rejected. A pattern accepted by the
browser's basic syntax check can still be refused by the server's bounded evaluator.

Semantic checks use a deterministic heuristic with mandatory secret/PII sanitization before
classification. They do not call a trained model. Model names, instructions, instruction versions,
cache expectations and timeout settings remain editable configuration; the instruction is not
executed, there are no provider token charges or prefix-cache hits, and the timeout fault is a
test input rather than a measured provider outage. Check traces label the baseline and report
`cache:"not_applicable"`, zero model tokens and `instruction_executed:false`.

Signature source and refresh interval are retained configuration. Runtime uses bundled static
signatures and does not fetch the configured feed. Catalog endpoint strings are metadata; they
never become network destinations.

## Invocation, effects and accounting

A minimal operator invocation is:

```json
{
  "idempotencyKey": "unique-client-key",
  "onBehalfOf": "support-bot",
  "request": {
    "agent": "support-bot",
    "dir": "tool_call",
    "service": "documents",
    "action": "read",
    "params": {"doc_id": "KB-1042"}
  }
}
```

For `input` or `output`, provide a model `target` and `text`; these are local content evaluations,
not provider calls. Service parameters must match the imported schema's string, number or boolean
types and required fields. The server constructs tool-call text from the validated arguments.

One transaction locks the panel state, selects the active policy, calculates trusted counters,
evaluates input, conditionally applies the local effect, evaluates output and stores the event,
usage and claim. PostgreSQL mode persists that transaction in `control_panel_state`; memory mode
is intentionally ephemeral. Bootstrap loads `panel_seed.json` only when there is no panel state;
it seeds policy, services and tests, with empty event and training collections.

Idempotency is scoped to the authenticated principal. Repeating the same key and request returns
the stored event with `replayed:true`; changing the request for that key returns
`idempotency_conflict`. Retrying after a policy activation replays the original event. Claims and
synthetic effects commit together; no remote adapter or out-of-process side effect is involved.

`documents.read/search/update/delete` operate on local synthetic document state. Other catalog
actions record a local synthetic effect and return an explicit synthetic result. Importing a
schema does not implement or contact that external business service. Verification means
`scope:"local_synthetic_schema"`, not network reachability or compatibility with a deployed API.

Redacted tool parameters, not the original parameters, reach the local adapter. The evaluator
refuses unsafe schema-changing redaction and rechecks access against final changed arguments.
Input `block` and `throttle` decisions never dispatch. Throttle is admission refusal with a
retry-after duration; it does not sleep, queue or automatically retry the call.

Rate and loop admission use persisted attempts from the previous 60 seconds, including the
current attempt. The token budget uses a UTF-8 input-length estimate per synthetic agent and UTC
day. It is not measured LLM token usage, a provider invoice or a production budget ledger.
Comparison can use explicit synthetic test counters; live invocation ignores client metadata
when calculating counters.

Events separate these outcomes:

| Field | Meaning |
|---|---|
| `r.decision`, `policy.decision` | Input evaluation decision |
| `action.outcome`, `action.dispatched` | Local effect success/failure/admission refusal and whether dispatch happened |
| `output.disclosure`, `output.text` | Full, redacted, withheld or absent output |
| `outputR`, `policy.outputDecision` | Separate output inspection trace and decision |
| `actor`, `onBehalfOf` | Transport principal and optional operator-selected synthetic agent |
| `tokensStatus`, `usageKind` | Explicit synthetic estimate labels |

A succeeded action with withheld output is valid: output controls do not undo an action. Withheld
output content is omitted from output traces and associated training examples.

## Audit, replay and training boundaries

Request events, traces, reviews, retained replay content and examples are sanitized before
persistence. The browser never reconstructs raw input. Replay reevaluates the retained sanitized
request against the current and optional draft policy; it does not redispatch, consume budget,
reproduce the original rate window or promise the original result. Sanitization can change the
result of a later replay.

Explicitly authored synthetic test fixtures are a separate corpus and retain their configured
inputs and expectations. Use synthetic values in that corpus. Comparison evidence keeps hashes
and verdicts rather than an additional raw request copy.

Training examples come from actual baseline evaluations of local synthetic traffic. Reviews may
be `unreviewed`, `needs review`, `confirmed` or `corrected`; a corrected label must belong to the
labels recorded for that example's classifier version. JSONL export contains only confirmed or
corrected examples and labels its baseline origin. No automatic retention job, fine-tuning,
model switch or model quality threshold is implemented by this contract.

## Errors and practical limits

Missing/invalid identity or role is an authentication/authorization error. Invalid policy or
request data is HTTP 422. Revision/evidence/idempotency conflicts are HTTP 409; unknown records
are HTTP 404; unavailable storage is HTTP 503. Error details use the existing HTTP server's error
envelope. Clients must obtain fresh state and comparison evidence after an active-version
conflict rather than silently overwriting it.

The panel is a local demonstration with a single locked state row, bounded response windows and
local synthetic adapters. It has no production SSO/TLS setup, external service integration,
filesystem watching, trained model, automatic replay recovery or measured scalability guarantee.

## Operator fixes (2026-10-04)

Check exceptions now use case-insensitive **full request text equality**; existing `match` values
are interpreted as exact text, never substrings. Adding any text invalidates the exception.
The exception only affects its check, so all other controls still apply.

Compare estimates each fixture's input tokens with the same UTF-8 estimator as live admission.
Fixture `meta.tokens_used` defaults to zero; `meta.tokens_requested` can retain the original
estimate from a sanitized recorded request. Live invocation never accepts these overrides.
Events retain `evaluationContext`, which Save as test case copies into fixture metadata.
Comparison does not consume live counters and cannot predict future concurrency or usage.

Unchanged refreshes preserve draft/test object identities used by open form handlers. Remote
changes replace and redraw the affected editor. Requests search includes the full request ID;
not-started actions show no received payload. Content-only evaluations explicitly state that no
model dispatch occurred.
