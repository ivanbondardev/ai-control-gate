# Operator scenarios for the gate control web panel

Date: 2026-10-04. Context: HackYeah 2026, AI Control Layer task.

The document describes eight working situations for an administrator or operator of Action Gate: the trigger for intervention, the sequence of actions and a verifiable result. It is intended for discussing UX, preparing a demonstration and checking the completeness of operator processes.

**The status of all scenarios is proposals, high confidence in their alignment with the task.** These are desired workflows, not confirmation that every step exists in the UI, and not an approved MVP expansion plan. All data examples are synthetic. Action names and UI values are given in English. The division into administrator and operator describes responsibilities in the scenarios, not a confirmed RBAC implementation.

**Source fact:** the task requires centralized policies, input and output controls, budgets, management reporting, audit for the security team, and positive and negative tests. Judges may change configuration live. [Primary source of the task, sections 2–6](../sources/goldman-task/extracted/CRIETRIA%20AI%20Control%20Layer.md).

## 1. Allow a new agent to work with documents

**Proposal, high confidence.**

**Situation:** the team launches an assistant that searches internal documents and prepares answers. It must not delete documents or send messages.

**Administrator actions:**

1. Opens the service catalog, imports the description of Documents actions and checks their parameters.
2. Creates rules for a specific agent: allow `search` and `read`, deny `delete` and Outbox actions.
3. Configures sanitization of sensitive content, allowed models and resource limits.
4. Runs three examples: allowed read, denied delete, read with PII in the response.
5. Reviews the results and activates the policy.

**Expected result:** the agent performs useful work within the defined boundaries. For the denied action there is evidence of non-execution; for the sanitized response, a visible redaction result.

## 2. Change a policy without unexpectedly blocking work

**Proposal, high confidence.**

**Situation:** ordinary contact data must be hidden and passed through, while secrets must be fully blocked.

**Administrator actions:**

1. Creates a draft from the active policy.
2. For PII selects `Redact`, for secrets `Block`; checks application on input and output.
3. Adds examples: safe text, text with a phone number, text with a synthetic key.
4. Compares the current and the proposed policy on the saved test set.
5. Examines each decision change: why `Allow` became `Block`, whether needed protection was lost.
6. Activates the verified version and performs a control request.

**Expected result:** the operator can explain exactly what changed and which requests it affected. An incomplete test run is not presented as a successful check.

## 3. Investigate a suspicious agent invocation

**Proposal, high confidence.**

**Situation:** a blocked request appeared in the log: the agent tried to send document content via Outbox.

**Operator actions:**

1. Finds the event by time, agent, service or request identifier.
2. Opens the details: action, sanitized parameters, policy version, rule and reason for blocking.
3. Determines at which stage the refusal occurred: before the service invocation or after receiving its response.
4. Checks the fact of execution separately from the control decision. In this process, a blocked response is not sufficient evidence that the action did not execute.
5. Reviews related events if they are available; if needed, creates a narrow blocking rule for subsequent attempts.
6. Saves the sanitized evidence and adds the example to the regression tests.

**Expected result:** the conclusion contains specifics: what the agent tried to do, what the gate stopped, whether there was a side effect and what remains unknown.

**Proposed special branch:** when the status is `unknown`, the operator first reconciles the operation state with the service. They do not resend with a new identifier before the state is clarified, in order to avoid a possible duplicate.

## 4. Fix a false positive

**Proposal, high confidence.**

**Situation:** an employee asks for an explanation of prompt injection for training, but the check blocks the very mention of the attack.

**Operator actions:**

1. Opens the blocked event and checks the context.
2. Marks it as a probable false positive and records the rationale.
3. Saves the example as a test with expected `Allow`.
4. Adds a paired negative test — a real attempt to make the agent violate the rules.
5. Prepares a narrow exception or adjusts the specific check.
6. Compares the policies, makes sure the negative test remains blocked, and activates the change.

**Expected result:** the legitimate request works while protection against the corresponding attack is preserved. The `false positive` mark by itself must not change the active policy.

## 5. Analyze a sharp increase in costs

