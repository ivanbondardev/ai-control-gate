# 23 — Bash scenario matrix

**Fact of the dated report:** the proxy is implemented; selected historical runs are described in the [2026-10-04 report](../sources/model-proxy-implementation-2026-10-04.md). This is not a check of a new environment. The full set under all profiles is not confirmed.

**Source fact:** the organizers require hybrid protection, centralized policies, budgets, signatures, reporting and positive/negative automated checks; also live configuration changes and performance telemetry. [Primary text, §2–6](../sources/goldman-task/extracted/CRIETRIA%20AI%20Control%20Layer.md).
**Coverage proposal, high confidence:** the scenarios below are a concretization of these requirements and of the MCP plan, not new jury criteria. **Implementation fact:** client requests and assertions are prepared in the [Bash set](../scripts/gate-scenarios/README.md); a full live run is not confirmed; the statuses below distinguish individual historical results.

| Source requirement | Scenarios | Independent evidence |
|---|---|---|
| §3 AI integration | L01–L04, agent-loop | Real provider request ID, usage; two model hops and MCP receipt |
| §4.1 access and allowed models | A01–A04, M07–M11 | Transport identity; zero dispatch; scoped catalog |
| §4.2 deterministic controls | V01–V04, D01–D07 | Valid error; provider input sanitized; output/SSE sanitized |
| §2, §4.2 semantic controls | S01–S05, M13, agent-loop KB-INJECT-01 | Real detector; score/threshold, positive control S03 |
| §4.3 budgets | B01–B05, concurrent-budget | Atomic ledger; usage; time; unknown spend; no overspend |
| §4.4 historical attacks | X01–X04, P01–P03 | Feed version/hash; specific match; zero dispatch |
| §4.5 reporting | report.sh + every case | Correlation, sanitized audit, management counters, scope/pagination |
| §4.6 self-testing | run.sh, assertions, existing suites | Mismatches yield FAIL; blocked/pending explicitly separated |
| §6 configuration change | D01→D02, P01→P02→P03 | Snapshot/generation, behavior change without restart |
| §6 performance | timing.tsv of every request | E2E latency; overhead requires server telemetry |
| §2 tool interaction | M01–M14, retry.sh | Service receipts, single effect, independent storage checks |
| §2 resilience | R01–R03, S05, existing recovery tests | Fail closed/unknown, recovery without duplication |
## Evidence status for each ID

Composition fact: [cases.json](../scripts/gate-scenarios/cases.json) contains 53 descriptions: 39 model and 14 MCP. The model IDs correspond to JSON fixtures in `requests/`; the MCP IDs correspond to invocation descriptions in cases.json. The presence of a description does not equal execution.

| IDs / scenario | Available implementation or contract | Historical evidence | Runtime check of this copy |
|---|---|---|---|
| L01–L04, A01–A04, V01–V03, D01, D03 | [Proxy](../app/contracts/model-proxy.md), [tests](../app/tests/test_model_proxy.py) | Client assertions per the proxy report; independent audit reconciliation only for the lines noted in the report | Not performed |
| V04, D02, D04–D07 | Validation and output controls in the proxy; D07 is an HTTP block before buffered SSE | The report has no live confirmation for these IDs | Not performed |
| S01–S05 | [Detector profiles](../app/action_gate/detectors.py); strict requires a separate AI profile | The quality of the real detector is not confirmed; the baseline does not substitute for it | Not performed |
| X01–X04, P01–P03 | Signature/config controls, [configuration](../app/contracts/configuration.md) | The live sequence of these IDs is not confirmed by the proxy report | Not performed |
| B01–B05, R01–R03 | Proxy budgets and refusals; [unit checks](../app/tests/test_model_proxy.py) | Unit coverage is not a live pass of the IDs | Not performed |
| M01–M14 | [MCP contracts](../app/contracts/mcp-tool-contracts.md), [acceptance](../app/tests/acceptance/mcp_acceptance.py) | [MCP fixes](../sources/mcp-fixes-2026-10-04.md) describe a separate suite; its phases are not automatically equated with these IDs | Not performed |
| agent-loop KB-1042 | [Client](../scripts/gate-scenarios/agent-loop.sh) | The proxy report confirms the OpenAI → MCP → OpenAI cycle and the audit of two model hops | Not performed |

For checks of this copy's files and fixtures see [transfer](transfer.md). `OBSERVED` means a client-side result requiring independent evidence, not an overall security PASS.

## Requests

**Expectation proposals:** the profiles must be prepared by the operator per the [instructions](../scripts/gate-scenarios/README.md); they are not activated by the scripts. Every row requires Gate evidence as given in `cases.json`.

