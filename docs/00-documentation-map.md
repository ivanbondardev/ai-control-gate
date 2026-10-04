# Action Gate documentation map

Updated after cleanup on 2026-10-04. The workspace holds 50 documentation files: 45 Markdown, 2 PDF, 2 JSON indexes and 1 log. The initial inventory covered 46 files; the map, the cleanup report, the pitch index and the archive of the previous judging have been added.

Three pitch drafts have been moved to a dated archive; the working references have been updated. The status "keep" denotes the document's role, not a fresh runtime confirmation. Completed C01–C10 are in the [cleanup report](09-documentation-cleanup.md).

Staging deployment preparation: [SSH deployment runbook](staging.md) (added after the inventory below).

## Reading order

1. [Main README](../README.md) → [working rules](../AGENTS.md) → [transfer boundaries](transfer.md).
2. For development: [application README](../app/README.md) → [contracts](../app/contracts/README.md) → the relevant code and tests.
3. For checks: [scenario client](../scripts/gate-scenarios/README.md) → [scenario matrix](23-bash-scenario-matrix.md). The matrix separates the scenario description, the historical evidence and the check on this copy.
4. For the competition: [primary source registry](../sources/goldman-task/_inbox/README.md) → [extracts](../sources/goldman-task/extracted/README.md) → [criteria](05-judging.md) → [questions](07-open-questions.md). Do not take the historical product assessment for the current one.
5. To continue the work: [decisions](01-decision.md), [log](08-session-log.md), [operator scenarios](25-gate-operator-scenarios.md).

## How to treat sources

- Competition requirements: the original PDFs and the English extracts; the Ukrainian translations are auxiliary. Discrepancies in deadlines and weights remain in the questions log. In this review the PDFs were not re-extracted and the translations were not re-verified.
- Implementation: the code and tests of the relevant path; the contracts describe the expected behaviour. In this session the runtime was not started.
- Reports in `sources/`: evidence of specific previous runs. They do not attest to the operability of the new environment.
- Scenarios and pitch: desired behaviour or historical drafts; the status is stated for each document.

## Full registry after cleanup

### Entry point and provenance

| File | Purpose | Status / action |
|---|---|---|
| [README.md](../README.md) | Main entry, run, copy boundaries | Keep |
| [AGENTS.md](../AGENTS.md) | Working rules in the workspace | Keep |
| [CHANGELOG.md](../CHANGELOG.md) | Release history 0.0.1–0.2.0 | History; do not rewrite |
| [TRANSFER-MANIFEST.json](../TRANSFER-MANIFEST.json) | SHA-256 of the initial transfer composition | Provenance evidence |
| [docs/transfer.md](transfer.md) | Copy composition, exclusions and transfer checks | Provenance evidence |

### Project management and scenarios

| File | Purpose | Status / action |
|---|---|---|
| [docs/01-decision.md](01-decision.md) | Decision log | Append |
| [docs/07-open-questions.md](07-open-questions.md) | Open and closed questions | Update based on evidence |
| [docs/08-session-log.md](08-session-log.md) | Session log | Append only |
| [docs/05-judging.md](05-judging.md) | Criteria and historical readiness assessment | Current criteria; the old assessment is in the archive |
| [docs/23-bash-scenario-matrix.md](23-bash-scenario-matrix.md) | Mapping of requirements to scenarios | Evidence statuses reconciled |
| [docs/25-gate-operator-scenarios.md](25-gate-operator-scenarios.md) | Eight proposed operator processes | Proposals; keep |
| [docs/archive-references.json](archive-references.json) | Index of references to the excluded archive | Initial provenance snapshot |

### Technical documentation

| File | Purpose | Status / action |
|---|---|---|
| [app/README.md](../app/README.md) | Run, pipeline, MCP, limitations | Working reference |
| [app/docs/structure.md](../app/docs/structure.md) | Module map of the early 0.2.0 slice | Module map updated |
| [app/contracts/README.md](../app/contracts/README.md) | Index of HTTP and MCP contracts | Keep |
| [app/contracts/invocation.md](../app/contracts/invocation.md) | Protected invocation, idempotency, audit | Heading reconciled with the release |
| [app/contracts/configuration.md](../app/contracts/configuration.md) | Draft, compare, activate, rollback, bootstrap | Keep |
| [app/contracts/control-panel.md](../app/contracts/control-panel.md) | Panel, policy, audit and operator corrections | Keep |
| [app/contracts/reporting.md](../app/contracts/reporting.md) | Metrics, ownership, export, shared reporting | Keep |
| [app/contracts/mcp-protocol-profile.md](../app/contracts/mcp-protocol-profile.md) | Selected protocol and transport profile | Keep |
| [app/contracts/mcp-tool-contracts.md](../app/contracts/mcp-tool-contracts.md) | Catalogue and schemas of synthetic MCP tools | Keep |
| [app/contracts/mcp-operations.md](../app/contracts/mcp-operations.md) | Operations, retry, unknown, reset, evidence | Keep |
| [app/contracts/model-proxy.md](../app/contracts/model-proxy.md) | Responses proxy, budgets, SSE, settings | Keep |
| [app/migrations/README.md](../app/migrations/README.md) | Schema description and runner of the early release | Reconciled with the SQL and runner |
| [infra/postgres/init/README.md](../infra/postgres/init/README.md) | Initial PostgreSQL initialization | Reconciled with the SQL and runner |
| [scripts/gate-scenarios/README.md](../scripts/gate-scenarios/README.md) | Scenario client instructions and assertions | Evidence statuses reconciled |

