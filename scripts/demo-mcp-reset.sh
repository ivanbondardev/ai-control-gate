#!/usr/bin/env sh
# Demonstration reset: move the Gate and every dummy service to a new run id.
#
# Order is the contract from the plan:
#   1. close admission (no new operation may start);
#   2. reconcile unfinished operations (a receipt resolves them, a missing receipt blocks the reset);
#   3. move every service to the new run id and re-seed;
#   4. move the Gate and reopen admission only when both sides report the same run id.
#
# Evidence of the previous run is preserved: a service reset starts a new run and keeps the previous
# receipts, and the Gate archives nothing away.
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

run_id="${DEMO_RUN_ID:?DEMO_RUN_ID is required, for example DEMO_RUN_ID=run-0002}"
compose="docker compose --env-file .env --profile demo-mcp"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Closing admission is durable. Any failure leaves it closed for operator recovery.
$compose exec -T gate-mcp python -m action_gate.mcp_ops close-admission --note "reset to $run_id"
$compose exec -T gate-mcp python -m action_gate.mcp_ops reconcile > "$work/reconcile.json"
$compose exec -T gate-mcp python -m action_gate.mcp_ops assert-reset-ready

# All configured demo services are required, including when retrying a partial reset.
for service in documents outbox tickets; do
    $compose exec -T "$service-mcp" python -m dummy_mcp.admin --service "$service" run > "$work/$service-before.json"
done
for service in documents outbox tickets; do
    $compose exec -T "$service-mcp" python -m dummy_mcp.admin --service "$service" reset --run "$run_id" --note "operator reset" > "$work/$service-reset.json"
done
for service in documents outbox tickets; do
    $compose exec -T "$service-mcp" python -m dummy_mcp.admin --service "$service" run > "$work/$service.json"
done
python3 - "$work" "$run_id" <<'PYCODE'
import json, pathlib, sys
for service in ('documents', 'outbox', 'tickets'):
    row = json.loads((pathlib.Path(sys.argv[1]) / (service + '.json')).read_text())
    assert row['runId'] == sys.argv[2], f'{service}: run mismatch; admission stays closed'
PYCODE
$compose exec -T gate-mcp python -m action_gate.mcp_ops set-run --run "$run_id" --note "verified service reset"
$compose exec -T gate-mcp python -m action_gate.mcp_ops open-admission --note "reset to $run_id complete"
echo "reset complete: $run_id"
