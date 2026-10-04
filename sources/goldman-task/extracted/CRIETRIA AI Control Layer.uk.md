---
source: organizer-task
source_role: primary-reference
source_confirmed_by: owner
title: "AI Control Layer task and criteria — unofficial English translation"
from: "../_inbox/CRIETRIA AI Control Layer.pdf"
method: translation-to-en
translated: 2026-10-03
language: en
fidelity: translation
---

**Primary source of the organizers' task — status determined by the owner on 2026-10-03.** This file is an unofficial English translation of the source; for exact formulations, refer to the English extraction and the PDF.

Source: [CRIETRIA AI Control Layer.pdf](<../_inbox/CRIETRIA AI Control Layer.pdf>). [English text](<CRIETRIA AI Control Layer.md>). Unofficial English translation. The provisions below are a translation of the source's statements, not an independent confirmation of their validity. Discrepancies of the original are preserved.

<!-- Page 1 -->

# AI Control Layer — the AI control layer

Build a flexible AI control layer to protect and govern interactions with agentic AI systems (AI agents, MCP services, large language models — LLMs, APIs). This layer will help organizations protect data, apply the necessary guardrails, manage API budgets, and block emerging exploits while maintaining developer speed. Create the ultimate hybrid defense system for the generative AI era!

## 1. Introduction — organization, context and current state

Modern organizations continuously improve the security of their infrastructure and foster safe technological innovation. They work to enable developers and employees to adopt cutting-edge technologies such as AI safely, without compromising data privacy, financial budgets, or, more broadly, the security of the organization. The goal is to bridge the gap between the need for rapid software development and cybersecurity controls and practices.

Today developers make extensive use of AI and agentic AI in their work: to write code, draft documents, and analyze data. Likewise, AI and agentic AI systems are widely used to support or fully automate numerous business processes. This significantly increases productivity, but at the same time creates risks that traditional security tools are not always ready for.

When adopting AI and agentic AI, organizations face new problems.

In particular, agentic systems need more modern and more dynamic authentication and access-control mechanisms. Without local enforcement, agentic systems can easily gain access to resources they should not have access to, impersonate other actors, and perform harmful and irreversible actions.

Input validation and output filtering are another critical risk area. Unlike traditional applications with structured inputs, AI systems interpret natural language as execution logic, which makes them especially vulnerable to attacks such as prompt injection. On the output side, the absence of rigorous filtering means that AI systems can return sensitive data.

In addition, organizations find it difficult to manage access to memory and resource consumption, especially in autonomous agentic workflows. When agents rely on persistent context or shared memory stores, they can cause unauthorized data retrieval or get trapped in runaway execution loops. Because of their non-deterministic behavior, they can unexpectedly consume an excessive amount of resources.

To counter these risks, organizations need robust and comprehensive AI controls (often called guardrails) that can be implemented and enforced through a flexible and adaptive control layer, such as a smart intermediary. Such a layer must instantly inspect, redact unsafe content, or block unsafe interactions in real time, combining traditional policy enforcement with AI-supported enforcement.

Note: the potential threats listed above are only examples of risks in agentic systems.

<!-- Page 2 -->

When designing the control layer, you should deeply analyze the AI ecosystem, review the available sources (for example, OWASP), and determine which additional controls are needed for a comprehensive defense system that is ready for production use and capable of countering emerging risks and threats.

## 2. Challenge

Your task is to build a lightweight, flexible AI control layer. It can be implemented as a gateway, proxy, middleware, or SDK wrapper that intercepts and governs interactions with AI systems. This layer must enforce the security, privacy, and resource controls defined in or provided by a centralized configuration source (for example, in a control catalogue). The layer must be able to produce reporting for security teams and management, for example through a user interface or in another way.

For an optimal balance between speed and deep semantic understanding, the control layer must implement a hybrid defense architecture, using both non-AI (deterministic) controls and AI-based (semantic) controls.

In addition, when designing, think about how to ensure sufficient resilience of the layer to manage the budgets of both external commercial APIs and locally hosted models, and how it can detect or mitigate known historical attacks on AI infrastructure. This refers, in particular, to the ability to receive signatures of such attacks from an externally managed system.

