# Pitch: lines to use

Updated: 2026-10-03. All texts for delivery are in English; Ukrainian is used only for internal understanding.

> **Historical document (marked 2026-10-03, 16:00).** The texts assume a working demo that was **deleted** on 3 October 2026. The wordings «I already have the action half running» and «the half already works» are untrue for the current state. Before use in the submission the texts must be rewritten. The code remains in the git history (commit `52f1d87`).

**What changed compared with 2 October.** The criteria are known: Robustness+Guardrails 30%, Architecture 20%, Security Reporting 20%, Self-Testing 20/15%, Practical 10/15%. **The novelty of the idea and the screen design are not assessed at all** — so the pitch is built not on “what a good idea this is”, but on “here is what works and here is how it is proven”. The task requires **hybrid** protection, so the wording “no model needed” has been replaced with “the model is a detector, the policy is the arbiter”.

## The main sentence (one for the whole project)

> **Everything passes through one layer: content is redacted before it leaves, actions are decided before they run.** Deterministic policy makes the call; the model supplies a signal, never a verdict — and every step leaves tamper-evident evidence. Control is what makes wider autonomy safe, not what slows it down.

Ukrainian rendering: everything passes through one layer — content is hidden before it leaves, actions are decided before they run. A deterministic policy makes the decision; the model gives a signal, not a verdict. Control is what allows agents to be given more rights, not what takes them away.

## The key distinction you must be able to say out loud

> *We do use a model — as a detector, not as a judge. It tells us "this looks like social engineering, confidence 0.8". It never tells us "allow this". The threshold lives in the policy file, which is why we can test it and replay it.*

This is the answer to two different judges' questions: “why the decision is not in the model” **and** “where is the semantic control that the task requires”. Both answers — in one sentence.

## 30 seconds — for recruiting the team (historically: with the prototype on the screen; there has been no prototype since 3 October 2026)

> «Everything an agent reads and everything it does goes through one layer. Content gets redacted before it reaches an external model. Actions get decided before they execute — allow, block, or escalate. I already have the action half running: allowed, blocked, and approved-after-escalation, with a hash-chained audit trail. I'm adding the content half now. I need someone who knows what an auditor would accept, and someone who can make the screen obvious in three seconds.»

Ukrainian rendering: the half already works; I am looking for someone from risk/compliance and a frontend developer.

## 30 seconds — three opening options for the judges

**If the customer is an AI platform / developer productivity:**
> «Your developers already run agents against real repositories and systems. Today the only two options are full access or no access. We built the missing third option: a layer agents cannot go around — policy-enforced execution at the tool boundary, with zero added steps for the routine 80%, and content redaction before anything leaves your perimeter.»

**If the customer is cyber / identity:**
> «An agent is not a user and not a service account. It reads untrusted content, it can be manipulated, and it acts. We give it an owner, a scoped credential with an expiry, a policy decision point in front of every action — and we redact sensitive content before it reaches any external model. The raw data never leaves.»

**If the customer is risk / compliance / AI governance:**
> «Every interaction produces something you can defend: which control fired, which rule applied, who approved, what actually happened — in a tamper-evident record you can hand to an auditor. And when the model is unavailable, the layer says so instead of pretending. Control here is evidence, not vibes.»

## 60 seconds — the full pitch

1. **The problem (in their words).** Agents read untrusted content and act: they touch resources and run complex processes. The risks: data disclosure, unauthorised actions, unpredictable costs. Traditional security tools do not cover this.
2. **The gap.** The existing options are either a log that merely describes, or a blanket ban that stops the work. And the task requires a **hybrid**: deterministic controls **and** semantic ones.
3. **Our solution — two lines of defence.** Content: a deterministic scan for PII and secrets, redaction **before** it leaves, a semantic signal. Action: a decision point in the execution path. The model gives a signal — the policy decides. A human sees only the exceptions.
4. **Demo.** Six scenes: allowed · blocked · escalated and approved · the attack does not get through · **PII redaction before it leaves** · **semantic signal → policy decision**.
5. **Evidence.** N attack attempts → 0 executions; M redactions; p95 decision time separate from provider latency; tokens spent; the share of actions with no additional human step at all.
6. **Limits.** Mock tools, simplified policies, no real IAM; the semantic control is not a production-grade classifier. An honest list builds trust.
7. **The ask.** “Is there any point in showing this to someone at your company, and who could we talk to next week?”

## Supporting quotes — answers to the judges

