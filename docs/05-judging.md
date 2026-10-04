# AI Control Layer judging criteria

Updated 2026-10-04. The requirements below are taken from the preserved [English extracts](../sources/goldman-task/extracted/README.md). The weights and wording are not an assessment of Action Gate's readiness. The previous assessment of the old prototype, the design proposals and the judges' answers are preserved in the [dated archive](archive/2026-10-03/judging.md).

## Judging criteria (source fact)

| Criterion | RULES, clause 11 | CRIETRIA, section 8 |
|---|---:|---:|
| Robustness of the Solution and Quality of Guardrails | 30% | 30% |
| Architecture and Performance Efficiency | 20% | 20% |
| Security Reporting | 20% | 20% |
| Completeness of the Self-Testing Suite | **20%** | **15%** |
| Practical Implementability and Scalability | **10%** | **15%** |

**Source fact:** the weights for Self-Testing and Practical differ. The final clarification remains in the [open questions](07-open-questions.md); this document does not set new weights.

## How the judges will check (CRIETRIA, section 6) — read before every run

| Mechanism | Verbatim | Implication for us |
|---|---|---|
| Judges run our test suite | «Judges will execute the automated test suite provided by the team» | Prepare a reproducible `make test` run per the [README](../README.md); the transfer results and skips are in [transfer](transfer.md) |
| Spontaneous actions | «spontaneous, zero- preparation actions» | The demo must not depend on a pre-warmed state |
| Live ad-hoc prompts | «interactively test the running control layer in real time using spontaneous, ad-hoc prompts» | **The biggest risk.** The layer must react to arbitrary text, not only to structured invocations |
| Configuration change | «may modify the configuration files/feeds … changing rules, removing controls, adjusting thresholds … can they adjust in real-time» | Live policy reload is mandatory; removing a control must not break the layer |
| Telemetry | «You should be able to produce performance telemetry as it may be used for evaluation» | Latency and metrics on screen, not in the log |

**Proposal, high confidence:** the «Implication for us» column is an interpretation for demo preparation, not an additional requirement from the organizers or a promise of a score.

## Where to check the implementation and the evidence

| Surface | Contract | Dated evidence and boundaries |
|---|---|---|
| Protected invocations and configuration | [invocation](../app/contracts/invocation.md), [configuration](../app/contracts/configuration.md) | [Checks on this copy](transfer.md), [log](../sources/export-unit-tests.log) |
| Panel and reporting | [panel](../app/contracts/control-panel.md), [reporting](../app/contracts/reporting.md) | [Integration](../sources/original-panel-integration-2026-10-03.md), [fixes](../sources/operator-fixes-2026-10-04.md) |
| MCP and operation recovery | [operations](../app/contracts/mcp-operations.md) | [MCP fixes](../sources/mcp-fixes-2026-10-04.md) |
| Model proxy | [Responses](../app/contracts/model-proxy.md) | [Implementation report](../sources/model-proxy-implementation-2026-10-04.md) |

**Boundary:** the existence of code or of a historical run does not prove that all criteria are met. The quality of the semantic guardrails, the performance and the full set of scenarios are not confirmed by this review. The new runtime was not started in the cleanup session. Scenario preparation is in the [matrix](23-bash-scenario-matrix.md); the submission decision belongs to the owner.
