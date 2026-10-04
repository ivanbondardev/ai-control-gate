# Model proxy implementation — 2026-10-04

**Assignment fact:** after the review of the missing route, the owner assigned "implement it". Real requests to OpenAI with the provided server key and Bash clients from localhost had been directly assigned earlier. This allows real integration within this task; the key was not added to the code or fixtures. Previous review (archive reference: `model-proxy-check-2026-10-04.md`), [format and provider](openai-request-format-decision-2026-10-04.md).

**Implementation fact:** `POST http://localhost/v1/responses` forwards allowed requests to `https://api.openai.com/v1/responses`. Text, history, function calling, stateless reasoning continuation and buffered SSE are implemented. The key is read only by the server. Inbound/outbound controls, allowlist, atomic budget reservation, usage accounting and sanitized audit are performed at Gate. [Contract and boundaries](../app/contracts/model-proxy.md), [implementation](../app/action_gate/model_proxy.py).

**Activation fact:** the API image was rebuilt and launched while preserving data; `gpt-5-nano-2025-08-07` was added via panel compare/activate (version 16). There are no new comparison failures; the previous baseline mismatch `t10` was left explicitly marked. By a separate config compare/activate (generation 30) the time windows were increased: target 15000 ms, output 4000 ms, global 20000 ms; the daily limits were preserved. Model activation (archive reference: `../evidence/model-proxy-2026-10-04/activation.json`), time windows (archive reference: `../evidence/model-proxy-2026-10-04/deadline-activation.json`), [operator helper](../app/action_gate/model_proxy_setup.py).

## Checks

**Automated verification fact:** the final image passed 290 tests, including HTTP and real PostgreSQL. Log (archive reference: `../evidence/model-proxy-2026-10-04/final-tests.log`). Transport substitution is used only for isolated unit tests; runtime works with OpenAI.

**Live check fact:** from localhost the client assertions L01/L02/L03/L04, A01–A04, V01–V03, D01 and D03 passed; L02 and D01 — after fixes, not in the first run. The cycle OpenAI → MCP documents read → OpenAI also passed separately. The status `OBSERVED`/exit 3 means successful client assertions that require server-side evidence; it was not renamed to a full security confirmation.

| Selected check | HTTP | Real total_tokens OpenAI |
|---|---:|---:|
| L01, text | 200 | 168 |
| L02, history | 200 | 421 |
| L04, SSE | 200 | 133 |
| A04, forbidden model | 403 | no dispatch |
| D01, sanitization of synthetic PII | 200 | 907 |
| D03, blocking of a synthetic secret | 403 | no dispatch |
| Agent cycle, first call | 200 | 217 |
| Agent cycle, completion | 200 | 633 |

**Independent reconciliation fact:** for the eight rows of the table, the audit was obtained via `/v1/invocations/{id}` and matched against the client invocation IDs. Successful calls have provider request/response IDs, usage and a budget commit; A04/D03 have no dispatch. D01 has `inputRedacted=true` and different hashes of the input and forwarded payload. This is a processing audit, not a network capture; the sanitized outgoing payload was separately verified by a unit test. Matched evidence (archive reference: `../evidence/model-proxy-2026-10-04/verified-audit.json`).

Live artifacts: main run (archive reference: `../evidence/gate-scenarios/20261003T235931Z-54065-14928/`), L02 (archive reference: `../evidence/gate-scenarios/20261004T000339Z-55260-8039/L02/`), D01 (archive reference: `../evidence/gate-scenarios/20261004T000412Z-55411-24411/D01/`), D03 (archive reference: `../evidence/gate-scenarios/20261004T000418Z-55489-15069/D03/`), agent cycle (archive reference: `../evidence/gate-scenarios/20261004T000248Z-55003-20986/`).

**Fact of the issues found and fixed:** the real transport revealed the closing of the HTTP stream after the last Content-Length chunk; a regression test was added. A real reasoning item contains `content: []`; support and a test were added. 256 output tokens sometimes produced `incomplete`, so fixtures now have 1024 (budget B02 — 4096); the too-short target window was increased through the activation above. The previous failed artifacts were preserved. Timeout/unknown usage is accounted conservatively, not as a free call.

## Confirmation boundaries

**Current implementation fact:** a limited Responses profile is supported, not the entire OpenAI API; media, hosted tools, persistent context and Chat Completions are absent. SSE is emitted after the full response validation. The semantic detector by default remains marked baseline; real generation does not prove the quality of AI protection. The panel policy and the legacy config are fixed separately, not as one atomic release. The model allowlist is global for authenticated principals, without separate model grants. Cost in the budget is a configured conservative allowance, not an OpenAI tariff/bill. Crash reservations are held without automatic reconcile. Encrypted reasoning is opaque to content checks. Details are in the [contract](../app/contracts/model-proxy.md).

**Unverified:** all 53 scenarios under all the required policy profiles, full protection quality, load and production readiness. The described live checks do not replace these checks.
