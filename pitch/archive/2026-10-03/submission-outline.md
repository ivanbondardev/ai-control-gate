# Submission: structure

> **Partially outdated (marked 2026-10-03, 16:00).** The slide plan and the list of mandatory fields remain valid. The item “What works today”, slides 4–9 and the “Before submission” checklist describe an implementation that was **deleted** on 3 October 2026, so they contain untrue statements about working code. They must be rewritten for the “no code” state. The code remains in the git history (commit `52f1d87`).

Updated: 2026-10-03. **Rewritten according to the primary competition rules** (`sources/goldman-task/extracted/RULES AI Control Layer.md`, sec. 5). The submission language is English: the rules allow English or Polish (RULES:33), and English satisfies them.

## What changed on 3 October

| Was (2026-10-02) | Became (fact from RULES) |
|---|---|
| The main artifact — a 2–3 minute video | **The mandatory artifact — a PDF presentation of up to 10 slides.** There are no requirements for a video |
| A one-page submission text | Mandatory fields: project title, team name, team members (1–6), project description |
| The submission channel is unknown | The **HackTribe** platform |
| The repository and demo are separate artifacts | «could include: snapshots, code repository, demo links, graphic materials» — that is, **appendices to the presentation** |

A video can be recorded as an appendix, but it is not a requirement and must not eat into the time set aside for the mandatory elements.

## Mandatory submission fields (RULES:25–33)

| # | Field | Our value |
|---|---|---|
| a | Project title | AI Control Layer — Action Gate (confirm the final name) |
| b | Team name | to be determined |
| c | Team members (1–6) | to be determined; currently solo |
| d | Project description | the text below |
| e | PDF presentation, ≤ 10 slides | the slide plan below |

## Project description (submission text)

1. **The problem — in the partner's words.** Agents have moved from answers to actions: access to resources, process automation. The risks: data disclosure, unauthorised actions, unpredictable costs. Traditional security tools do not cover them.
2. **The solution — one sentence.** A control layer between the agent and what it reaches for: **everything passes through it**, a deterministic policy makes the decision based on the configuration, the semantic control gives a signal, and every step leaves immutable evidence.
3. **Two lines of defence.** (a) Interaction content: the prompt and the model response — deterministic patterns (PII, secrets) and semantic control; the result is `allow` / `redact` / `block`. (b) The action boundary: a tool invocation proposal — the agent passport, scope, budgets; the result is `allow` / `deny` / `escalate`. The second line works even when the first one let something through.
4. **What works today.** **Rewrite: as of 3 October 2026 nothing works — the implementation has been deleted.** Previously this listed components (the layer, a policy in YAML with sensitivity thresholds, a signature feed, an audit log with a hash chain, budgets, a dashboard, a test suite). If the code is not restored, the item is replaced with “What we propose and how to verify it”.
5. **Evidence in numbers.** N attack attempts → 0 executions; p95 layer latency; the share of actions with no additional human step; M tests, positive and negative.
6. **Limits.** Mock tools; no real IAM; simplified policies; load not tested; the semantic control is a local model, not a production-grade classifier.
7. **The next step.** Where this fits: a proxy in front of model and tool invocations (including an MCP gateway), policy as code with CI, the log as a source of evidence for audit.

## Slide plan (exactly 10, mandatory artifact)

| # | Slide | What is on it | The criterion it works towards |
|---|---|---|---|
| 1 | Title + one sentence | Name, team, members. “Agents propose, policy decides” | — |
| 2 | The problem in the partner's words | The three risks from CRIETRIA + the phrase «traditional security tools are not equipped» | — |
| 3 | **Architecture diagram** | Two lines of defence: content and action. Mandatory item 3b of the task | Architecture (20%) |
| 4 | Hybrid protection | Deterministic controls (PII, secrets, access) **and** semantic ones. Why the model is a detector, not a judge | Robustness (30%) |
| 5 | Centralised policy | One file: controls, Block/Redact thresholds, allowed models, budgets. Live reload | Robustness (30%) |
| 6 | Budgets and resources | Money per action, tokens, compute time; degradation instead of a stop | Robustness (30%) |
| 7 | Signature feed | An external feed, classes: malicious code execution, unsafe deserialization, supply chain | Robustness (30%) |
| 8 | Reporting | A dashboard for management + log export for security teams. Two audiences | Security Reporting (20%) |
| 9 | Test suite and evidence | Positive and negative cases; numbers: attacks/executions, p95, control coverage | Self-Testing (20/15%) |
| 10 | Limits and the next step | Honest constraints + the adoption path | Practical (10/15%) |

Rule: **everything the task calls mandatory must have a slide.** Slide 3 (the diagram) and slide 5 (the configuration) are direct requirements, not decoration.

## Repository README

- One sentence about the project.
- A flow diagram: content → control → model; action → policy → execution → log.
- Start-up in two commands, **no cloud and no keys**.
- An example YAML policy with comments, including the thresholds.
- Tests: how to run the policy, attack and budget suites **with one command on a clean machine**.
- A “What is not included” section — the honest limits of the prototype.
- Licence (there is currently no `LICENSE` file — add one).

## Video (appendix, not a requirement)

According to [demo-script.md](demo-script.md), with sound, in English. Record it **only after** the mandatory artifacts are ready. A demo link can be added to the presentation as a permitted appendix.

## What to collect in the repository as evidence artifacts

| Artifact | Why |
|---|---|
| `policy/tests/` | To prove that the policy is tested, not just drawn |
| `attacks/` | A list of bypass attempts with the expected result |
| `benchmarks/latency.md` | The numbers for the “control tax” panel |
| `audit/sample-export.json` | An example “evidence package” for one operation |
| `docs/limits.md` | The honest limits of the prototype |
| **diagram image** | Right now the diagram is ASCII only — the PDF needs a PNG or SVG |

## Before submission

- [ ] **The PDF is no longer than 10 slides** — a direct requirement of the rules.
- [ ] All five mandatory fields are filled in: project title, team name, members, description, presentation.
- [ ] **There is no code** (deleted on 3 October 2026), so the item about `make test` does not apply until the implementation is restored.
- [ ] The layer survives a live configuration edit: deleting a rule, changing a threshold, a broken file (not 500).
- [ ] The numbers in the text match those on the screen, in the presentation and in the README.
- [ ] The repository and demo links open from someone else's account.
- [ ] The language is English.
- [ ] Submitted **20 minutes before the deadline**, by the early deadline (11:00 on 4 October) — the discrepancy “11:00 PM” in RULES has not been clarified.
