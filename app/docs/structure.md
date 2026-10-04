# Action Gate structure

Map of the current copy as of 2026-10-04. The application version is `0.2.0` per [VERSION](../../VERSION) and the [version module](../action_gate/__init__.py). Below are the existing files and the boundaries from the contracts; this is not a report of a new runtime run.

## Directories

| Directory | Purpose |
|---|---|
| [action_gate/](../action_gate/) | HTTP, policies, enforcement, MCP, proxy, reporting and storage |
| [dummy_mcp/](../dummy_mcp/) | Synthetic Documents, Outbox, Tickets and shared transport/state |
| [demo_client/](../demo_client/) | Scenario MCP client |
| [static/](../static/) | Legacy workbench and the `/control/` panel |
| [policy/](../policy/) | Bootstrap/import configuration; the separate panel seed is [panel_seed.json](../panel_seed.json) |
| [contracts/](../contracts/README.md) | API and behavior boundaries of each path |
| [migrations/](../migrations/README.md) | Six PostgreSQL migrations |
| [tests/](../tests/) | Unit, HTTP, integration and acceptance checks |
| [scripts/](../../scripts/) | Launch, UI checks, MCP and the [scenario client](../../scripts/gate-scenarios/README.md) |
| [infra/](../../infra/) | Traefik routes and PostgreSQL init explanation; launch — [Compose](../../compose.yaml) |

## Execution paths and policies

| Surface | Main modules | Boundary |
|---|---|---|
| `/v1/invocations`, `/v1/config/*` | [gateway.py](../action_gate/gateway.py), [config_service.py](../action_gate/config_service.py), [snapshot.py](../action_gate/snapshot.py), [evaluation.py](../action_gate/evaluation.py) | Active legacy snapshot from PostgreSQL; draft/compare/activate/rollback; synthetic Document Desk |
| `/v1/panel/*` | [panel_service.py](../action_gate/panel_service.py), [panel_engine.py](../action_gate/panel_engine.py) | Separate panel policy and state; synthetic invoke, compare, review and replay |
| `/mcp` | [mcp_server.py](../action_gate/mcp_server.py), [execution.py](../action_gate/execution.py), [mcp_upstream.py](../action_gate/mcp_upstream.py) | Panel controls, verified registry, controlled dispatch to dummy services |
| MCP lifecycle | [service_registry.py](../action_gate/service_registry.py), [mcp_ops.py](../action_gate/mcp_ops.py), [mcp_bootstrap.py](../action_gate/mcp_bootstrap.py) | Catalog publication, reconcile/fence/reset; an unknown outcome does not mean the absence of an effect |
| `/v1/responses` | [model_proxy.py](../action_gate/model_proxy.py), [model_proxy_setup.py](../action_gate/model_proxy_setup.py) | Records the panel policy and the legacy release separately; a real provider when configured; buffered SSE |
| Reporting | [operator_reporting.py](../action_gate/operator_reporting.py), [http_server.py](../action_gate/http_server.py) | Consistent event representations do not merge policy lifecycle into a single release |

Transport and tool schema compatibility — in the [MCP profile](../contracts/mcp-protocol-profile.md) and [tool contracts](../contracts/mcp-tool-contracts.md). Shared identity and storage do not make compare evidence from different surfaces interchangeable.

## Shared modules

- [identity.py](../action_gate/identity.py) — identity from transport; local principals are not production IAM.
- [content.py](../action_gate/content.py), [detectors.py](../action_gate/detectors.py), [config_bundle.py](../action_gate/config_bundle.py) — content checks, detector profiles and configuration documents. The offline baseline is not a trained model.
- [budget.py](../action_gate/budget.py), [audit.py](../action_gate/audit.py), [services.py](../action_gate/services.py) — reservations, sanitized audit and the synthetic action of the legacy path.
- [storage/](../action_gate/storage/) — PostgreSQL, memory, config store, operations and Redis runtime. The memory backend does not prove durability.
- [migrate.py](../action_gate/migrate.py) — linear SQL migrations with a session advisory lock and an application journal; there is no automatic downgrade.

## How to continue

**Proposal, high confidence:** tie changes to a specific surface, its contract and tests. Do not attribute MCP guarantees to the model proxy or to a legacy invocation without a separate check. Semantic quality, performance and a new run of the copy remain separate work; the current boundaries are [transfer](../../docs/transfer.md), [questions](../../docs/07-open-questions.md), [scenario matrix](../../docs/23-bash-scenario-matrix.md).
