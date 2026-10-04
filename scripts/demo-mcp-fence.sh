#!/usr/bin/env sh
# Resolve the Gate ID, fence the service ID, then verify its authenticated status.
set -eu
cd "$(dirname "$0")/.."
: "${SERVICE:?SERVICE is required}" "${OPERATION_ID:?OPERATION_ID is required}"
compose="docker compose --env-file .env --profile demo-mcp"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
$compose exec -T gate-mcp python -m action_gate.mcp_ops fence-target \
    --operation-id "$OPERATION_ID" > "$work/target.json"
python3 - "$work/target.json" "$SERVICE" <<'PY'
import json,sys
row=json.load(open(sys.argv[1]))
assert row['service'] == sys.argv[2], 'SERVICE does not match the operation'
PY
upstream_id="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["upstreamOperationId"])' "$work/target.json")"
run_id="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["runId"])' "$work/target.json")"
$compose exec -T "$SERVICE-mcp" python -m dummy_mcp.admin --service "$SERVICE" \
    fence --operation-id "$upstream_id" --run "$run_id"
$compose exec -T gate-mcp python -m action_gate.mcp_ops confirm-fence --operation-id "$OPERATION_ID"
