# 07 — Open questions

**Navigation after the transfer:** new entries of this copy are in the [session log](08-session-log.md). The textual `archive reference` markers to the same-named log below denote the old log that was not transferred; these are not links to the new history.


Updated: 2026-10-03. Close questions with facts from the event, not with assumptions. Once clarified, move the answer here and into 08-session-log.md (archive reference: `08-session-log.md`).

The primary Goldman task documents arrived on 2026-10-03 and are in [../sources/goldman-task/](../sources/goldman-task/README.md). Analysis: [task-analysis-2026-10-03.md](../sources/goldman-task/notes/task-analysis-2026-10-03.md).

## Closed 2026-10-03 (from the primary documents)

| # | Question | Answer | Source |
|---|---|---|---|
| 1 | Full terms and judging criteria of the AI Control Layer task | Criteria: Robustness+Guardrails 30%, Architecture 20%, Security Reporting 20%, Self-Testing 20% (RULES) / 15% (CRIETRIA), Practical 10% (RULES) / 15% (CRIETRIA). Full analysis in [05-judging.md](05-judging.md) | RULES clause 11; CRIETRIA section 8 |
| 2 | Submission language in the Artificial Intelligence category | For Goldman: «in English or Polish». English satisfies both documents | RULES clause 5 |
| 4 | Submission format and channel | Platform **HackTribe**. Mandatory: project name, team name, team composition (1–6), project description, **PDF presentation of up to 10 slides**. Optionally allowed: screenshots, repository, demo links, graphic materials. **There are no video requirements** | RULES clause 5 |
| 6 | Does Goldman require its own SDK, data or environment | No. «No pre-packaged datasets, proprietary APIs, or specific hardware resources are provided»; there will be no paid subscriptions; OSS libraries and local models (Ollama) are expected | CRIETRIA section 7 |
| 7 | Technical requirements for video | **Question withdrawn** — video is not a submission requirement | RULES clause 5 |
| 8 | Are external LLM services and data egress allowed | Paid services are not provided; the system must be designed to run on its own hardware. Offline mode is not a compromise but the expected form | CRIETRIA section 7 |

## New questions (raised 2026-10-03)

| # | Question | Why it matters | Status |
|---|---|---|---|
| 11 | **Submission deadline: 11:00 or 23:00 on 4 October?** | RULES clause 5 says «11:00 PM» for both dates, whereas the event schedule gives 11:00 for the start and the deadline, and the finalist announcement at 15:00 on 4 October. Taking RULES literally, the deadline is 12 hours later, but then judging would be impossible | Open. **We plan by the earlier time — 11:00** |
| 12 | Which criteria weights apply: RULES (20/10) or CRIETRIA (15/15)? | The discrepancy is confirmed in both PDFs. The impact is small — the order of priorities is the same | Open |
| 13 | Are the repository and the demo link counted separately, or only as attachments to the PDF? | Determines whether the demo must be fitted inside the 10 slides | Open |
| 14 | Formal submission limits: PDF size, description length, naming format | The submission could be rejected on formal grounds | Open |
| 15 | Are there restrictions on using ready-made OSS solutions in the layer (licences)? | CRIETRIA explicitly asks to check licences; we need to know whether any classes are prohibited | Open. **The rule in force: check the licence of every borrowed component** |
| 16 | **Which real model profile should be used for semantic control: a local OSS model or an external OpenAI-compatible provider?** | In `0.1.0` an adapter with a deterministic offline baseline is implemented; the provider profile is disabled because no instruction has been given for external invocations, keys or costs. Without a real profile, the quality of the semantic guardrails (F1 in review 16 (archive reference: `16-mvp-architecture-roast.md`)) remains unmeasured | Open. **The owner's decision is needed before expanding the semantics** |
| 17 | Is a local model (Ollama or similar) available in the judging environment on the judges' machine? | CRIETRIA expects OSS/local models. If no local model is available, the hybrid control demo will depend on an external provider or on an honestly labelled baseline | Open. **Clarify with the mentors** |

## What remains permanently unverified

- The composition and quality of the teams on site — decided by conversation, not by data.
- Mentor availability: the catalogue has no schedule, consultation languages or booking.
- Whether Goldman representatives will be at the track (question 5 — still open, affects the conversation plan, not the project).
- Whether one project can be submitted to several categories (question 3 — still open; decides the fate of Prelint and Defence).
- The exact time zone of the schedule (question 9).
- Whether Goldman has an internal customer ready for a pilot.

## Questions that do not need an answer right now

- Which prize a particular project will receive: the amounts from RULES are a fund for three places (6 000 / 5 000 / 4 000 PLN), not a guarantee to one winner.
- Whether there is a path to hiring through the hackathon: this is a hypothesis, not a condition of the event.


