# extracted — text extracted from the raw files

Populated 2026-10-03. Both PDFs have been converted to Markdown — in English (the original text) and in an unofficial English translation. Every document in this workspace is now in English.

**The primary sources of the organizers' task:** the four documents below, as determined by the owner on 2026-10-03. The `.md` files are extractions from the original PDFs; the `.uk.md` files are their unofficial translations, now rendered in English. The `.uk.md` file names are kept unchanged so that existing links keep working. For exact formulations, refer to the English text and the PDF.

| File | What it is |
|---|---|
| [CRIETRIA AI Control Layer.md](CRIETRIA%20AI%20Control%20Layer.md) | Task description in English, the original text |
| [CRIETRIA AI Control Layer.uk.md](CRIETRIA%20AI%20Control%20Layer.uk.md) | Unofficial English translation of the task and criteria |
| [RULES AI Control Layer.md](RULES%20AI%20Control%20Layer.md) | Competition rules in English, the original text |
| [RULES AI Control Layer.uk.md](RULES%20AI%20Control%20Layer.uk.md) | Unofficial English translation of the rules |

**The conversion was performed by the owner and its accuracy verified.** The key claims were verified against the PDF independently — by parsing the PDF streams and `ToUnicode` tables (a one-off script, not stored in the repository). The following matched: "11:00 PM" for both dates, "maximum 10-slides PDF presentation", "in English or Polish", the criteria weights in both documents (30/20/20/20/10 and 30/20/20/15/15), "Block vs Redact", "token spend", "signatures … fed from some externally managed system", "local models (such as those run via Ollama)". Details — in [../notes/task-analysis-2026-10-03.md](../notes/task-analysis-2026-10-03.md).

Long paragraphs should be read in full from the file; a truncated tool output is not an abridgement of the primary source.

Rule: one extracted file corresponds to one file from `_inbox/`, the name matches, and the header contains a reference to the source:

```markdown
---
title: ...
from: ../_inbox/2026-10-03-hackyeah-task-card-goldman.pdf
method: pdf-text | ocr | manual-notes | translation
extracted: 2026-10-03
fidelity: exact | ocr-uncertain | paraphrase | translation
---

<text>
```

`fidelity: ocr-uncertain` — mandatory for OCR from screenshots: deadline figures, prize amounts, and language requirements from such text are not quoted without verification against the original.
