# Action Gate documentation cleanup

Completed 2026-10-04 at the owner's direct instruction "OK. do the cleanup" (translated from the owner's Ukrainian wording). The [documentation map](00-documentation-map.md) reflects the result.

## Changes made

| Candidate | Result |
|---|---|
| C01 | Three pitch drafts moved to `pitch/archive/2026-10-03/`, an English-language index added, links adjusted |
| C02 | Working judging focused on criteria and evidence; the previous text preserved in `docs/archive/2026-10-03/judging.md` |
| C03 | Rewrote the module map, separating legacy, panel, MCP and model proxy |
| C04 | Described all six migrations, the advisory lock and the separate Compose job; shortened the init README |
| C05 | Grouped the statuses of all 53 IDs by evidence; fixed the explanation of buffered SSE, reporting and the budget allowance |
| C06 | Updated the entry point to the competition sources; the historical analysis received an explicit cut-off boundary |
| C07 | Removed the duplicated extraction metadata block; kept the fuller version together with the translation |
| C08 | Clarified: the organizers do not provide paid subscriptions; the workspace spending rules remain in force |
| C09 | Distinguished the old and new logs; preserved the original JSON indexes; fixed the confirmed local MCP references |
| C10 | Aligned the invocation heading with release 0.2.0 per the explicit rule of the contracts index; the continuation route leads to local documents |

Code, configuration and runtime were not changed. The PDFs, English extracts, translations, five implementation reports/decisions, the test log and the original JSON indexes were preserved byte-for-byte. The archive Markdown has only editorial changes to relative links; the old judging received an archival caveat.

## Initial candidate review

The rationale from before the cleanup is preserved below. The words "proposal" and "prerequisites" (translated from Ukrainian) and the old defects described refer to that review; the current state is in the execution table above. The links point to the current paths. P1/P2 are editorial review priorities, not competition criteria.

## P1 Eliminate misleading pointers

### C01 Archive three historical pitch drafts

**Fact:** [demo-script.md](../pitch/archive/2026-10-03/demo-script.md), [pitch-lines.md](../pitch/archive/2026-10-03/pitch-lines.md), [submission-outline.md](../pitch/archive/2026-10-03/submission-outline.md) have historical caveats about the deleted prototype. The scenario contains unfilled N/X/Y/Z, and the pitch contains quantitative and product claims without evidence from the current copy. The [root README](../README.md) explicitly calls them inconsistent historical drafts. The commit `52f1d87` mentioned there concerns the old history; [transfer.md](transfer.md) reports that the old Git history was not transferred.

**Proposal, high confidence:** move all three together to `pitch/archive/2026-10-03/`, preserving the content; leave a short English-language index with status in `pitch/`. Prepare the new current pitch as a separate task based on the verified demo. The scope of archiving is 33,836 bytes; this is navigation cleanup, not disk savings.

**Prerequisites:** fix the incoming and outgoing relative links, including the links between the three files and from this map; do not turn historical promises into current ones. Deletion would lose wording and context, so it is not recommended.

### C02 Separate the criteria from the old product assessment

**Fact:** [docs/05-judging.md](05-judging.md) contains a useful criteria table but also the sentence "there has been no code in this directory since October 3, 2026" (translated from Ukrainian) and a section about the deleted implementation. The existing [app/README.md](../app/README.md) and [gateway code](../app/action_gate/gateway.py) confirm that code exists in this copy.

**Proposal, high confidence:** keep the criteria and the links to primary sources; move the old assessment and the jury answers into an explicitly dated historical block or archive. Add the current compliance matrix only with links to code and specific checks. Do not delete the file entirely: README and the open questions rely on it.

### C03 Update the module map

**Fact:** [app/docs/structure.md](../app/docs/structure.md) has the heading 0.2.0, but the tree starts with `hackyeah-2026/`, the VERSION line describes 0.1.0, and the list does not cover the new MCP, proxy and panel modules. The existing [model_proxy.py](../app/action_gate/model_proxy.py), [mcp_server.py](../app/action_gate/mcp_server.py), [panel_service.py](../app/action_gate/panel_service.py). The table also still states that there is no concurrent migration locking, whereas [migrate.py](../app/action_gate/migrate.py) calls `pg_advisory_lock`.

**Proposal, high confidence:** replace the tree and the boundary table with a current description of the modules; leave historical test counts in the respective reports. Do not merge different policy/runtime surfaces into one merely for diagram simplicity. Keep the file as a separate architecture reference.

### C04 Align the migration documentation with the code

**Fact:** [app/migrations/README.md](../app/migrations/README.md) describes only 0001–0002, the file-based policy source and the absence of runner locking. The directory contains 0001–0006; [0003_policy_lifecycle.sql](../app/migrations/0003_policy_lifecycle.sql) adds a snapshot and lifecycle in the DB, the [configuration contract](../app/contracts/configuration.md) defines files as bootstrap/import, and the [runner](../app/action_gate/migrate.py) has an advisory lock. [infra/postgres/init/README.md](../infra/postgres/init/README.md) still speaks of a future choice of runner.

**Proposal, high confidence:** make `app/migrations/README.md` the main description of all six migrations and the runner, and shorten the infrastructure README to the purpose of the init directory and a link to it. Keep the caveat about data and volumes. Do not change SQL and data as part of the documentation cleanup.

### C05 Align the scenario statuses