| ID | Scenario | Profile | Client expectation |
|---|---|---|---|
| L01 | Ordinary allowed request | `baseline` | `response` |
| L02 | Ukrainian text without sensitive data | `baseline` | `response` |
| L03 | System instruction and history | `baseline` | `response` |
| L04 | Streaming response | `baseline` | `stream` |
| A01 | Missing authentication | `baseline` | `unauthorized` |
| A02 | Wrong local token | `baseline` | `unauthorized` |
| A03 | Attempt to spoof a role in the body | `baseline` | `invalid` |
| A04 | Forbidden model | `baseline` | `denied` |
| V01 | Invalid JSON | `baseline` | `invalid` |
| V02 | Wrong input type | `baseline` | `invalid` |
| V03 | Unknown request field | `baseline` | `invalid` |
| V04 | Body limit exceeded | `body-limit` | `too_large` |
| D01 | PII on input — redact | `pii-redact` | `clean` |
| D02 | PII on input — block | `pii-block` | `denied` |
| D03 | Synthetic secret on input | `secret-block` | `denied` |
| D04 | Sensitive content on output | `output-redact` | `clean` |
| D05 | Sensitive content in SSE | `output-redact` | `stream_clean` |
| D06 | Blocking sensitive output | `output-block` | `denied` |
| D07 | Blocking sensitive output in SSE | `output-block` | `stream_block` |
| S01 | Direct prompt injection | `semantic-strict` | `denied` |
| S02 | Paraphrased prompt injection | `semantic-strict` | `denied` |
| S03 | Safe discussion of attacks | `semantic-strict` | `response` |
| S04 | Indirect hostile text in a document | `semantic-strict` | `denied` |
| S05 | Unavailable semantic detector | `semantic-unavailable` | `unavailable` |
| X01 | Unsafe deserialization | `signature-feed` | `denied` |
| X02 | Shell execution | `signature-feed` | `denied` |
| X03 | Supply-chain signature | `signature-feed` | `denied` |
| X04 | Control safe text | `signature-feed` | `response` |
| B01 | Exhausted token budget | `budget-zero` | `limited` |
| B02 | max_output_tokens limit | `output-cap` | `limited` |
| B03 | Exhausted time budget | `deadline-zero` | `deadline` |
| B04 | Monetary budget | `money-zero` | `limited` |
| B05 | Rate limit | `rate-exhausted` | `limited` |
| R01 | Real provider unavailable | `provider-unavailable` | `unavailable` |
| R02 | Missing server provider key | `provider-key-missing` | `unavailable` |
| R03 | Audit unavailable | `audit-unavailable` | `unavailable` |
| P01 | Signature before/after feed change | `feed-before` | `response` |
| P02 | Signature after activation | `feed-after` | `denied` |
| P03 | Signature after rollback | `feed-rollback` | `response` |
| M01 | Tool catalog | `mcp-baseline` | `mcp_catalog` |
| M02 | Document read | `mcp-baseline` | `mcp_success` |
| M03 | Document search | `mcp-baseline` | `mcp_success` |
| M04 | Protected document — write refusal | `mcp-baseline` | `mcp_denied` |
| M05 | Internal recipient — local storage | `mcp-baseline` | `mcp_success` |
| M06 | External recipient — refusal | `mcp-baseline` | `mcp_denied` |
| M07 | Observer — filtered catalog | `mcp-baseline` | `mcp_catalog_readonly` |
| M08 | Observer — hidden write | `mcp-baseline` | `mcp_hidden` |
| M09 | Observer — restricted document | `mcp-baseline` | `mcp_denied` |
| M10 | Unknown tool | `mcp-baseline` | `mcp_hidden` |
| M11 | Mutation without operation key | `mcp-baseline` | `mcp_invalid` |
| M12 | PII in a document | `mcp-baseline` | `mcp_redacted` |
| M13 | Prompt injection in a document | `mcp-semantic-strict` | `mcp_denied` |
| M14 | Ticket creation | `mcp-baseline` | `mcp_success` |

## Boundaries and additional checks

**Fact of the current scope:** this set covers OpenAI Responses text/function/SSE and the local MCP services. Images/audio/files, hosted tools, remote OpenAI MCP, WebSocket, long-running Conversations and arbitrary providers are not implemented by these scripts. The task does not require every modality or every OpenAI API. Support for a local provider and its compute budget must be checked by a separate real local runtime; an OpenAI run does not prove it.

**Proposal, high confidence:** do not run all policy/fault cases under a single active policy. The preconditions are mutually exclusive, and a shared run without preparation would yield false conclusions.

| Planned scenario | Executable base / what remains |
|---|---|
| Ticket transitions, optimistic version conflict, ownership, hidden tools | Existing `make demo-mcp-test`, phases T/D/P; verify the actual report |
| Lost response → unknown → reconcile, fence, crash/reset | Existing `make demo-mcp-test` and recovery checks; isolated stack |
| Concurrent idempotency, zero extra effects | Existing R phases plus `retry.sh`; service counts mandatory |
| Schema drift / registry publish | Existing MCP suite; review_required does not equal a successful dispatch |
| Compare without dispatch, activation CAS, rollback | Existing config/integration suites; P scenarios for the live behavior of the model input |
| Invalid feed, unavailable DB/Redis | Isolated fault/integration tests; valid signatures in X do not check a malformed feed |
| Input/output time reserve, unknown provider usage, disconnect mid-SSE | There are [unit tests](../app/tests/test_model_proxy.py) and [HTTP tests](../app/tests/test_model_proxy_http.py); separate end-to-end evidence is needed. A client timeout does not prove cancellation |
| Request in-flight during activation | A controlled synchronization point and Gate trace are needed; the P sequence alone does not prove this |
| Policy output-block and redaction across SSE boundaries | D04/D05 define redaction checks; D06/D07 are output block. Per the [contract](../app/contracts/model-proxy.md), the full response is checked before SSE, and block returns an HTTP error before the stream; the live pass of these IDs is not confirmed |
| Ad-hoc judge prompt | Edit a copy of the L01 JSON and send it via `ad-hoc.sh`; do not present an unknown expected verdict as an automatic PASS |

**Unverified in the new environment:** live compatibility of the model proxy, validity of the provider key, available models, completeness of model/MCP audit correlation, semantic quality, performance and prices. This is a list of acceptance checks, not a readiness report.
