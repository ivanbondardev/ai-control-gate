# Analysis of the Goldman Sachs "AI Control Layer" task

> **Boundary of the historical snapshot, added 2026-10-04:** the comparison with the prototype and the proposals below relate to the state as of 2026-10-03. They are not an assessment of the current copy. The newer implementation and boundaries are described in the [MCP](../../mcp-fixes-2026-10-04.md) and [model proxy](../../model-proxy-implementation-2026-10-04.md) reports. The historical text is preserved; the requirements of the primary sources are unchanged.


Compiled: 2026-10-03. Sources: [../_inbox/RULES AI Control Layer.pdf](../_inbox/RULES%20AI%20Control%20Layer.pdf) and [../_inbox/CRIETRIA AI Control Layer.pdf](../_inbox/CRIETRIA%20AI%20Control%20Layer.pdf); text versions — [../extracted/RULES AI Control Layer.md](../extracted/RULES%20AI%20Control%20Layer.md) (hereinafter **RULES**) and [../extracted/CRIETRIA AI Control Layer.md](../extracted/CRIETRIA%20AI%20Control%20Layer.md) (hereinafter **CRIETRIA**).

References to lines are in the `extracted/*.md` files, not in the PDF.

**Conversion check.** The `.pdf → .md` conversion was performed by the owner. Since the conclusions depend on it, the key claims were verified against the PDF independently — by parsing the PDF streams and the `ToUnicode` tables (a one-off script, not stored in the repository). The following matched verbatim:

| Claim | Source | Verification result |
|---|---|---|
| "11:00 PM" for both dates | RULES | **matched**: "n? earlier than 11:00 PM on October 3rd" |
| "maximum 10-slides PDF presentation" | RULES | **matched** |
| "submitted to platform HackTribe in English or Polish" | RULES | **matched** |
| Criteria 30/20/20/**20**/**10** | RULES | **matched** |
| Criteria 30/20/20/**15**/**15** | CRIETRIA | **matched** |
| "Block vs Redact or adherence %", "allowed LLM models" | CRIETRIA | **matched** |
| "compute time or token spend for access to LLMs" | CRIETRIA | **matched** |
| "signatures … fed from some externally managed system" | CRIETRIA | **matched** |
| "local models (such as those run via Ollama)" | CRIETRIA | **matched** |

**Verification conclusion:** the `.md` conversion is accurate; the criteria-weight discrepancy (section 5) and the "11:00 PM" discrepancy (section 6.1) are discrepancies of the **documents themselves**, not conversion errors.

---

## 1. What these documents are

| Document | What it is | Scope |
|---|---|---|
| RULES | Official competition rules: organizer, prizes, deadlines, submission requirements, criteria, two evaluation phases | 15 clauses, 3 pages |
| CRIETRIA | Task description: context, problem, what needs to be done, expected artifacts, formal and technical requirements, how the judges will verify | 8 sections, 4 pages |

**Source fact:** RULES is an annex to the general HackYeah rules, and the sponsor and the party promising the prize is Proidea Sp. z o.o. (RULES:15, 17). That is, RULES has higher legal force than CRIETRIA.

---

## 2. What the task requires (source facts)

### 2.1. Form of the solution

**Source fact** (CRIETRIA:29): "build a lightweight, flexible AI Control Layer. This layer can be implemented as a gateway, proxy, middleware, or SDK wrapper that intercepts and governs interactions with AI systems".

**Source fact** (CRIETRIA:33): the list of interactions the layer must intercept — "agent to agent, app to agent, agent to MCP, agent to model, etc communication".

### 2.2. Hybrid defense — the central requirement

**Source fact** (CRIETRIA:29): "your control layer must implement a hybrid defense architecture utilizing both non-AI (deterministic) and AI- based (semantic) controls".

**Source fact** (CRIETRIA:53, 55): deterministic controls — "pattern matching (detecting PII or secrets), checking of authentication or access requirements"; semantic — "consider using AI-based solutions/model to secure interaction with the AI systems".