**Proposal, high confidence.**

**Situation:** in a short time the agent spent a significant part of its token budget; new requests receive a refusal.

**Operator actions:**

1. Reviews budget usage over the period and the available allocation by agents and models.
2. Looks for repeated requests, long responses, errors and retries.
3. Distinguishes confirmed consumption from reserved resource and from an unknown result after a timeout.
4. Chooses an action: limit the problematic agent, reduce the response size, or prepare a justified limit increase.
5. Checks behavior at the budget boundary: an allowed request passes, an overage stops before a new costly invocation.

**Expected result:** the cause of the costs is clear and uncontrolled consumption is limited. The cost estimate is marked as an estimate, not a provider invoice.

## 6. Add protection against a new attack pattern

**Proposal, high confidence.**

**Situation:** the team received a description of a dangerous request pattern that is not yet in the checks.

**Administrator actions:**

1. Adds the signature to the draft and notes the source and purpose.
2. Defines the scope: service, action, input or output.
3. Adds an attack example and a similar safe example.
4. Runs a comparison, checks for extra blocking and the execution time of the check.
5. Activates the change and verifies that a clear reason appears in the audit.

**Expected result:** the new rule has a source, a version and tests. Simply adding a line to a list is not considered proof of the protection's effectiveness.

## 7. Roll back a failed policy change

**Proposal, high confidence.**

**Situation:** after activating a new version, required business requests stopped passing.

**Administrator actions:**

1. Correlates the start of the refusals with the activation time.
2. Reviews the version diff and the specific rule that changed the decision.
3. Checks the previous version on the problematic example.
4. Performs a rollback while preserving history.
5. Repeats the allowed and denied control requests.
6. Saves the failed example as a test for the next change.

**Expected result:** work is restored, and the cause and history of the change are preserved. The scenario does not envisage undoing actions the agent has already performed through a policy rollback.

## 8. Prepare a report on the gate's operation

**Proposal, high confidence.**

**Situation:** a manager wants to know whether the agents are working, and the security team wants to know which violations were recorded.

**Operator actions:**

1. Selects the period and checks the completeness of the available data.
2. For the manager, builds a summary: allowed, blocked and sanitized interactions, resource usage, main reasons for refusals.
3. For the security team, exports the sanitized audit: identifiers, time, rules, policy versions, results and execution status.
4. Separately marks false positives and indeterminate results.

**Expected result:** two clear representations of the same events. The number of blocks is not called the number of proven attacks.

## Boundaries of confirmed implementation

**Source fact:** per the integration report, the panel has drafts, compare/activation/rollback, review, save-as-test and replay without executing the action. Replay uses sanitized data and does not reproduce old rate counters; semantic checks remain baseline by default. Importing a service in the described panel does not mean connecting an arbitrary external system; the endpoint is metadata. An external signature feed is not implemented in this integration. [Panel report](../sources/original-panel-integration-2026-10-03.md).

**Source fact:** a newer report confirms the operation of the model proxy, but the panel policy and the legacy configuration do not constitute a single atomic release. The model allowlist is global for authenticated principals, without separate model grants. The cost in the budget is a configured conservative allowance, not a provider invoice. Real generation does not prove the quality of semantic protection. [Proxy report](../sources/model-proxy-implementation-2026-10-04.md).

**Source fact:** in the MCP slice, unknown/reconcile/fence and operation recovery fixes were checked. This does not confirm the presence of the entire investigation process in the web panel. [MCP fixes report](../sources/mcp-fixes-2026-10-04.md).

**Unverified in this session:** the current UI and the end-to-end executability of all eight scenarios. The full process of managing rules, models and budgets through a single screen requires a separate check. This document does not change the runtime, active policies or the approved project scope.

## Proposal for a short hackathon demonstration

**Proposal, high confidence:** combine scenarios 2 → 3 → 4: change the policy, investigate a block, fix a false positive while preserving the negative test. Such a demonstration gives the operator a coherent task: manage protection, explain the gate's decision and verify the consequences of the change. This is a recommendation, not an approved pitch scenario.
