# Decisions

## 2026-10-04 — separate project directory

**Fact of the owner's instruction:** create a directory with a copy of everything necessary;
the owner will move it manually into the new workspace.

**Decision within the scope of the instruction:** the current code was transferred with its structure preserved,
along with the infrastructure, scripts, the primary task and the selected context. The source of the composition is the
[transfer description](transfer.md). The direction and the product scope were not changed.

## 2026-10-04 — documentation navigation and cleanup candidates

**Fact of the instruction:** find and structure all the workspace documentation and prepare cleanup candidates.

**Decision within the scope of the instruction:** a [full map](00-documentation-map.md) and a [list of candidates](09-documentation-cleanup.md) were added; the map was included in the root README. The navigation was structured without moving or deleting existing files. Archiving, trimming and updating from the list are proposals, not approved product decisions. The initial transfer manifest is kept as a historical snapshot.

## 2026-10-04 — execution of the documentation cleanup

**Fact of the instruction:** the owner approved the execution of the prepared list: "OK. do the cleanup" (translated from the owner's Ukrainian wording).

**Decision and execution:** C01–C10 from the [report](09-documentation-cleanup.md) were implemented. The historical pitch drafts and the previous prototype assessment were separated from the working navigation. The primary sources, the evidence and the initial transfer indexes are preserved. The invocation contract heading was corrected to release scope 0.2.0 under the explicit rule of the contracts index; there is no new release or API change. The project direction and the submission decision were not changed.

## 2026-10-04 — English as the documentation language

**Fact of the instruction:** the owner asked to translate all project documentation into English, including `sources/**` and the `*.uk.md` organizer-task files, and approved updating the language rule.

**Decision:** documentation in this workspace is written in English, and the language rule in [AGENTS.md](../AGENTS.md) was updated to match. Notes, plans, the repository README, UI text, code comments, messages, pitch and submission texts are all in English; mentor questions are still prepared in Ukrainian and English. Ukrainian is kept only where it is functional rather than documentary: the test fixtures `scripts/gate-scenarios/cases.json` and `scripts/gate-scenarios/requests/*.json`, whose Ukrainian payloads exercise Ukrainian input handling, and the archived-heading anchors in `CHANGELOG.md` and `docs/archive-references.json`.

**Boundaries:** the organizers' PDFs and the exact English extractions were not altered. The `*.uk.md` files keep their names for link stability although their content is now an unofficial English translation. The pre-translation originals are stored outside the documentation set at `.translation-backup/uk-originals-2026-10-04.tar.gz`. Code, configuration and runtime were not changed.