**Source fact** (CRIETRIA:19): the rationale — "Such layer must instantly inspect, redact, or block unsafe interactions in real-time, using a hybrid approach of traditional policy enforcement combined with AI-supported enforcement".

### 2.3. Centralized policy engine

**Source fact** (CRIETRIA:49): "A single config source (e.g. file/system) managing controls, sensitivity thresholds (Block vs Redact or adherence %), allowed LLM models, and resource/financial budgets".

Four things that a single file must cover: controls · sensitivity thresholds (Block **vs** Redact) · **allowed LLM models** · budgets.

### 2.4. Budgets and resources

**Source fact** (CRIETRIA:57): "how to enforce budget limits (e.g. resource access, compute time or token spend for access to LLMs)".

**Source fact** (CRIETRIA:29): manage budgets "for both external commercial APIs and locally hosted models".

### 2.5. Mitigation of historical attacks — with an external feed

**Source fact** (CRIETRIA:29): "how it can detect or mitigate known historical attacks on AI infrastructure (i.e. where signatures of such attacks can be fed from some externally managed system)".

**Source fact** (CRIETRIA:59): examples — "malicious code execution, unsafe deserialization, or supply-chain exploits targeting model repositories".

### 2.6. Reporting and audit

**Source fact** (CRIETRIA:61): two different audiences — "real-time metrics (blocked interactions, budget usage) for management and exportable audit logs designed for security teams".

**Source fact** (CRIETRIA:43): the dashboard shows "controls, overall security posture, blocked threats, and other metrics (e.g. resource consumption/cost)".

### 2.7. Test suite

**Source fact** (CRIETRIA:45): "A ready to run test-suite which can verify implementation of your controls, including budget limits and exploit mitigation".

**Source fact** (CRIETRIA:63): "Automated test suite verifying both positive (allowed) and negative (blocked) cases".

### 2.8. Architecture diagram

**Source fact** (CRIETRIA:37): "You should provide a simple diagram presenting the architecture of your solution".

### 2.9. Resources and constraints

**Source fact** (CRIETRIA:77): no datasets, proprietary APIs, or special hardware; no paid subscriptions; "Teams are expected to use publicly available open-source libraries where necessary and local models (such as those run via Ollama), and their own self- created test prompts".

**Source fact** (CRIETRIA:67): the stack is free, but "make sure you check the license of these tools"; pre-existing agents, LLMs, and applications that use our layer are **not assessed**.

---

## 3. How exactly the judges will verify (CRIETRIA:73) — the most important section

**Source fact**, five separate mechanisms:

1. **The judges run our test suite themselves** — "Judges will execute the automated test suite provided by the team".
2. **Spontaneous actions without preparation** — "spontaneous, zero- preparation actions".
3. **Interactive testing of the running layer** with ad-hoc requests — "Judges may interactively test the running control layer in real time using spontaneous, ad-hoc prompts and observing how the system reacts".
4. **The judges modify the configuration** — "may modify the configuration files/feeds to your AI Control Layer (e.g. changing rules, removing controls, adjusting thresholds) to understand how the control layer behaves with new configuration (how changes are reflected, can they adjust in real-time, etc)".
5. **Performance telemetry** — "You should be able to produce performance telemetry as it may be used for evaluation".

Plus a review of the architecture, dashboards, and logs.

**Hypothesis (high confidence):** item 3 is the main risk. A judge will write an arbitrary prompt and see whether the layer intercepts it and whether it redacts the content. If our layer only sees structured tool invocations, it will respond to an arbitrary prompt with nothing.

---

## 4. Submission (source facts from RULES)

**Source fact** (RULES:23, 25–33): participation is individual or in teams of up to 6 people. The submission **must include**:

