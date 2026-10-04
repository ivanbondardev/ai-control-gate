#!/usr/bin/env sh
# Evidence bundle for a demonstration run: before/after snapshots, the policy and catalog revisions
# and the sanitized audit trail, in one directory that can be attached to a report.
#
# Nothing here contains a credential: audit rows carry decisions, identifiers and durations, and the
# credential file is never read by this script.
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

label="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
bundle="$root/evidence/bundle-$label"
compose="docker compose --env-file .env --profile demo-mcp"
mkdir -p "$bundle"

echo "-> gate state, registry revision and audit rows"
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --state > "$bundle/gate-state.json"

echo "-> independent service state and receipts"
for service in documents outbox tickets; do
    if $compose ps --status running --services 2>/dev/null | grep -qx "${service}-mcp"; then
        $compose exec -T "${service}-mcp" python -m dummy_mcp.admin --service "$service" inspect \
            > "$bundle/service-$service.json"
    fi
done

echo "-> published tool schemas and catalog mapping"
# The payload is printed on stdout so the file can be created on the host: the container has no
# access to the host's evidence directory.
$compose exec -T gate-mcp python - <<'PY' > "$bundle/catalog.json"
import json

from action_gate.mcp_bootstrap import Bootstrap
from action_gate.storage.operations import build_operations

operations = build_operations(Bootstrap().core.repository)
row = operations.active_registry()
document = row['document'] if row and isinstance(row['document'], dict) else (
    json.loads(row['document']) if row else None)
payload = {'revision': row['revision'] if row else None,
           'documentHash': row.get('document_hash') if row else None,
           'services': []}
for service in (document or {}).get('services', []):
    payload['services'].append({
        'serviceId': service['service_id'], 'health': service['health'],
        'tools': [{'publishedName': tool['published_name'],
                   'upstreamName': tool['upstream_name'],
                   'panelService': tool['panel_service'],
                   'panelAction': tool['panel_action'],
                   'schemaHash': tool['schema_hash'],
                   'reviewRequired': tool.get('review_required', False)}
                  for tool in service['tools']]})
print(json.dumps(payload, indent=2, sort_keys=True))
PY

echo "-> service health as the Gate last saw it"
$compose exec -T gate-mcp python -c "
import json, sys
from action_gate.mcp_ops import McpOperator
json.dump(McpOperator().operations.service_health(), sys.stdout, indent=2, sort_keys=True, default=str)
" > "$bundle/health.json"

echo '-> files'
ls -la "$bundle"
echo "bundle written to $bundle"
