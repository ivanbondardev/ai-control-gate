# A 3-minute demo

Updated: 2026-10-03. The same scenario is used both for the live demonstration and for the video — the only difference is who is speaking.

> **Historical document (marked 2026-10-03, 16:00).** The scenario **is not performed**: the implementation it is built on was **deleted** on 3 October 2026. There is nothing to show the scenes with `allow` / `deny` / `escalate`, redaction and live configuration changes with. The code remains in the git history (commit `52f1d87`).

**What changed.** Two lines of defence were added: **content** (items 5–6) and **action** (items 2–4). The video is no longer a mandatory artifact — the main submission artifact is a **PDF of up to 10 slides** ([submission-outline.md](submission-outline.md)). This scenario remains for the live demonstration in front of the judges.

## Before you start

- One screen open, nothing extra on the desktop.
- The policy open in a second tab — for scene 4 (changing a rule live).
- **If the live provider is enabled, check that it responds.** If not — the demo runs on recorded responses, and this is visible on the screen, not hidden.
- A timer on the screen or in your head: 3:00.
- Know the three numbers by heart (they are in scene 7).

## Scenario

| Time | What is on the screen | What the presenter says |
|---|---|---|
| 0:00–0:15 | The slide with the Goldman risks | “Agents read untrusted content and act. The risks: data disclosure, unauthorised actions, unpredictable costs. Traditional security tools do not cover them” |
| 0:15–0:45 | **Scene 1.** Proposal → `allow` → execution → record | “The agent proposes refunding within the limit. The layer checks the permissions, the resource and the amount. Allowed, executed, no human involved” |
| 0:45–1:15 | **Scene 2.** Over the limit → `deny` with a reason | “The same action, but the amount is over the limit. The action did not happen — here is the rule that stopped it” |
| 1:15–1:45 | **Scene 3.** `escalate` → queue → approval → execution | “Above the threshold it goes to a human. After approval it executes exactly once: a repeat event does not double the effect” |
| 1:45–2:10 | **Scene 4.** Injection → `deny`; we edit the rule live → the same action goes through | “The agent asks to expand its permissions. It does not go through. Now I change the rule — and only now is the action allowed. The decision is in the policy, not in the prompt” |
| 2:10–2:35 | **Scene 5 (content).** A card number in the prompt → `redact` → “before/after” → we show what exactly went to the provider | “Here is what matters most for the bank: the agent sees the card number, the layer hides it **before** it leaves the perimeter. Here is what actually went to the model. The raw data did not leave the perimeter” |
| 2:35–2:50 | **Scene 6 (semantic control).** Social engineering in the rationale → a signal with confidence → the policy blocks by threshold | “The model says: this looks like social engineering, confidence 0.8. It neither allows nor forbids — the threshold in the file decides. That is why this can be tested” |
| 2:50–3:00 | The panel: three numbers + tokens spent | “The cost of control: N attack attempts — zero executions; p95 decision — X ms; Y% of actions with no additional human step at all; Z redactions” |

## What must be visible in each scene

- **Scene 1:** the time from proposal to execution; the absence of a human step.
- **Scene 2:** the name of the rule that fired, and what is needed for the action to be allowed.
- **Scene 3:** who approved, when, what was executed; the idempotency marker.
- **Scene 4:** the difference between “the agent asked” and “the policy allowed”; the reaction within seconds of editing the file.
- **Scene 5:** the **before** and **after** fragments of the redaction side by side; it is visible that the provider received the cleaned text. If the content did not leave at all — that appears as `block`, not `redact`.
- **Scene 6:** **the signal and the decision are different lines on the screen.** Signal: class and confidence. Decision: rule and threshold. This is the answer to “why the model does not decide”.

## Scene 7 (separate, if the judges ask)

**The judge changes the configuration live** — this is named directly in the task («may modify the configuration files/feeds … can they adjust in real-time»). Three actions to choose from:

| Action | What should happen |
|---|---|
| Change the sensitivity threshold | The verdict changes from `redact` to `block` (or vice versa) |
| Remove a control | The layer **does not fall over**; the decision changes; the record remains |
| Break the YAML | **400 with an explanation**, the last working policy stays in force. Not 500 |

Prepare this scene in advance and **check it by hand** before going out — this is the behaviour the judge notices most.

## Fallback options

| What breaks | What to do |
|---|---|
| **No network or key** | The demo runs on recorded model responses. The layer shows “semantic control unavailable” — **honestly, not hidden** |
| The provider responds differently than in the rehearsal | We discuss **the policy decision based on the signal**, not the signal itself. That is our thesis |
| The provider is slow | We show latency as a separate number — this is also the telemetry the task asks for |
| The UI crashes | A second tab with the same scenario or a terminal run of `make demo` |
| We run out of time to show scene 6 | We show scene 5 and separately describe the semantic signal from the slide |
| The judge asks for something that does not exist | An honest answer + a line in “limits”. Do not improvise a feature on stage |

## Shot list for the video (appendix, not a requirement)

The video is not required by the rules. If you record one — after the mandatory artifacts are ready.

1. The first screen with the timeline (5 s).
2. Scene 1 in full (10 s).
3. Scene 2 with a zoom-in on the rule name (10 s).
4. **Scene 5: the redaction “before/after” — the most valuable shot for the bank (20 s).**
5. **Scene 6: the signal and the decision on one screen (15 s).**
6. Scene 4: the injection and the rule change (20 s).
7. The panel with the numbers (10 s).
8. The final shot: the thesis in one sentence (5 s).