To prove the reliability and robustness of the solution, you must also provide a complete automated test suite that demonstrates both positive (allowed) and negative (blocked or redacted) cases for the implemented controls.

## 3. Expected Outcome

1. **AI Control Layer:** a functional gateway, proxy, middleware, SDK wrapper, or other component that developers can easily integrate into AI systems, for example into "agent — agent", "application — agent", "agent — MCP", "agent — model" interactions, and so on.

   a) To demonstrate the solution, you can build your own agent OR use an already existing one.

   b) You should provide a simple diagram of the solution's architecture.

2. **Sample Configuration:** a documented policy file that configures the controls and guardrails and demonstrates different configurable strictness/adherence levels and budget rules for those controls.

<!-- Page 3 -->

3. **Simple Interactive Dashboard:** a UI displaying controls, overall security posture, blocked threats, and other metrics, for example resource consumption and cost.

4. **Executable Test Suite:** a ready-to-run test suite that verifies the implementation of your controls, including budget limits and exploit mitigation.

## 4. Formal Requirements

1. **Centralized Policy Engine:** a single configuration source, for example a file or system, that manages controls, sensitivity thresholds (blocking or redacting content, or the adherence percentage), allowed LLM models, and resource and financial budgets.

2. **Controls / Guardrails:**

   1. **Deterministic (Non-AI):** for example, pattern matching to detect personally identifiable information (PII) or secrets, checking authentication or access requirements, and so on.
   2. **Semantic (AI-Based):** where possible, consider using AI-based solutions or a model to secure interactions with AI systems.

3. **Budget and Resource Governance:** when designing the control layer, think about how to enforce budget limits, for example regarding resource access, compute time, or token spend for access to LLMs.

4. **Historical Attack Mitigation:** think about how to detect and block patterns associated with successful historical exploits against AI systems, such as malicious code execution, unsafe deserialization, or supply-chain exploits targeting model repositories.

5. **Security Reporting & Auditing:** real-time metrics for management (blocked interactions, budget usage) and exportable audit logs for security teams to analyze threats, policy violations, and system usage. It can be implemented as a dedicated dashboard or in another way.

6. **Self-Testing Suite:** an automated test suite that verifies both positive (allowed) and negative (blocked) cases for the controls.

## 5. Technical Requirements

Teams have complete freedom in choosing their technology stack: solutions can be built from scratch in languages such as Go, Rust, or Python, or built on top of existing open-source tools. Be sure to check the licenses of these tools. For the agents, LLMs, and applications that will use your control layer, pre-existing tooling can be used: agents, applications, and other components that are not directly related to the task will not be assessed.

<!-- Page 4 -->

## 6. Testing and/or Validation Approach

The evaluation relies primarily on the materials provided by the team itself and on spontaneous actions without prior preparation. The judges will run the automated test suite provided by the team, so make sure that it allows the implemented controls to be tested. The suite must contain both positive and negative test cases to prove that the system works as intended.

The judges may interactively test the running control layer in real time, using spontaneous, ad-hoc prompts and observing how the system reacts. They may modify the configuration files or input feeds of your control layer, for example changing rules, removing controls, or adjusting thresholds, in order to understand how the layer behaves with a new configuration: how changes are reflected, whether they can be applied in real time, and so on. You must be able to provide performance telemetry, since it may be used for evaluation.

The judges will also review the overall architecture, dashboards, and logging information that can be provided to management and security teams.

## 7. Available Resources

No pre-packaged datasets, proprietary APIs, or special hardware resources are provided for this challenge. This is intentional, to give teams complete architectural freedom and to avoid the constraints of static synthetic data. Teams are expected to use publicly available open-source libraries where necessary, local models (for example, those run via Ollama), and their own test prompts to demonstrate and validate the control layer. Subscriptions to paid services, for example OpenAI, Anthropic, Copilot, and so on, will not be provided for this challenge, so make sure that you can design, build, and run the entire system on your own hardware and in your own environment.

## 8. Evaluation Criteria

For a balanced assessment of technical execution and practical utility, projects will be evaluated by the following criteria:

- Robustness of the solution and quality of guardrails — 30%.
- Architecture and performance efficiency — 20%.
- Security reporting — 20%.
- Completeness of the self-testing suite — 15%.
- Practical implementability and scalability — 15%.
