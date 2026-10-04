#!/usr/bin/env bash
# Shared transport. No provider credentials are loaded by this client.
set -euo pipefail
umask 077
SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCENARIO_DIR/../.." && pwd)"
GATE_BASE_URL="${GATE_BASE_URL:-http://localhost}"
GATE_BASE_URL="${GATE_BASE_URL%/}"
GATE_PRINCIPAL="${GATE_PRINCIPAL:-support-agent}"
export GATE_PRINCIPAL
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$-${RANDOM}"
RESULT_DIR="${RESULT_DIR:-$REPO_ROOT/evidence/gate-scenarios/$RUN_ID}"
if [[ -d "$RESULT_DIR" ]] && [[ -n "$(ls -A "$RESULT_DIR")" ]]; then
  echo 'RESULT_DIR must be new or empty; refusing to mix evidence from different runs' >&2
  exit 2
fi
for dependency in python3 curl; do
  command -v "$dependency" >/dev/null || { echo "Missing dependency: $dependency" >&2; exit 2; }
done
# Refuse credentials in URLs, fragments, query strings and unexpected URL schemes.
python3 - "$GATE_BASE_URL" <<'PY'
import sys
from urllib.parse import urlsplit
u=urlsplit(sys.argv[1])
assert u.scheme in ('http','https') and u.hostname and not u.username and not u.password and not u.query and not u.fragment, 'Invalid Gate URL'
assert u.hostname != 'api.openai.com', 'Point the client to Gate, not directly to OpenAI'
PY
PRIVATE_DIR="$(mktemp -d)"
trap 'rm -rf "$PRIVATE_DIR"' EXIT
helper() { python3 "$SCENARIO_DIR/support.py" "$@"; }
http_request() {
  local path="$1" body="$2" folder="$3" principal="$4" mode="${5:-normal}"
  mkdir -p "$folder"
  helper auth "$PRIVATE_DIR/headers" "$principal" "$mode"
  local args=(--silent --show-error --connect-timeout 5 --max-time "${REQUEST_TIMEOUT_SECONDS:-60}"
    --proto '=http,https' --max-redirs 0 --header "@$PRIVATE_DIR/headers"
    --dump-header "$folder/response.headers" --output "$folder/response.body"
    --write-out '%{http_code}\t%{time_total}\t%{time_starttransfer}\t%{size_download}\n')
  # Local calls must not be sent to an HTTP proxy inherited from the host environment.
  case "$GATE_BASE_URL" in
    http://localhost|http://localhost:*|https://localhost|https://localhost:*|http://127.0.0.1|http://127.0.0.1:*|https://127.0.0.1|https://127.0.0.1:*)
      args+=(--noproxy '*') ;;
  esac
  if [[ "$path" == /mcp ]]; then args+=(--header 'MCP-Protocol-Version: 2025-11-25'); fi
  if [[ "$body" != '-' ]]; then args+=(--request POST --data-binary "@$body"); fi
  CURL_EXIT=0
  curl "${args[@]}" "$GATE_BASE_URL$path" > "$folder/timing.tsv" 2> "$folder/transport.err" || CURL_EXIT=$?
  HTTP_CODE="$(cut -f1 "$folder/timing.tsv")"
  HTTP_CODE="${HTTP_CODE:-000}"
}
initialize_mcp() {
  local principal="$1"
  printf '%s\n' '{"jsonrpc":"2.0","id":"init","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"gate-bash-scenarios","version":"1.0"}}}' > "$PRIVATE_DIR/init.json"
  http_request /mcp "$PRIVATE_DIR/init.json" "$RESULT_DIR/initialize-$principal" "$principal"
  [[ "$CURL_EXIT" == 0 && "$HTTP_CODE" == 200 ]] || return 2
  python3 - "$RESULT_DIR/initialize-$principal/response.body" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r.get('id') == 'init' and r.get('result',{}).get('protocolVersion') == '2025-11-25', 'MCP negotiation failed'
PY
  printf '%s\n' '{"jsonrpc":"2.0","method":"notifications/initialized"}' > "$PRIVATE_DIR/initialized.json"
  http_request /mcp "$PRIVATE_DIR/initialized.json" "$RESULT_DIR/initialized-$principal" "$principal"
  [[ "$CURL_EXIT" == 0 && "$HTTP_CODE" == 202 ]] || return 2
}
