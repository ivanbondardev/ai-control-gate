# Bash scenarios for Action Gate

**Suite implementation fact:** 53 scenario descriptions in `cases.json`, 39 OpenAI Responses JSON templates, a Bash transport via `curl`, separate scripts for the agent loop, retry, concurrent budget and reporting export. This is a client test suite; it does not implement the model proxy.

**Owner decision fact:** the format and the real provider are OpenAI by default; we do not create an LLM emulator. [Instruction](../../sources/openai-request-format-decision-2026-10-04.md). The provider key is configured **on the Gate**; client scripts neither read it nor forward it. `GATE_TOKEN` is a separate client identity; by default a staging token from the ignored client registry is used.

**Implementation fact:** `/v1/responses` supports a limited OpenAI Responses profile, function calling and buffered SSE. [Contract](../../app/contracts/model-proxy.md), [live evidence and boundaries](../../sources/model-proxy-implementation-2026-10-04.md). The full set of 53 scenarios under all policy profiles has not yet been confirmed.

The status of each ID, historical results and the boundaries of the copy check are summarized in the [matrix](../../docs/23-bash-scenario-matrix.md). The current document describes the run and assertions.

## Running from a local terminal

**Implementation fact:** the scripts run on your computer, outside containers. The default address is `https://ai-control-gate.ivbon.dev`. For the local demo, explicitly set `GATE_BASE_URL=http://localhost`; `http://127.0.0.1` is also supported. Requests to loopback bypass the system HTTP proxy. Docker is needed for the server stack, but the client scripts do not call Docker and do not require `docker exec`.

```bash
# Run from the repository root; sync Gate tokens once or after token rotation.
./scripts/gate-scenarios/sync-staging-auth.sh
./scripts/gate-scenarios/preflight.sh
./scripts/gate-scenarios/run.sh --case M02

# If the server port is changed to 8080:
GATE_BASE_URL=http://localhost:8080 ./scripts/gate-scenarios/preflight.sh

# Can be run from any working directory:
./scripts/gate-scenarios/run.sh --list
```

**Prerequisite:** the selected server stack is already running. Staging client credentials are stored in `secrets/staging-client/principals.json` (gitignored, mode 600). Only the exact staging HTTPS origin can use this registry automatically. No provider credentials are downloaded. `GATE_BASE_URL` changes only the client address, not the server port. MCP requires running MCP services and a published catalog. The model route `/v1/responses` is implemented; the OpenAI key and the allowed model are configured on the server.

## Scenario commands

Bash 3.2+, curl with `--header @file` support and Python 3.9+ are required. `jq`, the OpenAI SDK and package installation are not needed.

```bash
./scripts/gate-scenarios/run.sh --list
./scripts/gate-scenarios/run.sh --check
./scripts/gate-scenarios/preflight.sh

# Substitute the model allowed by the Gate policy and available to the provider account.
export OPENAI_MODEL=gpt-5-nano-2025-08-07
./scripts/gate-scenarios/run.sh --case L01
./scripts/gate-scenarios/run.sh --profile baseline

# MCP must be published and have a corresponding policy.
./scripts/gate-scenarios/run.sh --case M02
OPENAI_REASONING_EFFORT=minimal ./scripts/gate-scenarios/agent-loop.sh KB-1042
./scripts/gate-scenarios/retry.sh
./scripts/gate-scenarios/report.sh

# Arbitrary judge request; put the real model ID in the JSON.
./scripts/gate-scenarios/ad-hoc.sh /path/to/request.json
```

**Script behavior fact:** `--check` and the validator tests do not call the network. `preflight.sh` only reads readiness and identity; it does not check the OpenAI key. Running a model scenario may spend real provider money. The scripts perform no automatic retries, redirects or infinite loops. The model is not silently selected by the semantic detector profile.

| Variable | Purpose |
|---|---|
| `GATE_BASE_URL` | Default `https://ai-control-gate.ivbon.dev`; the Gate root without `/v1` |
| `OPENAI_MODEL` | The real allowed model for generation; required for model scenarios, except malformed JSON |
| `GATE_PRINCIPAL` | Default `support-agent` |
| `GATE_TOKEN` | The token of this principal; if absent — the staging client registry, or synthetic registry for explicit localhost |
| `RESULT_DIR` | A new, empty evidence directory; by default in the gitignored `evidence/gate-scenarios/…` |
| `REQUEST_TIMEOUT_SECONDS` | Client timeout, default 60 s; this is not evidence of the server time budget |
| `REPORT_PRINCIPAL` | Default `operator-local`; for own-scope `support-agent` is also possible |
| `REPORT_SINCE`, `REPORT_UNTIL` | ISO-8601 with a time zone; by default the previous 15 minutes |

When a non-standard token for the reporting principal is needed, set `GATE_PRINCIPAL=operator-local GATE_TOKEN=… REPORT_PRINCIPAL=operator-local` together. Do not write the token into shell history: pass it through your session environment/secret manager. The provider API key stays on the server.

## How to read the result

