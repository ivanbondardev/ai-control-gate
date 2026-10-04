#!/usr/bin/env bash
# Read-only readiness. Does not call the LLM or prove that /v1/responses is implemented.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/common.sh"
for route in /health/ready /v1/me; do
  name="${route##*/}"
  http_request "$route" - "$RESULT_DIR/$name" "$GATE_PRINCIPAL"
  [[ "$CURL_EXIT" == 0 && "$HTTP_CODE" == 200 ]] || { echo "BLOCKED: $route (HTTP $HTTP_CODE, curl $CURL_EXIT)"; exit 2; }
done
python3 - "$RESULT_DIR/me/response.body" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); assert isinstance(r,dict)
PY
echo 'Readiness and caller endpoint reachable; model proxy and provider key are NOT verified.'
echo "Evidence: $RESULT_DIR"
