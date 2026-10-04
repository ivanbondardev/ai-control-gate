# goldman-task — detailed description of the task from Goldman Sachs

**Navigation after the migration:** new entries for this copy go to the [session log](../../docs/08-session-log.md). The textual `archive reference` mentions of the journal of the same name below denote the old, unmigrated journal; they are not links to the new history.


Created: 2026-10-02. **Populated 2026-10-03.** This is where the owner places files with a detailed description of the AI Control Layer track (Goldman Sachs) task — everything obtained at the event or found before it.

The agent does not download these materials, does not search on the owner's behalf, and does not make things up. It reads what has been placed here and analyzes it according to the discipline of claims.

## Status

| What | Where |
|---|---|
| Raw PDFs: `CRIETRIA` (task description) and `RULES` (competition rules) | [_inbox/](_inbox/README.md) |
| Text and translations | [extracted/](extracted/README.md) |
| **Analysis of the task, discrepancies, comparison with the prototype** | [notes/task-analysis-2026-10-03.md](notes/task-analysis-2026-10-03.md) |

Brief summary: criteria — Robustness+Guardrails 30%, Architecture 20%, Security Reporting 20%, Self-Testing 20% (RULES) / 15% (CRIETRIA), Practical 10% (RULES) / 15% (CRIETRIA). Submission — a PDF of up to 10 slides on the HackTribe platform; no video is required. The assessment of the old prototype in the analysis is historical. The current model input is described in the [proxy contract](../../app/contracts/model-proxy.md); the presence of generation does not prove the quality of the semantic protection.

## Why this folder

The track card is not a specification. In [../../docs/07-open-questions.md](../../docs/07-open-questions.md) six questions are already closed by the primary documents; what remains are the deadline, the criteria weights, and the formal submission constraints. The analysis is kept separate so that source fact is not mixed with conclusion.

## Structure

| Folder | What to put there |
|---|---|
| [_inbox/](_inbox/README.md) | Raw files as they are: PDFs, screenshots, platform exports, `task.md`, organizers' emails |
| `extracted/` | text extracted from PDFs and images, with a note of where it came from |
| `notes/` | summary: requirements, criteria, deadlines, contradictions, open questions |

Do not rename or clean anything in `_inbox/` — the primary file must remain recognizable.

## File names

```
YYYY-MM-DD-<source>-<short-name>.<extension>
```

Examples:

- `2026-10-03-hackyeah-task-card-goldman.pdf`
- `2026-10-03-goldman-track-briefing-notes.md`
- `2026-10-03-platform-submission-form.png`
- `2026-10-03-organizer-email-language-and-deadline.md`

The date is when the material was obtained. Source — `hackyeah`, `goldman`, `platform`, `organizer`, `mentor`.

For text files, the following header is preferred:

```markdown
---
title: ...
source: task-card | briefing | platform | email | screenshot | mentor
obtained: 2026-10-03
origin: <URL or "live at the event">
language: en | pl | uk
verbatim: true | false
---

<text as is>
```

Set `verbatim: false` for your own paraphrase of what was heard — otherwise on stage a paraphrase may accidentally be quoted as an exact requirement.

## What the agent does with this folder

On request:

1. Reads `_inbox/`, extracts text from PDFs and images into `extracted/` (indicating the source).
2. Produces a summary in `notes/`: requirements, criteria, mandatory artifacts, deadlines, constraints, language.
3. Cross-checks the findings against ../../docs/02-project-action-gate.md (archive reference: `../../docs/02-project-action-gate.md`), ../../docs/04-goldman-hypotheses.md (archive reference: `../../docs/04-goldman-hypotheses.md`) and [../../docs/05-judging.md](../../docs/05-judging.md): what was confirmed, what was refuted, what is still unknown.
4. Closes items in [../../docs/07-open-questions.md](../../docs/07-open-questions.md) and adds an entry to ../../docs/08-session-log.md (archive reference: `../../docs/08-session-log.md`).

## Discipline of claims

As everywhere in this catalogue:

- **Source fact** — a reference to a file in this folder (for text files, a line number is acceptable; for images and extracted OCR, a quotation) plus a verbatim fragment.
- **Hypothesis/proposal** — with a confidence level (high / medium / low) and a note that it is not a task requirement.

Judging criteria are not invented: as long as they are not in `_inbox/`, they remain an open question.
