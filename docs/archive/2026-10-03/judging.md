# Historical overview of the criteria and the prototype

Archived 2026-10-04. The earlier text from 2026-10-03 is preserved below; statements about the state of the product and the judges' answers do not describe the current copy. The working document is [criteria](../../05-judging.md).

# 05 — Judging: criteria and distribution of effort

Updated: 2026-10-03. The criteria were **read from the primary task documents** (not a hypothesis): `sources/goldman-task/_inbox/RULES AI Control Layer.pdf` and `CRIETRIA AI Control Layer.pdf`, with text versions in `sources/goldman-task/extracted/`. Analysis: [../sources/goldman-task/notes/task-analysis-2026-10-03.md](../../../sources/goldman-task/notes/task-analysis-2026-10-03.md).

## What changed on 3 October

The previous version of this file contained the criteria of the **open** tasks (idea and innovation 30%, design 20%…) and itself noted that for the Goldman task they had to be rewritten after 11:00. That has been done. **None of those criteria applies to this track.**

## Judging criteria (source fact)

| Criterion | RULES, sec. 11 | CRIETRIA, ch. 8 |
|---|---:|---:|
| Robustness of the Solution and Quality of Guardrails | 30% | 30% |
| Architecture and Performance Efficiency | 20% | 20% |
| Security Reporting | 20% | 20% |
| Completeness of the Self-Testing Suite | **20%** | **15%** |
| Practical Implementability and Scalability | **10%** | **15%** |

**The discrepancy is confirmed in both PDFs.** There is almost no practical impact: the order of priorities is the same, and the total is the same. We plan by RULES (the official competition rules) and keep the difference as a question for the organisers.

## What earns the maximum for each criterion

| # | Criterion | Weight | What is actually assessed | Who is responsible |
|---|---|---:|---|---|
| 1 | Robustness + Quality of Guardrails | 30% | The layer **actually** intercepts and blocks/hides what it should. Controls are heterogeneous: deterministic **and** semantic. Behaviour is predictable on **someone else's** prompts and with a changed configuration | Ivan + security |
| 2 | Architecture and Performance Efficiency | 20% | An architecture diagram, clean boundaries, no redundant layers, **performance telemetry** | Ivan |
| 3 | Security Reporting | 20% | A dashboard for management **and** exported logs for security teams — these are two different audiences per the requirement | Frontend + Ivan |
| 4 | Self-Testing Suite | 20% (15%) | Positive **and** negative cases, including budgets and exploits. Run with a single command **with no preparation** | Security |
| 5 | Practical Implementability and Scalability | 10% (15%) | Honest limits, an adoption path, scalability | Ivan |

**Practical conclusion:** 70% of the score is “the layer works, and that is visible live”, 30% is “the evidence base”. The novelty of the idea and the screen design are directly **not assessed**. The demo must be convincing in operation, not pretty on a slide.

## How the judges will test (CRIETRIA, ch. 6) — read before every run

| Mechanism | Verbatim | Consequence for us |
|---|---|---|
| The judges run our test suite | «Judges will execute the automated test suite provided by the team» | **If the submission includes code:** `make test` must work on a clean machine offline, with no keys and no preparation. There has been no code in this directory since 3 October 2026 |
| Spontaneous actions | «spontaneous, zero- preparation actions» | The demo must not depend on a pre-warmed state |
| Live ad-hoc prompts | «interactively test the running control layer in real time using spontaneous, ad-hoc prompts» | **The biggest risk.** The layer must react to arbitrary text, not only to structured invocations |
| Configuration change | «may modify the configuration files/feeds … changing rules, removing controls, adjusting thresholds … can they adjust in real-time» | Live policy reload is mandatory; removing a control must not break the layer |
| Telemetry | «You should be able to produce performance telemetry as it may be used for evaluation» | Latency and metrics go on the screen, not in a log |

## Where we stand against these criteria