| Result / exit | Meaning |
|---|---|
| `--check`: 0 | The JSON files and the suite metadata are structurally valid; this is not an OpenAI check |
| `preflight`: 0 | Readiness and the caller endpoint are available; the model route has not been checked |
| `FAIL`: 1 | The actual response contradicts the client expectation |
| `BLOCKED`: 2 | There is no prerequisite, route or transport; there is no conclusion about a guardrail |
| `OBSERVED`: 3 | Client assertions passed, independent Gate/service evidence is required |

**Deliberate scope:** the suite does not return a general "all protection PASS" based only on an HTTP response. A model refusal in an HTTP 200 response is not counted as blocking by the gate. The absence of PII in the response does not prove that PII did not go to OpenAI. A final conclusion requires correlation with the audit, ledger and independent receipts. `summary.json` always explicitly has `security_verified: false`.

Planned model-input refusals: auth 401; invalid 400/422; policy 403; body size 413; limits 429; dependency 502/503; deadline 408/504. A JSON `error` object with `message` is expected. 404/405 means a missing/unsuitable route. Codes may be changed only together with an agreed contract, not to hide an implementation error.

**Implementation fact:** each attempt stores the request, response, headers, curl status and timing (`http_code`, `time_total`, `time_starttransfer`, `size_download`), and the main runner — `result.json` and a summary. Files are created with `umask 077`; authentication headers — in a temporary directory that is deleted. Requests contain only synthetic data. Do not use this directory for real client secrets or PII. Responses are not printed automatically to the console.

## Policy prerequisites

**Acceptance profile proposals, high confidence:** these are names of test prerequisites, **not** already established policy IDs. The runner does not create or activate them. Before running `--profile NAME` or an individual case, prepare an isolated policy in the panel/operator API and record its version. Do not disable production dependencies for a test.

| Profile | What to prepare |
|---|---|
| `baseline` | An allowed `OPENAI_MODEL`, sufficient budget, a working real OpenAI; sensitive controls must not block neutral text |
| `body-limit` | Request body limit below 1 200 000 bytes, a check before external calls |
| `pii-redact` / `pii-block` | Identical PII detectors; a redact or block action; redact is performed before every external model call |
| `secret-block` | Blocking of a synthetic `sk-…` on input, before the external semantic/provider hop |
| `output-redact` | Output check, including all SSE deltas, against the email canary; a confirmed raw canary in the provider output |
| `output-block` | Sensitive upstream output is blocked with HTTP 403 before SSE: the proxy checks the full response before emitting the buffered stream. The D07 validator also allows a terminal error, but that branch does not describe the current proxy |
| `semantic-strict` | A real AI detector, with a recorded model/instruction version/threshold; the S03 positive control is also mandatory |
| `semantic-unavailable` | A mandatory detector is unavailable in the isolated stack; fail closed without target dispatch |
| `signature-feed` | The active feed contains `pickle.loads(`, `os.system(` and the synthetic marker `GATE_TEST_UNTRUSTED_MODEL_LOADER_V1`; record hash/version |
| `budget-zero` | Zero available tokens; a reservation is impossible before a paid call |
| `output-cap` | A hard refusal for `max_output_tokens: 4096`; the cap is below 4096. If the product chooses clamp, a different agreed assertion is needed |
| `deadline-zero` | The server deadline is exhausted before dispatch; do not substitute the client curl timeout |
| `money-zero` | The ledger/cap is configured; zero allowance. The configured costMicroPerToken is an internal estimate, not a provider tariff or invoice |
| `rate-exhausted` | The rate limit window for the test caller is already exhausted without a paid flood |
| `provider-unavailable` | The network path to the real OpenAI is blocked in the test stack; no LLM stub is used |
| `provider-key-missing` | The key is missing only in the isolated configuration; do not change the real stored key |
| `audit-unavailable` | The durable audit storage of the isolated stack is unavailable; behavior before/after dispatch is distinguished by evidence |
| `feed-before` / `feed-after` / `feed-rollback` | The marker `GATE_TEST_LIVE_FEED_V1` is first absent, then added and activated, then rolled back with a new generation |
| `mcp-baseline` | A published MCP catalog, principals, baseline per [MCP tool contracts](../../app/contracts/mcp-tool-contracts.md): internal Outbox allowed, external forbidden, KB-9000 protected |
| `mcp-semantic-strict` | MCP output passes a real semantic check; KB-INJECT-01 is blocked |

**Claim boundary:** X01–X03 check the transmission and application of specific signatures. They do not prove coverage of all exploit variants, CVEs or supply-chain attacks. Semantic expectations are proposed labels, not measured accuracy; variability of a real model may cause a FAIL, which we do not hide by repeating until success.

## Sequences

**Rehearsal order proposal:** L01 → A01/A02 → D01/D02 → S01/S03 → X01/X04 → B01 → M02/M04/M06 → agent loop → report. Run profiles after preparing the corresponding policy. `--profile baseline` also includes negative auth/schema/model cases with basic prerequisites, so it is not one cheap smoke request; use L01 for smoke.

