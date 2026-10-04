#!/usr/bin/env bash
# Send a user-authored Responses request through the same Gate transport.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
[[ $# == 1 && -f "$1" ]] || { echo 'Usage: ad-hoc.sh /path/to/responses-request.json' >&2; exit 2; }
request_file="$1"
source "$here/common.sh"
mkdir -p "$RESULT_DIR/ad-hoc"
python3 - "$request_file" "$RESULT_DIR/ad-hoc/request.json" <<'PY'
import json,sys
from pathlib import Path
r=json.loads(Path(sys.argv[1]).read_text())
assert isinstance(r,dict) and isinstance(r.get('model'),str) and r['model'] and 'input' in r
assert not {'api_key','Authorization','token','provider_api_key'} & set(r), 'Credentials do not belong in the request body'
Path(sys.argv[2]).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
PY
http_request /v1/responses "$RESULT_DIR/ad-hoc/request.json" "$RESULT_DIR/ad-hoc" "$GATE_PRINCIPAL"
echo "HTTP $HTTP_CODE, curl $CURL_EXIT; no predefined verdict for this prompt. Evidence: $RESULT_DIR"
[[ "$CURL_EXIT" == 0 ]] || exit 2
exit 3
