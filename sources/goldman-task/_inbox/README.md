# _inbox — raw files with the Goldman Sachs task description

Place files **as they are**, without renaming their contents or editing them: PDFs, screenshots, platform exports, briefing notes, organizers' emails.

Names: `YYYY-MM-DD-<source>-<short-name>.<extension>`, where source is `hackyeah`, `goldman`, `platform`, `organizer`, or `mentor`.

| File | Source | Obtained | What it is |
|---|---|---|---|
| [CRIETRIA AI Control Layer.pdf](<CRIETRIA AI Control Layer.pdf>) | goldman | 2026-10-03 11:33 | Task description: context, problem, expected artifacts, formal and technical requirements, testing approach, criteria |
| [RULES AI Control Layer.pdf](<RULES AI Control Layer.pdf>) | goldman | 2026-10-03 11:32 | Competition rules: organizer, prizes, deadlines, submission requirements, two evaluation phases, criteria |

Both have been converted to Markdown in [../extracted/](../extracted/README.md) — in English and Ukrainian. Analysis: [../notes/task-analysis-2026-10-03.md](../notes/task-analysis-2026-10-03.md).

**What else should be added to `_inbox/`:** the organizers' message about the deadline (the "11:00 PM" discrepancy, see section 6.1 of the analysis), the submission form on HackTribe, a screenshot of the track card, the announced judging panel from Discord.

For text files — the header:

```markdown
---
title: ...
source: task-card | briefing | platform | email | screenshot | mentor
obtained: 2026-10-03
origin: <URL or "live at the event">
language: en | pl | uk
verbatim: true | false
---
```

In detail: [../README.md](../README.md).
