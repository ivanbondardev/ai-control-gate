#!/usr/bin/env sh
# Bring the MCP demonstration slice up and bootstrap it.
#
# Order matters and mirrors the plan: credentials first (the containers mount them read-only), then
# the stack, then the registry revision, then the panel policy, then the demonstration principals.
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

compose="docker compose --env-file .env"

"$root/scripts/demo-mcp-secrets.sh"

echo '-> starting the stack with the demo-mcp profile'
$compose --profile demo-mcp up -d --build --wait

echo '-> publishing the registry revision'
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --publish

echo '-> applying the demonstration transport principals'
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --apply-principals

echo '-> applying the panel services, rules and tests'
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --apply-panel-policy

echo '-> state'
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --state