## Clarified in the owner's words — demo focus

**Question:** should the logs and statistics dashboard be made the main advantage of the MVP?

**Answer for our choice of focus:** no. According to the owner's account, a mentor called this typical functionality for which tools such as Grafana already exist. The owner explicitly instructed to avoid focusing on standard solutions (source (archive reference: `../sources/mentor-feedback-2026-10-03.md`)).

**Boundaries:** the priority question for our MVP is closed by the owner's decision. The official criteria are unchanged; the specific non-obvious idea and its novelty remain open.

## Closed 2026-10-03 by the MCP slice implementation

**Fact:** the items that plan 21 (archive reference: `21-dummy-mcp-implementation-plan.md`) §13 left open until the first run have been checked on a live stack. Handoff with evidence (archive reference: `22-mcp-implementation-handoff.md`).

| Question from the plan | What was established | Evidence |
|---|---|---|
| Exact SDK and protocol profile | `mcp==2.3.0`, agreed revision `2025-11-25`, Streamable HTTP in JSON mode without sessions | `python -m unittest tests.test_mcp_profile`, [profile](../app/contracts/mcp-protocol-profile.md) |
| Which MCP host we will use | Our own scenario CLI (`python -m demo_client`): the main demo does not depend on `_meta` support by a third-party host | `make demo-mcp-client` |
| How the operation key is passed | `params._meta["actiongate.demo/operation_key"]` — our extension; a mutation without a key is rejected | phase R01 of the acceptance run |
| Is a client chat needed | Not for this slice: the client runs the tool loop without a model | — |
| Does the owner choose the whole set | All three services are implemented; Tickets remains optional for the main story | `compose.yaml`, `demo-mcp` profile |

**What remains open after this session:** the product choice of web client; latency/CPU/RSS measurements; the behaviour of an arbitrary third-party MCP host; a real semantic model; the owner's choice — whether to submit this slice or not.

## 2026-10-04 — questions after the documentation inventory

**Open documentation question:** the `0.1.0` version in the [invocation contract](../app/contracts/invocation.md) — is it a separate contract version or an outdated heading relative to the `0.2.0` gateway? Before changing the number, verify compatibility and the contract history; [candidate C10](09-documentation-cleanup.md). No answer was established in this session.

## 2026-10-04 — invocation heading question closed

**Source fact:** the [contracts index](../app/contracts/README.md) explicitly defines versioning the contracts together with release 0.2.0; [VERSION](../VERSION) and the [application module](../app/action_gate/__init__.py) contain 0.2.0. Hence the 0.1.0 heading was outdated relative to the documented scope. It has been replaced with `Release scope: 0.2.0`, without any API change or declaration of a separate version. The question from the previous inventory is closed.

## 2026-10-04 — server preparation follow-up

- Pending owner approval: switch SSH to key-only access and enable UFW with TCP 22 allowed. Automatic approval review rejected the bundled security changes due to lockout/disruption risk; the narrower dependency installation succeeded.
- Before public deployment: decide the hostname and TLS/access configuration. The current Compose file binds HTTP to loopback and uses synthetic local operator credentials; it is not an approved public deployment configuration.
- **Proposal, medium confidence:** consider swap or additional RAM after measuring the complete stack. The instance has approximately 2 GB RAM and no swap; no application load test has been run.

## 2026-10-04 — staging first-deployment inputs

- Which operator-controlled contact email should be passed to `deploy-staging.py --email` for ACME? No email was supplied or invented.
- Has `ai-control-gate.ivbon.dev` been pointed to `95.217.5.223`, with public TCP 80/443 reachable and no incompatible AAAA record? DNS and public reachability have not been verified in the preparation session.
- The checkout currently contains uncommitted changes, including staging preparation and earlier documentation edits. Deployment intentionally requires their review, commit and push before it can proceed.

### Follow-up — owner supplied email and Cloudflare DNS

- Resolved email: the owner supplied `ivan.bondar.dev@gmail.com`; it is now the deploy script's default ACME contact.
- DNS configuration evidence: the supplied screenshot shows the requested hostname's A record at `95.217.5.223`, with Cloudflare proxy enabled. This resolves the question of the intended record configuration; public reachability is still unverified.
- Still unverified: Cloudflare SSL/TLS mode (Full strict is required by the runbook), challenge-path rules and origin port reachability. The screenshot does not expose these settings.

### Follow-up — staging deployed and verified

The owner authorized commit, push, deployment and authenticated checks. Origin TLS, public Cloudflare HTTPS readiness, panel API authentication and MCP initialization passed on 2026-10-04. The DNS/reachability deployment prerequisite is satisfied. The Cloudflare dashboard's configured SSL mode was not directly inspected, although both HTTPS paths work. Load and backup/restore verification remain pending.
