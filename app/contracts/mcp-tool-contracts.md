# Tool contracts of the demo MCP services

This file pins the published tools of the three dummy services and the two hops that carry them. It is
the reference an operator reviews before publishing a registry revision, and the reference a test
author writes acceptance checks against.

Nothing here is a claim about a third-party system: every schema is authored in this repository and
served by a container that reaches no network but the Gate.

## 1. Two hops, two vocabularies

| Hop | Caller identity | Control metadata | Business arguments |
|---|---|---|---|
| Client → `gate-mcp` | `support-agent`, `observer-agent`, `operator-local` from the shared principal registry | `actiongate.demo/operation_key` in `params._meta` | the published tool's `inputSchema` |
| `gate-mcp` → dummy service | `gate-mcp`, one generated token per service scope | `actiongate.internal/{operation_id,demo_run_id,actor}` in `params._meta` | the same arguments after the policy's processed-argument step |

A client never sees the second hop's namespace, and the Gate never forwards a client token. A dummy
refuses a call whose control metadata is missing or malformed with a JSON-RPC `-32602` error, so a
control field can never be smuggled in as a business argument.

## 2. Published catalog

| Published tool | Service | Upstream tool | Panel service/action | Kind |
|---|---|---|---|---|
| `documents_search` | documents | `search_documents` | `demo_documents.search` | read |
| `documents_read` | documents | `read_document` | `demo_documents.read` | read |
| `documents_update` | documents | `update_document` | `demo_documents.update` | mutation |
| `outbox_send` | outbox | `send_message` | `demo_outbox.send` | mutation |
| `outbox_get` | outbox | `get_message` | `demo_outbox.get` | read |
| `outbox_list` | outbox | `list_messages` | `demo_outbox.list` | read |
| `tickets_create` | tickets | `create_ticket` | `demo_tickets.create` | mutation |
| `tickets_read` | tickets | `read_ticket` | `demo_tickets.read` | read |
| `tickets_transition` | tickets | `transition_ticket` | `demo_tickets.transition` | mutation |

A tool is in a caller's catalog only when the policy contains a rule for that caller and that
service/action pair. A tool with no rule is absent from `tools/list` and a guessed name of it is
answered exactly like an unknown name.

## 3. Arguments

All schemas use `additionalProperties: false` and are validated without coercion: `"2"` is not `2`.

### `documents_search`
```json
{"query": "string, 1–200 characters",
 "limit": "integer 1–20, optional, default 10"}
```
Returns `results: [{doc_id, title}]` and `count`. Never a snippet. Every returned document id is
re-checked against the caller's read rule, and a withheld entry is only counted (`filtered_count`),
never named.

### `documents_read`
```json
{"doc_id": "string matching ^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"}
```
Returns `doc_id`, `title`, `content`, `version`. Seeded fixtures: `KB-1042` (editable instruction),
`KB-9000` (protected policy), `KB-PII-01` (synthetic sensitive values), `KB-INJECT-01` (labelled
adversarial fixture), `KB-RESTRICTED-01` (read refused for `observer-agent`).

### `documents_update`
```json
{"doc_id": "string", "content": "string, 1–64000 characters", "expected_version": "integer ≥ 1"}
```
One atomic commit: content, version and revision row move together, `version` becomes
`expected_version + 1`, and a mismatch is the typed business refusal `version_conflict` with
`currentVersion` in `details`. A repeat of the same operation id with the same arguments returns the
stored receipt; with different arguments it is `idempotency_conflict`.

### `outbox_send`
```json
{"to": "single plain address, ≤ 254 characters",
 "subject": "string, 1–200 characters",
 "body": "string, 1–64000 characters"}
```
The service parses the address itself: display names, address lists, CRLF, whitespace and malformed
domains are refused (`invalid_recipient`) before anything is stored. The stored status is
`stored_locally`; there is no delivery path and no SMTP client in the container.

