# Reporting contract

Every read below requires a configured identity. An `operator` sees the whole bench; an `agent` sees
its own rows. The scope is stated in the response (`scope: bench | own`) rather than implied.

## One window for everything

`GET /v1/summary`, `GET /v1/invocations`, `GET /v1/audit/export` and `GET /v1/audit/events` accept the
same window parameters:

| Parameter | Meaning |
|---|---|
| `window` | minutes back from `until`, 1–43200; default 1440 |
| `since` | ISO-8601 timestamp **with** a timezone offset; default `until - window` |
| `until` | ISO-8601 timestamp with a timezone offset; default now |

Bounds are normalised to UTC and printed in one format (`…Z`, milliseconds). The interval is
`[since, until)`. A naive timestamp, an unparseable one, an interval where `since >= until` and a
non-numeric `window` are all `422 schema_invalid`. This is deliberate: a report whose counters use
different windows is worse than a refused report.

The daily budget ledger is a **UTC day**. It is reported with `periodKind: utc_day`, its own
`period`, and the label `Current shared budget (UTC day, all callers)`. It is not a per-agent budget
and not a figure for the activity window.

## `GET /v1/summary`

```json
{
  "window": {"since": "…Z", "until": "…Z"},
  "invocations": {"total": 12, "allowed": 7, "redacted": 2, "blocked": 3, "dryRun": 1, "replayed": 1},
  "disclosure": {"full": 6, "redacted": 1, "withheld": 1, "none": 4},
  "outcomes": {"succeeded": 7, "notStarted": 4, "unknown": 0, "failed": 1},
  "semantic": {"available": 6, "unavailable": 0, "disabled": 4, "notRun": 2},
  "topReasons": [{"value": "sensitivity_threshold", "count": 2}],
  "topFindings": [{"value": "email", "count": 1}],
  "dispatch": {"documents.read": 5},
  "dispatchByDecision": {"allow": 5},
  "latency": {"total": {"n": 12, "p50": 21, "p95": 63, "max": 104}},
  "events": 118,
  "lastEventAt": "…Z",
  "budget": {"scope": "global-daily", "period": "2026-10-03", "periodKind": "utc_day",
             "limitTokens": 40000, "usedTokens": 10, "reservedTokens": 0,
             "remainingTokens": 39990, "availableTokens": 39990, "overLimit": false,
             "overdraftTokens": 0, "unknownUsageCount": 0,
             "label": "Current shared budget (UTC day, all callers)"},
  "release": {…},
  "semanticMode": "baseline",
  "storage": {"repository": "postgres"},
  "runtime": {…},
  "methodNotes": {"latency": "…", "blockedShare": "…", "window": "…"},
  "scope": "bench"
}
```

* Every counter, every dispatch figure and the latency sample use the same bounds. Per-principal
  scope is a filter on the same window, not a second window.
* `latency.total` is the whole invocation. Percentiles are nearest-rank, computed the same way in
  memory and in PostgreSQL from the actual sample, because two backends reporting different numbers
  for one dataset is a defect. An empty window reports `{"n": 0, "p50": null, "p95": null, "max": null}`.
* `blocked` counts **input decisions**. It is not a detection rate and the response says so in
  `methodNotes`. A detection rate needs a labelled dataset, which is the evaluation report's job.
* `dispatch` counts durable effects in the same window; `dispatchByDecision` joins them to the
  invocation decision that produced them.
* An agent's response additionally carries `ownInvocations` and `ownOutcomes` for its own rows while
  the shared ledger stays visible and clearly labelled as shared.

## `GET /v1/invocations`

| Parameter | Meaning |
|---|---|
| `limit` | 1–200, default 50 |
| `cursor` | opaque cursor from a previous page |
| `decision` | `allow`, `redact` or `block` |
| `outcome` | `succeeded`, `not_started`, `unknown` or `failed` |
| `service`, `action` | exact match |
| `dryRun` | `true` or `false` |

```json
{"invocations": [{"invocationId": "…", "principalId": "agent-local", "principalRole": "agent",
                  "service": "document-desk", "action": "documents.read", "decision": "allow",
                  "actionOutcome": "succeeded", "disclosure": "redacted", "reasons": [],
                  "findings": ["email"], "semanticStatus": "available", "dryRun": false,
                  "latencyMs": 21, "budgetScope": "global-daily", "release": "…",
                  "createdAt": "…Z"}],
 "nextCursor": "…", "truncated": true,
 "window": {"since": "…Z", "until": "…Z"}, "scope": "own", "filters": {"…": "…"}}
```

Response bodies are **not** in a list page; a trace is loaded one invocation at a time. The cursor is
opaque, bound to the window and filters it was issued for, and pages a stable window without skipping
or repeating a row.

## `GET /v1/invocations/{id}`

Returns the invocation metadata, the stored response — the *disclosed* result, never raw untrusted
input — and the ordered audit events. An invocation that belongs to another principal is reported as
`404 not_found`, not `403`: an agent must not be able to probe which invocation ids exist.

## `GET /v1/audit/export` and `/v1/audit/events`

| Parameter | Meaning |
|---|---|
| `limit` | 1–1000, default 200 |
| `kind` | audit event kind |
| `cursor` | opaque cursor from a previous page |

`/v1/audit/export` returns `application/x-ndjson` with the next cursor and the truncation flag in
headers, so a client can page deterministically:

| Header | Meaning |
|---|---|
| `X-Action-Gate-Next-Cursor` | pass back as `cursor`; empty when the window is exhausted |
| `X-Action-Gate-Truncated` | `true` when more events exist in this window |
| `X-Action-Gate-Window-Since`, `X-Action-Gate-Window-Until` | the window the page belongs to |

Records are the sanitized audit schema: `invocation_id`, `seq`, `kind`, `decision`, `reasons`,
`findings`, `detail`, `created_at`. Raw untrusted text never appears, and a direct repository write
cannot bypass the sanitizer.

## Unified operator reporting (2026-10-04)

`GET /v1/report` accepts the same window parameters and enforces the same caller ownership as
summary. It returns one content-free record per operation across `panel`, `mcp`, `model`, and
`legacy`, plus `total`, `bySource`, `decisions`, and `byAgentModel`. `/v1/summary` includes this
representation as `unified`; its older top-level counters remain legacy/model counters.
The workbench labels both scopes. The control panel's **Unified report** supports period selection,
ID/agent/target search, operation metadata including MCP receipt IDs, and security export.

Existing `/v1/audit/events` and `/v1/audit/export` now merge legacy audit rows with one
`panel_outcome` or `mcp_outcome` snapshot per durable operation, including pre-upgrade records.
Supplemental event IDs are source-prefixed; `invocation_id` preserves the original request or
operation ID. Window/filter-bound cursors paginate the merged stream. These snapshots do not
pretend to be a complete MCP transition history. Raw arguments and result documents are excluded.

Synthetic admission estimates and provider-reported model tokens are separate columns; absent
model usage is explicit. Neither is presented as a currency invoice. Outcomes can change during
reconciliation; reports are current read snapshots, not a transaction spanning all three stores.
The local implementation materializes the requested window for merging; high-volume reporting
and concurrent pagination under writes have not been load-tested. Stored window comparisons
include both boundaries (`since <= created_at <= until`), matching both repository backends.