| # | What | Verbatim |
|---|---|---|
| a | project title | "project title" |
| b | name of the team | "name of the team" |
| c | list of team members (1–6) | "list of team members (1-6 members)" |
| d | project description | "project description" |
| e | PDF presentation of up to 10 slides | "maximum 10-slides PDF presentation" |

**Source fact** (RULES:33): the presentation "could include: snapshots, code repository, demo links, graphic materials and other materials related to the project" — that is, the repository, demo links, and screenshots are **added to the presentation**, as permitted attachments.

**Source fact** (RULES:33): "submitted to platform HackTribe in English or Polish".

**Source fact** (RULES:73): "Any alterations or revisions made after the statutory time is expired are illegal. Any alterations and modifications made after the statutory time is expired will not be considered by the Jury".

**Source fact** (RULES:47–51): two phases. Phase 1 — evaluation of the submitted projects **on the HackTribe platform** by a commission of **at least three mentors**. Phase 2 — live presentations by the finalists before the judging panel. The compositions may coincide, but not necessarily.

**Source fact** (RULES:69): "the project must receive a minimum of 50% of the points in 1 step" — the cut-off threshold at the first phase.

**Source fact** (RULES:39–43): prize pool PLN 15,000: 1st place 6,000, 2nd 5,000, 3rd 4,000 (all including tax).

**Source fact** (RULES:21): prizes are issued within 90 days after the announcement of the results.

**Source fact** (RULES:75): the proprietary copyrights to the awarded solution are **not** transferred to the sponsor.

**Source fact** (RULES:77): the judging panel will be announced on Discord no later than October 4.

---

## 5. Evaluation criteria — and the discrepancy between the documents

| Criterion | RULES:59–67 | CRIETRIA:83–91 |
|---|---:|---:|
| Robustness of the Solution and Quality of Guardrails | 30% | 30% |
| Architecture and Performance Efficiency | 20% | 20% |
| Security Reporting | 20% | 20% |
| Completeness of the Self-Testing Suite | **20%** | **15%** |
| Practical Implementability and Scalability | **10%** | **15%** |

**Source fact:** the discrepancy is real — in two documents of the same competition, the weights of the last two criteria differ by 5 percentage points.

**Hypothesis (medium-high confidence):** the RULES weights are the effective ones, because these are the official competition rules and an annex to the general HackYeah rules, whereas CRIETRIA is the task description. But this has almost no practical significance: both documents give the **same order of priorities**, and gaining one criterion at the expense of another is impossible — it is the same 100%.

**What this means for the allocation of effort.** The previous table in [../../../docs/05-judging.md](../../../docs/05-judging.md) described the criteria of the **open** tasks (idea and innovation 30%, design 20%…). It does not apply to this track. The real priorities:

| Priority | Criterion | Weight | What gives the maximum |
|---|---|---:|---|
| 1 | Robustness + Quality of Guardrails | 30% | The layer actually blocks/redacts what it should; controls are heterogeneous (deterministic **and** semantic); behavior is predictable on others' prompts |
| 2 | Architecture and Performance Efficiency | 20% | Architecture diagram, clean boundaries, performance telemetry, absence of redundant layers |
| 3 | Security Reporting | 20% | Dashboard + exported logs for security teams; two different audiences |
| 4 | Self-Testing Suite | 20% / 15% | Positive **and** negative cases, including budgets and exploits; launch with a single command |
| 5 | Practical Implementability and Scalability | 10% / 15% | Honest boundaries, an adoption path, scalability |

**Conclusion:** 70% of the score is "the layer works and it is visible", 30% is "the evidence base". Screen design and the novelty of the idea are not directly assessed at all.

---

## 6. Discrepancies to be resolved with the organizers

### 6.1. Deadline time — critical

**Source fact** (RULES:23): "who have started solving the competition task no earlier than 11:00 PM on October 3rd and forwarded the task for evaluation no later than 11:00 PM on October 4th".