Rule: every line below is a **source fact**: this is how it was heard in the auto-captions of a talk at the AI Engineer conference. A quote confirms that the direction has already been named in the community, not that we are right. Before public use, verify against the primary recording (link at the end). Names and organisations are taken from the talk titles or from the speakers' own words; where a name is not heard in the recording, it is an attribution from the title, not from the stage. **None of the quotes relates to a version of the MCP specification** — across the 35 talks in the folder the version is never named, so no claims about specification compliance should be built on them.

**1. “The protocol does not provide a control plane” — on the question “doesn't MCP itself do this?”**

> "The protocol itself doesn't enforce like specific observability." — Mahesh Murag, Anthropic
> "The client is responsible for dealing with that information." — David Soria Parra, Anthropic

What to say: *MCP guarantees the wire, not the control plane — and the client is explicitly responsible for what happens next. That is the layer we built.*

**2. “A gateway in front of tool invocations is an already-named pattern”**

> "a tool in between … filters which servers it has access to" — Mahesh Murag, Anthropic
> "enforcing policy", "ban malicious servers" — John Welsh, Anthropic (talking about an MCP gateway)

What to say: *We are not inventing a category. We are adding the mechanics: ordered rules, default deny, escalation, receipts.*

**3. “An error is a prompt” — on the question why the gate rewrites the tool's response**

> "errors are prompts" — Jeremiah Lowin, Prefect / FastMCP
> "Examples are contracts" — same talk

What to say: *The gate hands the model a normalized error and keeps the raw server text in the audit trail.*

**4. “The host is in charge” — on the question “what if it is an MCP client?”**

> "the host decides what to do" — Ido Salomon & Liad Yosef, MCP Apps
> "the control is in the hands of the host" — the same speakers, a second recording of the same talk

What to say: *In our layer the decision is not in the host and not in the model: it is in a file a human signed.*

**5. “A registry is not trust”**

> "simply having a registry doesn't solve the problem" — Henry Mao, Smithery

What to say: *A server catalog is not trust. The gate evaluates the action, not the vendor.*

**6. “Default deny is not exotic”**

> "you start with something that has no capabilities" — Sunil Pai, Cloudflare
> "They're blocked by default" — RL Nabors, WebMCP

What to say: *Default deny is the same construction principle, applied to business actions.*

**Sources (AI Engineer conference auto-captions; verify before public use):**

| Abbreviated | Talk | URL |
|---|---|---|
| Murag, Anthropic | Building Agents with Model Context Protocol | <https://www.youtube.com/watch?v=kQmXtrmQ5Zg> |
| Soria Parra, Anthropic | The Future of MCP | <https://www.youtube.com/watch?v=v3Fr2JR47KA> |
| Welsh, Anthropic | Remote MCPs: What we learned from shipping | <https://www.youtube.com/watch?v=0NHCyq8bBcM> |
| Lowin, Prefect | Your MCP Server is Bad (and you should feel bad) | <https://www.youtube.com/watch?v=96G7FLab8xc> |
| Salomon & Yosef | MCP Apps: Extending the Frontier | <https://www.youtube.com/watch?v=-jY2T2PiJBE> |
| Pai, Cloudflare | Code Mode: Let the Code do the Talking | <https://www.youtube.com/watch?v=8txf05vVVl4> |
| Nabors, WebMCP | Introducing WebMCP: Agents in the Browser | <https://www.youtube.com/watch?v=LMbeDEQO6QM> |
| Mao, Smithery | Are MCPs Overhyped? A Rant about MCPs | <https://www.youtube.com/watch?v=tOou_GJ9Ddk> |

The full analysis is in ../talks/mcp-and-ai-agents/synthesis.md (archive reference: `../talks/mcp-and-ai-agents/synthesis.md`); notes on each talk are in `talks/mcp-and-ai-agents/notes/`.

## Phrases not to use

- “AI safety platform” — too broad, it reads as “nothing specific”.
- **“We use AI to check AI”** — you cannot say that, but denying the model is no longer possible either: the task **requires** semantic controls. The correct wording is from the “Key distinction” section above: the model detects, the policy decides. The difference between “the model advises a human” and “the model gives a signal and the threshold lives in a file” is the difference between a lottery and a controlled system.
- **“We do without a model”** — a direct contradiction of requirement CRIETRIA:29. Do not say it.
- “We block everything dangerous” — contradicts the second half of the Goldman question.
- “This can be scaled to the whole bank” — premature; it is better to show one completed scenario.
- “Data does not leave the perimeter” without qualification. The precise wording: **raw data does not leave the perimeter — what leaves is already hidden content.** The difference is fundamental, and it must be said out loud, not left for the judges to guess.
