# HTTP contracts

**Implementation fact:** below are the contracts of gateway `0.2.0` and the separate server surface of the restored original frontend. The panel contract records implemented behavior, not the result of a not yet completed check run.

| Document | What it records | Implementation |
|---|---|---|
| [invocation.md](invocation.md) | one guarded invocation: request, response, three separate responses (input decision, action outcome, output disclosure), status mapping, idempotency scoped to a principal, audit boundaries | [gateway.py](../action_gate/gateway.py), [contracts.py](../action_gate/contracts.py) |
| [configuration.md](configuration.md) | policy lifecycle: snapshot, draft, compare, activate, rollback, export/import, bootstrap | [config_service.py](../action_gate/config_service.py), [snapshot.py](../action_gate/snapshot.py), [evaluation.py](../action_gate/evaluation.py) |
| [reporting.md](reporting.md) | reporting: a single window for all metrics, pagination, latency, ownership, audit export | [http_server.py](../action_gate/http_server.py), [storage/](../action_gate/storage) |
| [control-panel.md](control-panel.md) | the original visual/YAML builder: drafts, access rules, compare/activate, local synthetic invocations, catalog, sanitized replay, reviews and JSONL export; a separate policy from the legacy gateway | [panel_service.py](../action_gate/panel_service.py), [panel_engine.py](../action_gate/panel_engine.py), [panel.js](../static/control/panel.js) |
| [mcp-protocol-profile.md](mcp-protocol-profile.md) | MCP compatibility profile: protocol revision, Streamable HTTP transport in JSON mode without sessions, authentication to the transport, `_meta` as a control channel, verified SDK 2.x limitations | [mcp_server.py](../action_gate/mcp_server.py), [dummy_mcp/common/service.py](../dummy_mcp/common/service.py) |
| [mcp-tool-contracts.md](mcp-tool-contracts.md) | tool contracts of the three dummy services: schemas, receipts, error dictionary, limits, two hops with different dictionaries | [dummy_mcp/](../dummy_mcp/), [service_registry.py](../action_gate/service_registry.py) |
| [mcp-operations.md](mcp-operations.md) | one operation: durable claim, idempotency and conflicts, unknown/reconcile/fence, reset, limits, audit format and two independent evidence channels | [execution.py](../action_gate/execution.py), [storage/operations.py](../action_gate/storage/operations.py), [mcp_ops.py](../action_gate/mcp_ops.py) |

**Panel boundary:** activation via `/v1/panel/*` changes the behavior of `/v1/panel/invoke`, but not `/v1/invocations` and not `/v1/config/*`. The shared server, identity registry and storage do not make the policies and the compare evidence interchangeable. [Contract and implementation sources](control-panel.md).

**What changed from `0.1.0`:** `releaseHash` now describes the rules actually executed, not the bytes of the files; an invocation holds a single immutable snapshot; `PUT /v1/config/drafts/{id}` and the rest of the lifecycle routes were added; the idempotency key is scoped to a principal; `GET /v1/invocations` and `GET /v1/audit/events` were added; the reporting window is validated rather than silently accepted. Historical descriptions — in the 0.1.0 handoff (archive reference: `../../docs/18-release-0.1.0-handoff.md`).

**Boundary, high confidence:** the contracts are versioned as `0.2.0` together with the release. This is not a frozen public API: authentication is local and synthetic, and TLS, OIDC and a production-grade role model are out of scope. A breaking change requires a new contract version, not a silent edit.

**Proposal, high confidence:** add new routes only together with a recorded intent of who calls them (an agent, an operator or a service check), what evidence they provide and which test confirms this. A route without such a connection must not expand the attack surface of the gate. The full list of open questions is in the [decision log](../../docs/07-open-questions.md).

- [OpenAI Responses model proxy](model-proxy.md): implemented profile, policy, budgets, buffered SSE and operator setup.