**Source fact** (../../../sources/event-context.md (archive reference: `../../../sources/event-context.md`), lines 16 and 22): publication of the tasks and the start of programming — **11:00** on October 3; the deadline for the final submission — **11:00** on October 4. Also there (line 25): announcement of the finalists — **15:00** on October 4.

**Analysis:** "11:00 PM" is 23:00. If RULES is read literally, the submission deadline is 23:00 on October 4, that is, 12 hours later than the event schedule. But then the announcement of the finalists at 15:00 on October 4 would be impossible: evaluation would not have started yet. The event schedule and the logic of the phases indicate that RULES contains a typo and "11:00 AM" was intended.

**Hypothesis (high confidence):** RULES has an error, "PM" instead of "AM".

**Decision (proposal, not fact):** plan for the **earlier** of the two times — 11:00 on October 4. An error on the safe side costs nothing; an error on the unsafe side costs the entire submission. The question should be put to the organizers anyway and the answer recorded.

### 6.2. Criteria weights

The discrepancy is described in section 5. The impact on the work is minimal, but the question is worth asking: it shows that we read both documents.

### 6.3. Submission format: a presentation, not a video

**Source fact** (RULES:33): the mandatory element is a PDF presentation of up to 10 slides. Video is **not mentioned** in the list of mandatory elements; it mentions "snapshots, code repository, demo links, graphic materials".

**Consequence:** the submission plan ([../../../pitch/submission-outline.md](../../../pitch/archive/2026-10-03/submission-outline.md)) was built around a 2–3 minute video. Video is not a requirement. The mandatory artifact that was not in the plan at all is the **presentation of up to 10 slides**. The plan was rewritten on 2026-10-03: the PDF became the main artifact, and the video remained an appendix.

### 6.4. Submission language

**Source fact** (RULES:33): "in English or Polish". The card required English. English satisfies both documents — the question is closed.

---

## 7. Comparison with our Action Gate prototype

Verified against the `app/` code (a separate audit, not the README). Run: `make test` → **75 passed, 2.33 s, exit 0**.

| # | Task requirement | Status | Evidence |
|---|---|---|---|
| 1 | Centralized policy engine (single file) | **Covered** | `policy/policy.yaml` + optional override, merged and hashed into `rev` |
| 2 | Interception of `agent → model`, `app → agent`, `agent → MCP` | **Missing** | the layer only sees proposed actions on tools; there are 0 network calls in the code, neither a proxy to the model nor an MCP client |
| 3 | Deterministic controls: access and authentication | **Covered** | agent passport, scope, tool catalogue, expired passport |
| 4 | Deterministic controls: pattern matching for PII and secrets | **Missing** | 0 implementations; `injection.watch_arg_keys` are argument names, not content patterns |
| 5 | **Semantic controls (AI-based)** | **Missing — and documented as a principled refusal** | `evaluator.py:3` "No model, no score, no judgement"; `POLICY.md` "No … the model judges risk"; `README.md:149` |
| 6 | **`redact` as a decision outcome** | **Missing** | app/action_gate/models.py:38–43 (archive reference: `../../../app/action_gate/models.py#L38-L43`) — only `ALLOW`, `DENY`, `ESCALATE`; the validator and the UI know three |
| 7 | Block vs Redact / adherence % thresholds | **Missing** | there is no sensitivity-threshold section in the policy |
| 8 | **Allowed LLM models in the policy** | **Missing** | there is no field; meaningless without item 5 |
| 9 | Budgets: money per action | **Covered, verified empirically** | per-action, per-day, soft degradation; 14×500 PLN → then `deny R-000-envelope-daily` |
| 10 | **Budgets: tokens / compute time** | **Missing** | the `spend` table counts money; time is only measured as decision latency, not limited |
| 11 | **Mitigation of historical attacks** (malicious code, unsafe deserialization, supply chain) | **Missing** | the 13 existing attacks are of a different class: authorization, identity, limits, injection in text |
| 12 | **External signature feed** | **Missing** | there is neither a signature table, nor a feed loader, nor a policy condition for them |
| 13 | Reporting: real-time metrics | **Partially covered** | blocked interactions are present; **budget usage is missing** in the metrics and in the UI |
| 14 | Reporting: exported audit logs | **Partially covered** | an evidence package for **a single** decision; there is no bulk export for a period |
| 15 | Interactive dashboard | **Partially covered** | 5 panels, refresh every 2.5 s; **there is no list of controls**, although `/api/policy` is already loaded in the client |
| 16 | Executable test suite, positive and negative | **Covered** | 75 tests; but `disable_rules` and `R-000-envelope-daily` are not covered |
| 17 | **The test suite is launched by a judge with a single command** | **Not done** | `make test` requires `.venv`, which is in `.gitignore`; on a clean clone — `No such file or directory`. `make setup` **with network** is needed |
| 18 | Architecture diagram | **Partially covered** | only ASCII in Markdown; not a single image — for the PDF submission it will have to be drawn |
| 19 | Configuration change in real time | **Partially covered** | reload exists and works; **there is no automatic pickup** — without an explicit reload the old policy remains in memory |
| 20 | Licenses of third-party tools | **Missing** | there is no `LICENSE` file |