> **Caveat (2026-10-03, 16:00).** This section describes the state of a **deleted** implementation. The “strengths” below relate to commit `52f1d87`; there is no code in the current directory, so there is nothing to show them with. The conclusion about the gap itself remains valid as a design conclusion.

The detailed “requirement → state → evidence” table is in [../sources/goldman-task/notes/task-analysis-2026-10-03.md](../../../sources/goldman-task/notes/task-analysis-2026-10-03.md), section 7. In brief:

**Strengths (they map onto criteria 1, 3, 4):** enforcement in the execution path with a default of `deny`; an audit hash chain that separates “claimed by the agent” from “confirmed by the system”; live policy reload; a test suite with attacks.

**The main gap (it hits criterion 1, weight 30%):** the layer intercepts **structured tool invocation proposals**, not **the content of the interaction**. There are no semantic controls, no `redact`, no interception of prompts and model responses. Today the layer will not respond to a judge's spontaneous prompt — it will not see it.

## Design requirements for the main screen

Design is not a criterion, so these are requirements for **legibility from a distance**, not decoration.

- Left column: what came in — the prompt or the action proposal, in plain language.
- Centre: the verdict with its reason — which rule fired, why exactly `allow` / `deny` / `escalate` / `redact`.
- Right column: human actions (approve / reject) and the timeline of records.
- Four states by colour, if `redact` is implemented: allowed / blocked / **redacted** / escalated.
- At the bottom — the “control tax” numbers: latency, the share of auto-approvals, the ratio of attacks to executions.
- No stack traces, logs or debug panels on the demo screen.

## Judges' questions and prepared answers

> **Caveat (2026-10-03, 16:00).** The answers were written for a working demo that has been **deleted**. Some of them describe on-screen actions — “we show scene 4”, “we remove controls live”, “the number from the measurement” — that there is now nothing to perform. Before use at the defence, each answer must be checked against the actual state.

| Question | Answer |
|---|---|
| How is this different from an event log? | A log describes what happened. We do not let the action happen: the layer sits in the execution path, and there is no other path to the tools and the model |
| Why can't an LLM write the policy? | Because then the decision would depend on the prompt and the data the agent reads. A deterministic policy gives a reproducible and testable decision. In our design the semantic control is a separate signal, not the author of the decision |
| Where is the semantic control here, if the policy makes the decision? | Two levels: the semantic control assesses the **content** and produces a signal (risk class, confidence); the policy makes the decision using thresholds from the configuration. The model has no right to allow an action |
| What happens if the agent tries to bypass the layer? | We show scene 4: the injection does not get through; access to the tools exists only through the layer |
| How much latency does this add? | The p95 layer latency (the number from the measurement) and the share of actions with no additional human step |
| What happens if I turn this rule off? | We remove controls live from the configuration — the layer keeps working, the decision changes, the record remains. This is exactly what section 6 of the task asks for |
| What does not work in your prototype? | An honest list: mock tools, no real IAM, simplified policies, load not tested, the semantic layer is a local model, not a production-grade classifier |
| How would this be embedded in our stack? | The layer becomes a proxy in front of model and tool invocations (including as an MCP gateway), not an application: the agent does not change, the point through which interactions pass changes |
| What if the agent gets stuck in a loop and burns through the budget? | A spend envelope: limits on steps, time and tokens per task; at the boundary — degradation or escalation. The policy sees the budget of the task, not of an individual invocation |
| Does your log prove what the agent did — or what it said about it? | The latter. A hash chain proves integrity, not truth. That is why the record separates what the agent claimed from what the system confirmed, and the agent's rationale is marked as its own statement, not as fact |
| Where do you get the attack signatures? | From an external feed — a local file that the layer reads and reloads live. The task describes this directly as «signatures … fed from some externally managed system». In the demo the feed is local; in production it would be a signed external one |
| Who is accountable when the agent makes a mistake? | Every agent has an owner (an agent passport), every action has a record, and every approval has the name of the person who decided and what they saw on the screen |

The last point about honest limits builds trust; the judges notice its absence faster than a missing feature.
