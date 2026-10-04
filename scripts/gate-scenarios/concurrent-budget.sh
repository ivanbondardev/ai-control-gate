#!/usr/bin/env bash
# Requires an isolated policy budget that admits exactly one of these two reservations.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/common.sh"
: "${OPENAI_MODEL:?Set OPENAI_MODEL}"
mkdir -p "$RESULT_DIR/one" "$RESULT_DIR/two"
helper prepare L01 "$RESULT_DIR/one/request.json" "$RUN_ID-one"
cp "$RESULT_DIR/one/request.json" "$RESULT_DIR/two/request.json"
# Separate transport processes and private headers; fixed fan-out of two, never a load test.
for phase in one two; do
  (
    PRIVATE_DIR="$(mktemp -d)"; trap 'rm -rf "$PRIVATE_DIR"' EXIT
    http_request /v1/responses "$RESULT_DIR/$phase/request.json" "$RESULT_DIR/$phase" "$GATE_PRINCIPAL"
    printf '%s\n' "$CURL_EXIT" > "$RESULT_DIR/$phase/curl-exit"
  ) &
done
wait
python3 - "$RESULT_DIR" "$here" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[2]); from support import response_ok
p=Path(sys.argv[1]); statuses=[]
for phase in ('one','two'):
 d=p/phase; assert (d/'curl-exit').read_text().strip()=='0', 'Transport failed'
 status=int((d/'timing.tsv').read_text().split()[0]); statuses.append(status)
 body=json.loads((d/'response.body').read_text())
 if status==200: response_ok(body)
 elif status==429: assert body.get('error',{}).get('message'), 'Missing limit error'
assert sorted(statuses)==[200,429], f'Expected one admission and one refusal, got {statuses}'
(p/'result.json').write_text(json.dumps({'status':'OBSERVED','security_verified':False,'required_evidence':'Atomic reservation ledger; no overspend; exactly one target-provider dispatch; budget reason on 429.'},indent=2)+'\n')
print('OBSERVED: one admission and one limit; atomic ledger evidence pending')
PY
echo "Evidence: $RESULT_DIR"
exit 3