### Main conclusion

**The problem is not the number of missing features, but the interception point.**

**Source fact** (CRIETRIA:19): the layer must "instantly inspect, redact, or block unsafe interactions in real-time" — work with the **content of the interaction**.

**What we have:** Action Gate intercepts **structured tool-invocation proposals** and decides `allow/deny/escalate`. This is a strong but **narrower** thing than the task: a subset of "agent → MCP" without content.

**What we do not have:** a layer that looks at **text** — the prompt, the model's response. That is exactly where PII, secrets, prompt injection, and semantic controls live.

**Hypothesis (high confidence):** to a judge's spontaneous prompt (CRIETRIA:73, item 3) the prototype will respond with nothing — it will not see it. This is a direct blow to criterion No. 1, weighted 30%.

### A separate finding: we argue with the task in the documentation

The riskiest spot is not the absence of semantic control in itself, but the fact that **the README and POLICY.md argue against the model**: `evaluator.py:3` — "No model, no score, no judgement", `POLICY.md` — "No … the model judges risk".

**Hypothesis (high confidence):** at the defense this will read not as "a boundary of the prototype" but as **a refusal to fulfill a formal requirement**. The difference must be removed in the text: the model is a **detector**, the policy is the **arbiter**. This does not contradict our thesis but refines it, and it matches our own hypothesis S2.

### What remains a strength

- **Enforcement in the execution path** with a default of `deny` and fail-closed — criterion 1.
- **Audit hash chain** with a separation of "claimed by the agent" and "confirmed by the system" — criterion 3.
- **Live policy reload** — exactly what the judges will do per CRIETRIA:73.
- **75 tests offline, 2.33 s** — criterion 4.
- **What is claimed in the README matches the code** — a rare case, and this is worth emphasizing at the defense.

---

## 8. What to do next (priority by cost/effect ratio)

The order takes into account both the weight of the criterion and what the judge will see live.

| # | Action | Closes | Cost |
|---|---|---|---|
| 1 | **`make test` on a clean machine** — a target that creates the venv itself, plus a stdlib variant of the tests on a JSON policy | criterion 4 (20/15%), §6 | ~2 h |
| 2 | **Auto-reload + monitoring of both files + 400 instead of 500** on a broken policy | Architecture (20%), §6 | ~2 h |
| 3 | **Budget-usage metric** in `/api/metrics` and on the dashboard | Security Reporting (20%) | ~1 h |
| 4 | **Controls panel in the UI** from the already loaded `state.policy.rules` | Security Reporting (20%), §3.3 | ~1 h |
| 5 | **Signature feed + a policy condition for it** (eval/exec in arguments, pickle blob, `trust_remote_code`) | Robustness (30%), §4.4, "feeds" from §6 | ~3–5 h |
| 6 | Tests for `disable_rules` and `R-000-envelope-daily` | criterion 4 | ~1 h |
| 7 | **An image diagram** for the PDF submission | Architecture (20%), §3b | ~1 h |
| 8 | **Semantic control with a local model** (Ollama) as a second layer; the policy is the arbiter; fail-closed if the model is unavailable | Robustness (30%), §4.2.2 | ~3–4 h |
| 9 | **Rewrite the wording in the README and POLICY.md** about the model: a detector, not a judge | removes the risk of "refusing the requirement" | ~1 h |
| 10 | `LICENSE`, bulk audit export, fixes to `requirements.txt` and `docs/DEMO.md:12` | formal requirements, trust | ~2 h |