- **Threshold change:** D01 under `pii-redact`, then D02 under `pii-block`; confirm different active versions, retention of the previous snapshot in an in-flight request and independent dispatch counts.
- **Live feed:** P01, feed change/activation, P02, rollback, P03; the same prompt, new invocations. An application restart should not be required.
- **Agent loop:** `agent-loop.sh KB-1042`; at most two model requests and one MCP read. The received `function_call` is checked against the allowlist; the tool response and all model output items are returned with the correct `call_id`. An unknown tool or arguments are not executed. Additional variants — `KB-PII-01` and `KB-INJECT-01`. The model may receive a tool refusal; this is also a real result that is passed to it.
- **Mutation retry:** `retry.sh`; the same key and body, then the same key with a changed body. An independent Outbox count is required: exactly one effect. The idempotency of this MCP extension is not attributed to OpenAI Responses.
- **Concurrent budget:** `concurrent-budget.sh`; before running, set the balance sufficient for exactly one L01 reservation (including the semantic/output reserve), and stop execution by other callers. Two parallel requests, expected 200+429. The ledger must prove the absence of overspend; the codes alone do not prove this.
- **Reporting:** `report.sh`; the same time window for the summary and all audit pages. Separately repeat from `support-agent` and make sure there are no foreign entries. Model calls have an invocation ID and sanitized audit; the surfaces and scope are described in the [reporting contract](../../app/contracts/reporting.md). Check the actual correlation, not just a successful export.

## Evidence that must be added from the Gate side

**Acceptance checklist proposal, high confidence:** for each control case, record the correlation client request → Gate invocation → provider request/MCP operation, principal, policy release/generation, feed hash, decision/reasons and semantic status. For block — the absence of the corresponding dispatch; for redact — verification of the sanitized payload at the network boundary, including the semantic provider; for output-redact — the raw upstream actually contained the canary. Store raw payloads only for these synthetic fixtures, and do not export keys or Authorization.

For budget cases, used/reserved/remaining before and after are needed, target and semantic usage separately, and accounting of unknown usage after a timeout. For mutations — a service receipt and independent state. For performance — separate the Gate overhead and the OpenAI latency; curl `time_total` is only an end-to-end measurement and does not prove the proxy overhead. The current suite does not fake this evidence or generate a "successful" sidecar instead of it.

## Additional planned scenarios and the existing acceptance suite

The [coverage matrix](../../docs/23-bash-scenario-matrix.md) links this suite to the sections of the organizers' task. For lifecycle/container-managed failures, use the existing `make demo-mcp-test`: it runs an isolated Compose project by default. Do not substitute it with a single curl. Do not set `DEMO_MCP_TEST_IN_PLACE=1` for a normal rehearsal.

Before submission, the following must be closed separately: reset/reconcile/fence, crash recovery, version conflicts, resource ownership, schema drift, compare/activation CAS, rollback, audit sanitization/pagination/own-scope, invalid feed, Redis/DB failure. The presence of a scenario/test code does not mean it passes in the current state.

## Checking the suite itself

### Manual panel operator scenarios

**Implementation fact:** `operator-panel.sh` complements the browser check with staging or local
synthetic invocations of `/v1/panel/invoke`. It does not call OpenAI and does not change
policies. The policy is prepared in the browser. The results of this run and the
boundaries — the operator report (archive reference: `../../sources/operator-manual-report-2026-10-04.md`).

```bash
# RESULT_DIR must be new or empty.
RESULT_DIR=/tmp/operator-panel-new bash scripts/gate-scenarios/operator-panel.sh suite
RESULT_DIR=/tmp/operator-panel-pair OPERATOR_CASES=false-positive,injection,exception-reuse \
  bash scripts/gate-scenarios/operator-panel.sh suite
RESULT_DIR=/tmp/operator-panel-state bash scripts/gate-scenarios/operator-panel.sh state
```

**Boundary:** the suite requires an imported `qa_operator_documents` for the qa-* fixtures;
without it, select the existing cases via `OPERATOR_CASES`. Exit 0 means a successful
HTTP transport, not a security verdict. Compare `policy.version`, `r.decision`,
`action.dispatched`, `action.outcome` and `output.disclosure` with the specific policy.
State snapshots before/after and separate request/response/timing are created for each case.

```bash
for file in scripts/gate-scenarios/*.sh; do bash -n "$file"; done
python3 -m unittest discover -s scripts/gate-scenarios -p test_assertions.py
./scripts/gate-scenarios/run.sh --check
```

**Boundary:** the local unit tests check the validator on short synthetic JSON objects. This is not an HTTP service, not a generation fallback and not a provider emulation in the demo.

**Configuration fact of the verified run:** the fixtures use up to 1024 output tokens (B02 — 4096). `OPENAI_REASONING_EFFORT` optionally sets the effort for the agent loop; `minimal` was verified with the referenced nano model. Other models may need other values. The initial activation of the model and time windows is described in the [contract](../../app/contracts/model-proxy.md#operator-setup-and-verification).
