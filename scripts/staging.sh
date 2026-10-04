#!/usr/bin/env bash
# Explicit configuration prevents accidental use of the local demo project or provider keys.
set -euo pipefail
cd "$(dirname "$0")/.."
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES
if [[ ! -f .env.staging || ! -f secrets/staging/principals.json || ! -f secrets/staging/credentials.json ]]; then
    echo 'Run python3 scripts/staging-init.py --email YOUR_EMAIL on the staging server first.' >&2
    exit 2
fi
# Ignore inherited interpolation variables, including provider keys and database settings.
while IFS='=' read -r key rest; do
    [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] && unset "$key"
done < .env.staging
compose=(docker compose --env-file .env.staging -p action-gate-staging -f compose.yaml -f compose.staging.yaml --profile demo-mcp)
case "${1:-config}" in
    config) "${compose[@]}" config --quiet ;;
    up)
        "${compose[@]}" config --quiet
        "${compose[@]}" up -d --build --wait
        "${compose[@]}" ps
        ;;
    bootstrap)
        "${compose[@]}" exec -T gate-mcp python -m action_gate.mcp_bootstrap --publish
        "${compose[@]}" exec -T gate-mcp python -m action_gate.mcp_bootstrap --apply-principals
        "${compose[@]}" exec -T gate-mcp python -m action_gate.mcp_bootstrap --apply-panel-policy
        "${compose[@]}" ps
        ;;
    status) "${compose[@]}" ps ;;
    logs) "${compose[@]}" logs --tail=100 ;;
    stop) "${compose[@]}" stop ;;
    *) echo 'Usage: scripts/staging.sh {config|up|bootstrap|status|logs|stop}' >&2; exit 2 ;;
esac