**What cannot be cut:** items 1, 2, and 5. The first — because the entire verification rests on it; the second — because it is the behavior most noticeable to a judge; the fifth — because it is a separate formal requirement that is entirely absent.

**Hypothesis (medium confidence):** item 8 outranks item 5 in weight but lags in risk — without a local model it cannot be demonstrated. If there is no model, close item 8 honestly: show the interface, say "a local model works here", and do not pretend that it works.

---

## 9. Which open questions have been closed

| Question from [../../../docs/07-open-questions.md](../../../docs/07-open-questions.md) | Status |
|---|---|
| 1. Full conditions and evaluation criteria | **Closed** — RULES and CRIETRIA; criteria in section 5 |
| 2. Submission language | **Closed for Goldman** — English or Polish (RULES:33); English satisfies it |
| 4. Submission format and channel | **Partially closed** — HackTribe, PDF of up to 10 slides, project title, team name, team composition, description. There are no video requirements |
| 6. Whether Goldman requires its own SDK, data, or environment | **Closed** — nothing is provided or required (CRIETRIA:77) |
| 7. Technical requirements for video | **Dropped** — video is not mandatory (RULES:33) |
| 8. Whether external LLM services are allowed | **Closed** — there will be no paid subscriptions; local models are expected, e.g. Ollama (CRIETRIA:77) |
| 3, 5, 9, 10 | Remain open — they concern other tracks and the time zone |

## 10. New open questions

| # | Question | Why it matters |
|---|---|---|
| 11 | Submission deadline: 11:00 or 23:00 on October 4? | 12 hours of difference; RULES says "11:00 PM", the event schedule says 11:00 |
| 12 | Which weights are in effect: RULES (20/10) or CRIETRIA (15/15)? | The impact is small, but the question shows attentiveness to the documents |
| 13 | Are the repository and demo link counted as separate artifacts, or only inside the PDF? | Determines whether the demo needs to be embedded in the slides |
| 14 | Is there a requirement for the PDF size, the number of characters in the description, or the format of names? | A minor thing, but a submission could be rejected on formal grounds |

---

## 11. Boundaries of this analysis

- The time estimates in section 8 are a **proposal**, not a measurement.
- The presence of a local model (Ollama) on the owner's machine has not been checked.
- Section 7 was verified against the code; the automated test run is separate, with the result in the audit report.
- The PDFs were not read directly: the analysis is based on the converted `.md`, and the conversion was performed by the owner. A discrepancy between the PDF and the `.md` cannot be ruled out; for item 6.1 ("11:00 PM") the PDF itself should be checked.

---

## 12. External model providers instead of a local one (2026-10-03)

**Circumstance:** there is no local model (Ollama) on the owner's machine, but there is access to **OpenAI and DeepSeek models through official providers**.

### Is this allowed — source fact

**Source fact** (CRIETRIA:77), verbatim: "No subscriptions on paid services (e.g. OpenAI, Anthropic, Copilot, etc) **will be provided** for this challenge so ensure that you can design, build and run the entire system on your own setup".

This says that subscriptions **will not be provided** — that is an organizational fact, not a prohibition on using one's own. The task does not contain any phrase that would prohibit an external API.