**Fact:** the [matrix](23-bash-scenario-matrix.md) and the [client README](../scripts/gate-scenarios/README.md) already refer to the implemented proxy, but below they retain future wording and unverified assumptions. In particular, the README calls output-block the "proposed contract of the new proxy" and speaks of the "future model proxy" (both translated from Ukrainian). The [proxy contract](../app/contracts/model-proxy.md) and the [reporting contract](../app/contracts/reporting.md) already describe the respective surfaces. This requires reconciling specific scenarios, not automatically replacing all statuses with PASS.

**Proposal, high confidence:** keep the "requirement → scenario → evidence" link in the matrices and the launch and assertions in the README. For each scenario, separate the presence of a fixture, the implementation of the contract, the historical run and the check of this copy. Derive statuses from the available evidence; plan new runtime runs separately. Keep both files: their roles differ.

### C06 Mark the competition task analysis as historical

**Fact:** [sources/goldman-task/README.md](../sources/goldman-task/README.md) calls the absence of `agent → model` the main gap of the prototype and writes that the extracted/notes directories "will appear", although they exist. [task-analysis-2026-10-03.md](../sources/goldman-task/notes/task-analysis-2026-10-03.md), in the section comparing with the prototype, describes the missing MCP and proxy at that time. This copy has the [MCP contract](../app/contracts/mcp-protocol-profile.md) and the [Responses contract](../app/contracts/model-proxy.md).

**Proposal, high confidence:** update the navigation README; in the dated analysis add a clear historical cut-off boundary with a link to the newer reports. Keep the analysis itself as evidence of the provenance of decisions; do not rewrite its conclusions about the old code retroactively. Do not reinterpret the requirements, deadline and weights during the cleanup.

### C08 Fix the overgeneralization about paid services

**Fact:** [notes/README.md](../sources/goldman-task/notes/README.md), in item 4, said "no paid services" (translated from the pre-cleanup Ukrainian wording). Instead, the [English extract CRIETRIA, section 7](../sources/goldman-task/extracted/CRIETRIA%20AI%20Control%20Layer.md) and the [detailed analysis](../sources/goldman-task/notes/task-analysis-2026-10-03.md) clarify: the organizers do not provide paid subscriptions; that in itself is not tantamount to a prohibition on use.

**Proposal, high confidence:** replace the short wording with an accurate paraphrase and a link to section 7. The separate rule of this workspace prohibiting spending without the owner's instruction remains in [AGENTS.md](../AGENTS.md). Do not settle the final interpretation of the competition constraints through editorial cleanup.

## P2 Remove duplication and clarify navigation

### C07 Remove the duplicated extraction instruction block

**Fact:** [extracted/README.md](../sources/goldman-task/extracted/README.md) twice contains the paragraph "Rule: one extracted file corresponds to one file" (translated from Ukrainian), the metadata example and the `ocr-uncertain` rule. The first version additionally covers `translation`.

**Proposal, high confidence:** keep the first, fuller block, delete the second duplicate. This is the smallest self-contained edit; the whole file is needed for the provenance of extracts and translations.

### C09 Preserve the archival index and distinguish the same-named logs

**Fact:** [archive-references.json](archive-references.json) contains 71 entries from 16 files. Some textual archive references name `08-session-log.md`, although the new copy also has a file with that name. According to [transfer.md](transfer.md), the common old log was not transferred, and the new [log](08-session-log.md) begins with the initialization of the copy.

**Proposal, high confidence:** do not automatically replace such references with the new log. In working navigation, explicitly distinguish the old and the new context; keep the index and manifest as provenance snapshots. **Medium confidence:** individual references can be made local, but only after verifying that they mean the new document. The same name is not enough.

### C10 Align the versions and the continuation route

**Fact:** [invocation.md](../app/contracts/invocation.md) begins with version 0.1.0, while the [contracts index](../app/contracts/README.md) presents gateway 0.2.0. [app/README.md](../app/README.md), in the Continue implementation section, begins the route with a handoff that remained in the archive. [CHANGELOG.md](../CHANGELOG.md) preserves the historical boundary 0.2.0, and newer facts are placed in `sources/`.

**Proposal, medium confidence:** determine whether 0.1.0 is a separate contract version or an outdated heading; do not change the number mechanically. In the README, give a route through the current local contracts, transfer and the new map. Keep the release history; do not announce a new release as part of this cleanup.

## What was excluded from the deletion candidates

- Both PDFs, the English extracts and the Ukrainian translations: different roles, not redundant copies. The spelling `CRIETRIA` is preserved from the primary source; do not rename it to fix the spelling.
- The five dated reports/decisions in `sources/`, the test log, transfer, the manifest: evidence with defined boundaries. An old report does not become garbage after new code appears.
- The decision, session and open-question logs: preserve history. Do not delete closed questions.
- Operator scenarios: marked as proposals; the absence of a full implementation is not a reason for deletion.
- READMEs at various levels: their presence alone does not mean duplication. Shorten only duplications while preserving the directory purpose and links.

## Proposed order of further work

**Proposal, high confidence:** first C04 and C02 (incorrect technical/product pointers), then C01, C03, C05, C06 and C08; then C07, C09, C10. After moves, check local links; after changes to technical descriptions, check consistency with the code mentioned. Do not update the original transfer manifest as if the new texts were part of the original copy.

**Unverified:** external URLs, the accuracy of all contracts with respect to runtime, a new Docker launch, the current UI, paid APIs, re-verification of the PDFs/translations. The contradictions found are based on local files and targeted reading of code; no full technical audit was conducted.