### Implementation reports and evidence

| File | Purpose | Status / action |
|---|---|---|
| [sources/original-panel-integration-2026-10-03.md](../sources/original-panel-integration-2026-10-03.md) | Integration of the original panel | Dated report |
| [sources/mcp-fixes-2026-10-04.md](../sources/mcp-fixes-2026-10-04.md) | MCP fixes and operation recovery | Dated report |
| [sources/model-proxy-implementation-2026-10-04.md](../sources/model-proxy-implementation-2026-10-04.md) | Implementation and checks of the model proxy | Dated report |
| [sources/operator-fixes-2026-10-04.md](../sources/operator-fixes-2026-10-04.md) | Fixes UI-01–UI-06 | Dated report |
| [sources/openai-request-format-decision-2026-10-04.md](../sources/openai-request-format-decision-2026-10-04.md) | Origin of the model API format choice | Source of the decision |
| [sources/export-unit-tests.log](../sources/export-unit-tests.log) | Raw log of the copy checks | Keep as evidence |

### Competition sources and their analysis

| File | Purpose | Status / action |
|---|---|---|
| [sources/goldman-task/README.md](../sources/goldman-task/README.md) | Entry point to the task and rules for working with sources | Navigation updated |
| [sources/goldman-task/_inbox/README.md](../sources/goldman-task/_inbox/README.md) | Registry of received PDFs | Keep provenance |
| [sources/goldman-task/_inbox/CRIETRIA AI Control Layer.pdf](../sources/goldman-task/_inbox/CRIETRIA%20AI%20Control%20Layer.pdf) | Original task description | Primary PDF; keep |
| [sources/goldman-task/_inbox/RULES AI Control Layer.pdf](../sources/goldman-task/_inbox/RULES%20AI%20Control%20Layer.pdf) | Original competition rules | Primary PDF; keep |
| [sources/goldman-task/extracted/README.md](../sources/goldman-task/extracted/README.md) | Origin of the extracts and translations | Duplication removed |
| [sources/goldman-task/extracted/CRIETRIA AI Control Layer.md](../sources/goldman-task/extracted/CRIETRIA%20AI%20Control%20Layer.md) | English extract of the task description | Keep |
| [sources/goldman-task/extracted/CRIETRIA AI Control Layer.uk.md](../sources/goldman-task/extracted/CRIETRIA%20AI%20Control%20Layer.uk.md) | Unofficial Ukrainian translation of the task | Keep |
| [sources/goldman-task/extracted/RULES AI Control Layer.md](../sources/goldman-task/extracted/RULES%20AI%20Control%20Layer.md) | English extract of the rules | Keep |
| [sources/goldman-task/extracted/RULES AI Control Layer.uk.md](../sources/goldman-task/extracted/RULES%20AI%20Control%20Layer.uk.md) | Unofficial Ukrainian translation of the rules | Keep |
| [sources/goldman-task/notes/README.md](../sources/goldman-task/notes/README.md) | Analysis index and short summary | Wording clarified |
| [sources/goldman-task/notes/task-analysis-2026-10-03.md](../sources/goldman-task/notes/task-analysis-2026-10-03.md) | Requirements and comparison with the old prototype | Historical analysis; the boundary is marked |

### Historical pitch texts

| File | Purpose | Status / action |
|---|---|---|
| [pitch/archive/2026-10-03/demo-script.md](../pitch/archive/2026-10-03/demo-script.md) | Three-minute demo of the old prototype | Archived; not for submission |
| [pitch/archive/2026-10-03/pitch-lines.md](../pitch/archive/2026-10-03/pitch-lines.md) | Pitch variants and quotes | Archived; not for submission |
| [pitch/archive/2026-10-03/submission-outline.md](../pitch/archive/2026-10-03/submission-outline.md) | Old submission and slide plan | Archived; not for submission |

### Navigation documents and judging archive

| File | Purpose | Status / action |
|---|---|---|
| [docs/00-documentation-map.md](00-documentation-map.md) | Full registry and reading order | This map |
| [docs/09-documentation-cleanup.md](09-documentation-cleanup.md) | Execution report and initial candidates | C01–C10 completed |
| [pitch/README.md](../pitch/README.md) | Entry point to the historical pitch materials | Current navigation |
| [docs/archive/2026-10-03/judging.md](archive/2026-10-03/judging.md) | Previous assessment of the old prototype | History; not an assessment of the current copy |

## Scope boundaries and provenance

Regular workspace files were scanned, except `.git`; the external archive was not traversed. Code, SQL, configuration and fixtures are not counted as separate documents. Initial composition: 223 files, 46 documentation files, 652 786 bytes; there were no byte-identical duplicates among the documents, and 168 local Markdown links had existing targets.

All 221 records of the initial `TRANSFER-MANIFEST.json` matched SHA-256 before the documentation sessions. The manifest and `archive-references.json` (71 records from 16 files) remain initial snapshots, not up-to-date indexes after the editorial changes. In particular, the `pitch/*.md` paths in these JSON files now correspond to the `pitch/archive/2026-10-03/` archive; the old `docs/05-judging.md` is kept in the dated archive with corrected links.

The cleanup checks are in the [log](08-session-log.md). The local link check covers the existence of the file/directory, not anchors or external URLs. The PDFs and translations were not re-verified; the runtime was not started.