**Source fact** (CRIETRIA:29), verbatim: "think about how to make it resilient enough to manage budgets for **both external commercial APIs and locally hosted models**".

**Conclusion (high confidence):** external commercial APIs are not a loophole and not a compromise, but a **case named directly in the task** that the layer must be able to serve. In the text, local models are "expected", not "required". The use of OpenAI and DeepSeek is consistent with the task.

### What we gain from this

| Gap | What a real provider gives |
|---|---|
| No semantic controls (criterion 30%) | A genuine AI-based control instead of a stub |
| No token budgets | **Real** token and money spend — measured, not simulated |
| No list of allowed models in the policy | The field becomes meaningful: the layer refuses a model that is not on the list |
| No performance telemetry | Provider latency as a separate, interesting metric |

**Hypothesis (high confidence):** this makes the budget demonstration **stronger** than a local model. A local model costs nothing, so there is nothing to manage a budget for; an external API spends real money on tokens, and this is visible on the screen.

### The main constraint — and it is also the biggest opportunity

**Source fact** (CRIETRIA:73): "Judges will execute the automated test suite provided by the team". **Source fact** (CRIETRIA:77): "run the entire system on your own setup".

**Consequence (high confidence):** the test suite **must not require our key**. A judge runs it on their own machine, without our secrets and possibly without a network. Therefore:

- **The tests are deterministic, on recorded model responses.** Semantic control is verified on fixtures, not on a live API.
- **The live mode is separate, enabled by an environment variable.** Without a key the layer **degrades explicitly** ("semantic control unavailable"), rather than crashing or pretending to work.
- The existing seam was already made for this: `config.py` has `agent_mode` with the value `live`, marked as "(unimplemented) LLM seam", and `action_gate/agent/__init__.py` documents where the model is plugged in.

### The conflict that must be resolved by architecture

Our own docs/04-goldman-hypotheses.md (archive reference: `../../../docs/04-goldman-hypotheses.md`) in the list of "what they most likely do not want" names "a solution that takes the bank's data out to an external service". For a bank this is a real objection, and it does not disappear just because the task allows an external API.

**Proposal (medium-high confidence) — redaction before leaving the perimeter:**

```
content → deterministic scan (PII, secrets) → REDACT → external model → signal → policy → decision
```

Raw data does not leave the perimeter: what goes out is already cleaned text. This turns the objection into an advantage and **closes two gaps with a single mechanism** — the missing `redact` and the missing semantic control.

Wording for the pitch: "what goes to the external model is already redacted content; what must not leave does not leave at all".

### Risks

| Risk | Response |
|---|---|
| The judge has no key — the tests do not run | Tests without a key; live mode separate |
| The network at the venue fails in the middle of the demo | Degradation instead of a crash; recorded responses as a fallback |
| Real token spending during the demo | A limit on the demo run — our own budget mechanism |
| Non-determinism: a judge's spontaneous prompt yields a floating verdict | The model returns a **structured signal with confidence**, and the policy decides by thresholds; the log records the provider, the model, and the prompt hash |
| Keys in the repository | Only environment variables or `.env` (already in `.gitignore`); they never reach the repository |
| Data goes to a provider in another jurisdiction | The provider is a variable; redaction before egress; in production — the same interface to a local model |

### What this changes in the priorities

The item "semantic control with a local model" from section 8 is **unblocked**: it no longer depends on the availability of Ollama. The order of work becomes:

1. A provider adapter with two backends (OpenAI, DeepSeek) behind a single interface.
2. Deterministic redaction of PII and secrets **before** egress.
3. Semantic control as a **signal**, the policy as the arbiter.
4. An `allowed_models` field in the policy + a token budget.
5. Tests on recorded responses; live mode separate.

**Hypothesis (high confidence):** items 1–5 together close the biggest gap (the criterion weighted 30%) and do so more convincingly than a local model.
