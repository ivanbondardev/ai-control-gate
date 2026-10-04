#!/usr/bin/env sh
# Independent evidence snapshot: what the Gate decided and what the services actually stored.
#
# The service side is read over the local admin CLI (a read-only SQLite connection inside the
# container), which is deliberately not a business path a client can use. Customers of this demo read
# and write only through the Gate.
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

compose="docker compose --env-file .env"
profile="${COMPOSE_PROFILE:-demo-mcp}"

echo '=== gate side (PostgreSQL: registry, run, counters, audit) ==='
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --state

for service in documents outbox tickets; do
    echo "=== service side: ${service} ==="
    if $compose --profile "$profile" ps --status running --services 2>/dev/null | grep -qx "${service}-mcp"; then
        $compose exec -T "${service}-mcp" python -m dummy_mcp.admin --service "$service" inspect
    else
        echo "{\"service\": \"${service}\", \"status\": \"not running\"}"
    fi
done