### `outbox_get` / `outbox_list`
`get_message(message_id)` returns the stored message for its creator only; another principal gets
`not_message_owner`. `list_messages(limit 1–20)` returns metadata of the caller's own messages and
never a body.

### `tickets_create`, `tickets_read`, `tickets_transition`
`create_ticket(title, description)` returns a new `T-…` id in `open` at version 1.
`transition_ticket(ticket_id, target_status, expected_version)` accepts only
`open → in_progress → resolved`; anything else is the typed service refusal
`business_transition_invalid`, independently of what the Gate admitted.

## 4. Result envelope

Success and refusal are two documented shapes of one published output schema (`anyOf`).

Success:
```json
{"status": "succeeded",
 "service": "documents", "tool": "documents_update",
 "operation_id": "<gate operation uuid>", "service_operation_id": "<downstream operation id>",
 "receipt_id": "rcpt-…", "replayed": false,
 "disclosure": "full | redacted | withheld",
 "decision": "allow", "effect": "succeeded", "policy_version": 3,
 "resource_id": "KB-1042", "version": 2}
```
Refusal:
```json
{"status": "denied | throttled | failed | outcome_unknown",
 "operation_id": "<gate operation uuid or null>", "decision": "block | throttle | allow",
 "effect": "not_started | no_effect | unknown", "disclosure": "none | withheld",
 "reason": "…", "error": {"code": "…", "message": "…"}}
```

`effect` and `disclosure` are separate on purpose. `effect: succeeded` with `disclosure: withheld`
means the service changed and the Gate will not show the content; `effect: unknown` means the request
may have been executed and the Gate refuses to guess.

`disclosure` values: `full` (unchanged), `redacted` (the cleaned object is what every representation
is built from), `withheld` (the effect, if any, is reported without content), `none` (no effect).

## 5. Error vocabulary

| Code | Hop | Meaning |
|---|---|---|
| `-32602` JSON-RPC | client → Gate | unknown tool, hidden tool, malformed arguments, missing operation key |
| `-32602` JSON-RPC | Gate → service | missing or malformed internal control metadata |
| `invalid_recipient` | outbox | address refused by the service parser |
| `version_conflict` | documents, tickets | optimistic concurrency failed; no effect |
| `document_not_found`, `ticket_not_found`, `message_not_found` | service | unknown resource in the active run |
| `not_message_owner` | outbox | another principal's message |
| `business_transition_invalid` | tickets | transition outside the supported state machine |
| `stale_run` | service | the request belongs to a closed demonstration run |
| `operation_fenced` | service | an operator fenced this operation id as having no effect |
| `idempotency_conflict` | Gate and service | the same operation key with different content |
| `policy_denied`, `policy_throttled` | Gate | decided before any dispatch |
| `concurrency_limit`, `rate_limited` | Gate | resource limit refused before any dispatch |
| `admission_closed` | Gate | a demonstration reset is in progress |
| `tool_review_required` | Gate | the tool's schema changed and awaits operator review |
| `upstream_unavailable` | Gate | the connection was never established: provably no effect |
| `upstream_timeout`, `upstream_transport_error` | Gate | the outcome is unknown and is not retried automatically |
| `reconciled_after_lost_response` | Gate | a receipt was found; the effect is confirmed, the content is not recovered |
| `operator_fence` | Gate | an operator recorded the terminal no-effect outcome |

## 6. Limits

| Limit | Value | Where |
|---|---|---|
| HTTP body / result | 512 KiB | both hops |
| Single text field | 64 KiB | tool schemas |
| Connection timeout | 1 s | Gate → service |
| Upstream deadline | 5 s | Gate → service |
| Total operation deadline | 8 s | Gate |
| Tools per service | 100 discovered, 20 published | registry |
| Concurrent operations per service | 4 | Gate reservation |
| Calls per principal per minute | 60 | Gate counter, refusals included |
| SQLite busy timeout | 2 s | service, shorter than the upstream deadline |

These are configuration values for a local demonstration, not measured performance.
