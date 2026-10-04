# Operator panel fixes — 2026-10-04

**Assignment fact:** the owner asked to read the manual report in full (archive reference: `operator-manual-report-2026-10-04.md`) and implement all the fixes. The scope of this session is the six defects UI-01–UI-06 from the report's table. The product boundaries described there (new principals, MCP delete, external signature feed, production RBAC) were not turned into additional assignments.

## Implementation and evidence

The results below are **facts of implementation and verification**, not an assessment of full product readiness.

| Defect | Fix | Check |
|---|---|---|
| UI-01 | An unchanged refresh preserves the references to the draft/tests objects used by the form handlers. An external change redraws the corresponding editor | Browser: refresh → Secrets Block, token limit 1, Who, Name/Type → server-side save |
| UI-02 | Compare evaluates UTF-8 input tokens the same way as invoke; it takes fixture counters into account. New events store evaluationContext, Save as test case carries it into the fixture. There is a tokens already used field | Limit 1: live policy Allow → candidate Throttle; after activation Throttle. A separate regression reproduces 1 000 000 tokens already used without consuming live counters |
| UI-03 | not_started does not show processed as a received payload; content-only input explicitly marks the absence of model dispatch | Browser screenshot Throttle (archive reference: `operator-fixes-2026-10-04/browser/08-throttle-no-received-payload.png`): nothing received, not_started, Dispatched No |
| UI-04 | Unified report in the panel: the same window for panel/MCP/model/legacy, search by ID/agent/target, metadata/receipts, NDJSON export. GET /v1/report and summary.unified use the same projection. The old audit endpoints include stored panel/MCP operations | Reconciliation (archive reference: `operator-fixes-2026-10-04/verification.json`): all 42 panel IDs and 5 MCP IDs from the report were found in summary and export. Ownership, filters, pagination without duplicates and cursor binding to the window/filter were verified |
| UI-05 | Requests search includes the full request ID | Browser: an ID search finds the required event |
| UI-06 | An exception is case-insensitive equality of the whole text, not contains; the UI suggests the full text and explains the rule | Exact training phrase Allow; phrase + appended attack Block; other checks are not disabled |

**Verification fact:** 296 automated tests: 275 unit/HTTP + 21 PostgreSQL (archive reference: `operator-fixes-2026-10-04/unit-http.log`), 21 PostgreSQL tests (archive reference: `operator-fixes-2026-10-04/postgres.log`), 58 browser checks (archive reference: `operator-fixes-2026-10-04/browser.log`) — OK. The PostgreSQL suite creates a separate scratch database; the browser worked with a clean memory backend. The browser's test activations did not change the policy of the main demo stack.

**Fact of verifying historical data:** the daily summary (archive reference: `operator-fixes-2026-10-04/report-day/management/response.body`) contains 434 operations: 42 panel, 361 MCP, 15 model, 16 legacy. The full export of the same window contains 697 audit rows: the number of audit rows does not equal the number of operations. The window `2026-10-03T22:00Z`—`2026-10-04T22:00Z` corresponds to the original QA; its end was in the future, so this is a snapshot at the time of reading, not a total for a completed day. The first 15-minute report did not contain the old QA events; the reconciliation was repeated in the correct daily window.

**State fact:** the local `api` and `gate-mcp` were updated. State (archive reference: `operator-fixes-2026-10-04/runtime-state.json`): policy v21, draft = live, 43 panel events in total, 7 synthetic effects. The policy SHA-256 matches the stored state after the previous QA. Data and history were not reset. No new paid model calls were made.

## Boundaries

- **Contract fact:** existing `exceptions[].match` are now treated as the full text. An old short contains exception may stop passing a longer request; this is an intentional narrowing of the exception.
- **Contract fact:** compare is independent fixtures with a fixed context. It does not predict future load. Old events without evaluationContext do not get invented historical counters.
- **Contract fact:** synthetic estimated tokens and provider reported tokens are shown separately per agent/model; missing usage is marked. This is not a provider monetary invoice.
- **Contract fact:** audit adds one outcome snapshot per panel/MCP operation, not the full history of MCP transitions. Receipt IDs are available for investigation; no new reconcile/fence workflow was added via the UI.
- **Unverified:** load, paging under concurrent writes, production RBAC, trained semantic quality, new injected unknown/reconcile. The current merger loads the records of the selected window into memory; results from different stores are not a single transactional snapshot.

Code: [panel.js](../app/static/control/panel.js), [panel service](../app/action_gate/panel_service.py), [engine](../app/action_gate/panel_engine.py), [unified reporting](../app/action_gate/operator_reporting.py). The contracts were updated in [control panel](../app/contracts/control-panel.md) and [reporting](../app/contracts/reporting.md).
