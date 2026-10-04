# Main DB migrations

Updated 2026-10-04 per the [runner](../action_gate/migrate.py) and the SQL in this directory. A separate `migrate` job in [Compose](../../compose.yaml) runs the runner; the API and MCP ingress wait for `service_completed_successfully`. The [Dockerfile](../Dockerfile) itself does not apply migrations. This description is not a new run against PostgreSQL.

## Schema composition

| Migration | Purpose |
|---|---|
| [0001_init.sql](0001_init.sql) | Initial schema of invocations, audit, budgets, effects and synthetic documents |
| [0002_idempotency_claim.sql](0002_idempotency_claim.sql) | Idempotency key claim, overdraft and budget scope |
| [0003_policy_lifecycle.sql](0003_policy_lifecycle.sql) | Release snapshot, drafts and activations, principal-scoped claims and provenance |
| [0004_control_panel.sql](0004_control_panel.sql) | Separate JSON state of the original panel in `control_panel_state` |
| [0005_mcp_registry.sql](0005_mcp_registry.sql) | MCP registry versions, one active revision and service state |
| [0006_remote_operations.sql](0006_remote_operations.sql) | Durable MCP operations, attempts, audit, concurrency reservations and demo run state |

## Runner behavior

**Code fact:** `python -m action_gate.migrate` reads `*.sql` in name order, uses `schema_migrations` to track applied files and skips already applied versions. The directory can be set via `APP_MIGRATIONS_DIR`. The session-level `pg_advisory_lock` is held for the duration of the run until the connection closes, so that two runners do not apply the same file simultaneously.

**Boundaries:** this runner performs no automatic downgrade or checksum verification of already applied SQL. File new changes under the next number; editing applied SQL will not make the runner execute it again. Do not delete volumes or live data to apply a migration.

## Policies and state

**Contract fact:** after bootstrap, the active legacy release and its documents are stored in PostgreSQL; `app/policy/` is a bootstrap/import format, not the live source of policy. See [configuration](../contracts/configuration.md). The panel has a separate state and lifecycle, see [control-panel](../contracts/control-panel.md). The model proxy records both snapshots but does not make them a single atomic release — [model-proxy](../contracts/model-proxy.md).

Audit, ledger and claims cannot be restored by clearing Redis; the guarantees and boundaries of a specific path are described in [invocation](../contracts/invocation.md) and [MCP operations](../contracts/mcp-operations.md). Historical checks of the copy — in [transfer](../../docs/transfer.md).
