# Session log

## 2026-10-04 — initialization of the standalone directory

**Fact of the instruction:** the owner asked to prepare a copy for manual transfer.
**Done:** code and materials were copied selectively; README, AGENTS,
context and decisions were added. The composition and boundaries are in [transfer](transfer.md).
**Decision:** a new Compose project name, without transferring live state or keys.
**Unverified:** the new Docker run, browser and paid model scenarios.

**Checks:** 224 tests passed, 72 skipped; 14 assertion tests — OK;
53 fixtures valid; Compose, shell syntax and copy integrity were checked.
Details and boundaries are in [transfer](transfer.md).

## 2026-10-04 — documentation inventory and structure

**Fact of the instruction:** find and structure all the workspace documentation, prepare cleanup candidates.

**Done:** 46 documentation files were inventoried (41 Markdown, 2 PDF, 2 JSON indexes, 1 log) and grouped by purpose and status in the [documentation map](00-documentation-map.md). [10 groups of candidates](09-documentation-cleanup.md) were prepared: archiving three historical pitch drafts, updating outdated technical/competition summaries, removing duplication and clarifying navigation. A link from the README, a decision entry and a question about the invocation contract version were added.

**Decision:** structure the navigation in place. Do not delete or move existing documents as part of preparing candidates. Preserve the primary sources, translations, historical reports and the initial transfer manifest. All C01–C10 actions remain proposals.

**Checks:** before the changes, 221 records of the transfer manifest matched SHA-256; among the 46 documentation files there are no byte-identical duplicates; 168 initial local Markdown links have existing targets. The map contains exactly 46 unique rows and covers the entire initial documentation composition. After adding this entry, 277 local links in 43 Markdown files were checked: there are no missing targets. The code, configuration, scripts and sources are unchanged; the editorial changes to the initial files are limited to the README and three logs in docs/.

**Unverified:** anchors and external URLs, re-extraction of the PDFs and the accuracy of the translations, full correspondence of the contracts with the runtime, Docker/UI/integration and model checks. This is a documentation review with spot-checking of the code, not a new product readiness report.

## 2026-10-04 — documentation cleanup completed

**Fact of the instruction:** the owner approved the execution of the prepared cleanup list.

**Done:** C01–C10 executed, the result is the [report](09-documentation-cleanup.md). Three pitch drafts were moved to a dated archive with the text preserved and the links corrected; the previous judging is preserved separately. The module map, migrations, criteria, scenario statuses and navigation were updated. Duplicated extraction metadata was removed, the paid-subscription wording was clarified, and the invocation heading question was closed. The [map](00-documentation-map.md) now contains all 50 documentation files.

**Decision:** the historical materials are separated from the working references; the initial manifest and the archive references index were not rewritten. The code, configuration, data and product scope are unchanged.

**Checks:** all local Markdown links have existing targets; the 50 unique registry entries match the document composition exactly. All non-Markdown files were compared with the start of the session: unchanged. The SHA-256 of 16 preserved primary sources/historical files was checked separately (PDF, extracts, translations, reports, log, manifest, archive index, transfer and changelog). 53 scenario IDs were verified against cases.json: 39 for the model input, 14 MCP. `git diff --check` — no errors. Runtime tests were not run because the changes are documentation-only.

**Unverified:** anchors and external URLs, the runtime of the new stack, the UI, real model invocations, re-verification of the translations against the PDFs. Historical results were not relabelled as new PASS.

## 2026-10-04 — documentation translated into English

**Fact of the instruction:** the owner asked to translate all project documentation into English, including `sources/**` and the `*.uk.md` organizer-task files, and approved updating the language rule in `AGENTS.md`.

**Done:** 33 documentation files with Ukrainian prose were translated UK→EN in place; a further file (`infra/postgres/init/README.md`) was missed by the first pass and translated afterwards. Quoted Ukrainian phrases inside the English documents were rendered in English, marked as translated. The language rule in [AGENTS.md](../AGENTS.md) now states that documentation is in English. The `*.uk.md` files were made self-consistent: "unofficial English translation", `language: en`, `method: translation-to-en`, with the existing file names kept so that links and archive references keep working.

**Decision:** English is the documentation language of this workspace. Two categories stay in Ukrainian on purpose: the functional test fixtures `scripts/gate-scenarios/cases.json` and `scripts/gate-scenarios/requests/*.json` (the Ukrainian payloads are the test data for Ukrainian input handling), and the `archive reference` anchors that point at headings of archived files (`CHANGELOG.md`, `docs/archive-references.json`), where translating the fragment would break the reference. The organizers' PDFs and the exact English extractions were not altered.

**Checks:** every translated file was compared against the pre-translation copy for line count, headings, tables, code spans and link targets; the Markdown link check reports 0 broken links in 45 files, the same as before the translation. A full-repository Cyrillic scan is clean apart from the intentional cases above. Code, configuration, SQL, runtime and the Compose stack were not touched; no commits were made.

**Unverified:** the quality of the translation as judged by a native reviewer; anchors and external URLs; the runtime of the stack, the UI and real model invocations. The pre-translation originals are kept at `.translation-backup/uk-originals-2026-10-04.tar.gz` (not part of the documentation set).
