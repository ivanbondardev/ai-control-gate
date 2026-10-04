#!/usr/bin/env bash
# Retry semantics are a Gate MCP extension, not an OpenAI idempotency guarantee.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/common.sh"
initialize_mcp "$GATE_PRINCIPAL" || exit 2
mkdir -p "$RESULT_DIR/first" "$RESULT_DIR/replay" "$RESULT_DIR/conflict"
helper prepare M05 "$RESULT_DIR/first/request.json" "$RUN_ID"
cp "$RESULT_DIR/first/request.json" "$RESULT_DIR/replay/request.json"
python3 - "$RESULT_DIR" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); r=json.loads((p/'first/request.json').read_text())
r['params']['arguments']['body']='Different synthetic content with the same operation key.'
(p/'conflict/request.json').write_text(json.dumps(r,indent=2)+'\n')
PY
for phase in first replay conflict; do
  http_request /mcp "$RESULT_DIR/$phase/request.json" "$RESULT_DIR/$phase" "$GATE_PRINCIPAL"
  [[ "$CURL_EXIT" == 0 && "$HTTP_CODE" == 200 ]] || exit 2
done
python3 - "$RESULT_DIR" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
def load(name):
 r=json.loads((p/name/'response.body').read_text()); assert r.get('id')=='M05'; return r['result']['structuredContent']
a,b,c=map(load,('first','replay','conflict'))
assert a['status']=='succeeded' and b['status']=='succeeded'
assert b['replayed'] is True and a['operation_id']==b['operation_id']
assert a.get('receipt_id') and a['receipt_id']==b.get('receipt_id')
assert c.get('error',{}).get('code')=='idempotency_conflict', 'Missing conflict rejection'
(p/'result.json').write_text(json.dumps({'status':'OBSERVED','security_verified':False,'required_evidence':'Exactly one independently counted Outbox effect and one budget charge.'},indent=2)+'\n')
print('OBSERVED: same operation/receipt on retry; changed content refused; service count pending')
PY
echo "Evidence: $RESULT_DIR"
exit 3
