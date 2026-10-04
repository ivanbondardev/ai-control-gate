# Operations, idempotency and evidence contract

This contract fixes the behaviour of one client operation on the MCP ingress: what makes a retry safe,
what happens when an answer is lost, how a reset works and what evidence an operator can read
afterwards. Wire-level details are in [mcp-protocol-profile.md](mcp-protocol-profile.md); tool
schemas are in [mcp-tool-contracts.md](mcp-tool-contracts.md).

## 1. One operation, one durable row

Every admitted tool call becomes exactly one `mcp_operations` row:

| Field group | Meaning |
|---|---|
| identity | `id` (the operation id returned to the client), `demo_run_id`, `principal_id`, `client_operation_key`, `request_id` |
| request identity | `request_fingerprint` = HMAC over service + upstream tool + original arguments, `published_tool`, `upstream_tool`, `service_id`, `panel_service`, `panel_action` |
| snapshot identity | `policy_version`, `policy_hash`, `registry_revision` |
| outcome | `status`, `decision`, `reason`, `effect`, `disclosure`, `error_code`, `receipt_id`, `resource_id`, `before_version`, `after_version` |
| cost | `attempts`, `bytes_in`, `bytes_out`, `admission_ms`, `upstream_ms`, `output_ms`, `total_ms` |
| lease | `owner_lease`, `lease_expires_at`, `dispatch_started_at`, `finished_at` |

`UNIQUE (demo_run_id, principal_id, client_operation_key)` is what makes a retry safe; it is enforced
by the database, not by a cache.

Statuses: `claimed` → (`dispatch_started`) → `succeeded` | `failed` | `outcome_unknown`, or
`not_started` when the decision refused the call before the network, or `interrupted` when a restart
closed a claim that never reached dispatch.

## 2. Idempotency

* The key travels in `params._meta["actiongate.demo/operation_key"]`. It is **our extension**, not an
  MCP guarantee: a host that does not send it can read, and a mutation without it is refused with a
  typed error before anything is dispatched.
* A repeat with the same fingerprint returns the stored client representation with `replayed: true`
  and records no new attempt, so a retry never charges the upstream twice.
* A repeat with a different fingerprint — different tool or different arguments — is
  `idempotency_conflict`, including for a claim that already finished.
* The fingerprint is computed over the original arguments; it deliberately excludes the current policy
  version and the JSON-RPC request id, so an operator's policy change does not turn a retry into a
  conflict.
* A repeat of a refused key returns the stored refusal; it never becomes a new operation.
* Before an old result is disclosed again, the current policy is evaluated for the same request. If
  access has been revoked, the client gets a minimal status without content (`disclosure: withheld`).

## 3. Lost answers and unknown outcomes

| Situation | Gate state | Client sees |
|---|---|---|
| refused before the network | `not_started` | `denied` / `throttled`, `effect: not_started` |
| service confirmed a refusal without a commit | `failed` | `failed`, `effect: no_effect`, typed code |
| commit and answer received | `succeeded` | the cleaned result, `disclosure: full/redacted/withheld` |
| request may have arrived, answer lost | `outcome_unknown` | `outcome_unknown`, `effect: unknown` |
| Gate restarted after an upstream commit | unfinished claim | resolved by reconciliation, never by a new call |
| output blocked after a commit | `succeeded` | `disclosure: withheld`, effect reported |

A connection that was never established (`ConnectError`) is the only failure classified as a provable
no-effect. Everything else after dispatch is unknown, because the Gate cannot prove a negative.

Unknown operations keep their concurrency reservation until a confirmed terminal outcome, are visible
in `--state`, and are resolved only by:

```sh
make demo-mcp-reconcile                                   # read the service receipt for each unknown
make demo-mcp-fence SERVICE=outbox OPERATION_ID=op-...    # terminal no-effect, operator decision
```

The fence is a two-step operator path: the local admin CLI inside the service container writes the
terminal decision under the SQLite write lock. The Gate then reads the authenticated status endpoint
and records no_effect only for a matching operation, run and fence kind. An existing commit wins
and is reconciled as succeeded. The Make command accepts the Gate UUID and resolves its distinct
upstream operation ID; that ID is persisted before dispatch. A late request
for a fenced operation id is refused by the service (`operation_fenced`) and can never commit.

## 4. Reset

`make demo-mcp-reset DEMO_RUN_ID=run-0002` performs the only supported run transition:

1. close admission at the Gate (`admission_closed` for new calls);
2. reconcile every unfinished operation; any remaining unfinished operation blocks reset; there is no force bypass;
3. require all three configured services, then start the new run in each service and re-seed its demonstration data;
4. read back every service run id; only after all match, move the Gate to that run id;
5. reopen admission.

Previous receipts, events and Gate operations are preserved as evidence; a service reset never
deletes them. Startup never resets anything, and deleting a volume is not an update path.

## 5. Rate, concurrency and size limits

| Limit | Value | Behaviour |
|---|---|---|
| calls per principal per minute (Gate) | 60 | `rate_limited`, refusal counted as an attempt |
| calls per agent per minute (policy) | 30 in the shipped policy | `policy_throttled` with a retry hint |
| concurrent operations per service | 4 | `concurrency_limit` before the upstream hop |
| arguments / result | 512 KiB | refusal or `disclosure: withheld` |
| single text field | 64 KiB | schema violation |

A throttle is an explicit refusal with a hint; there is no hidden queue and no sleeping request.

## 6. Audit and evidence

`mcp_audit_events` carries one sanitized row per decision: principal, operation/run ids, published and
upstream tool, policy version and hash, registry revision, decision and reason, effect outcome,
disclosure, receipt reference, request id and durations. Content is never stored there — only
identifiers, typed reasons and counters.

Two independent channels exist and they are not interchangeable:

* **Gate side** — `GET`-equivalent reads through `python -m action_gate.mcp_bootstrap --state`:
  registry revision, run state, counters by status, recent operations and service health.
* **Service side** — `docker compose exec <service>-mcp python -m dummy_mcp.admin --service <s> inspect`:
  a read-only SQLite connection returning the stored rows, call counts, receipts, fences and events.

`make demo-mcp-evidence` writes both into one bundle. A demonstration claim is only supported when the
Gate decision and the stored service state agree.

## 7. What is not claimed

* no end-to-end exactly-once across PostgreSQL and SQLite: they have no shared transaction, which is
  exactly why `outcome_unknown` exists;
* no automatic re-dispatch of an unknown operation, ever;
* no recovery of a lost result: a reconciled operation is reported as succeeded with
  `disclosure: withheld`;
* no deduplication of *new* operation keys, and no guarantee after losing a service volume.

## 8. Isolated acceptance

`make demo-mcp-test` creates a temporary Compose project with dedicated volumes and an ephemeral
loopback port, then removes only that project's containers and volumes. Evidence stays under
`evidence/`. Use `DEMO_MCP_TEST_IN_PLACE=1 make demo-mcp-test` only for an explicit rehearsal-state
mutation: the suite changes policy, creates synthetic effects and tests a run reset.

Malformed business output remains subject to the Gate's pinned JSON Schema, size and content checks.
If the response lacks a receipt, one authenticated read-only status probe must prove the commit
before returning succeeded/withheld. Missing or mismatched evidence remains outcome_unknown;
transport timeouts still require the explicit reconcile path and never cause redispatch.

The baseline PII detector uses the country prefixes in SWIFT IBAN Registry release 101 and token
boundaries for card-like numbers. This avoids classifying generated alphanumeric IDs as financial
accounts while retaining redaction of the covered bank-account and card fixtures. It is not a
complete or measured PII classifier, nor a claim to validate bank accounts.
