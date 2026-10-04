#!/usr/bin/env bash
# Read-only reporting snapshot with one fixed UTC window and bounded pagination.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/common.sh"
REPORT_PRINCIPAL="${REPORT_PRINCIPAL:-operator-local}"
mkdir -p "$RESULT_DIR"
python3 - "$PRIVATE_DIR/window" <<'PY'
from datetime import datetime,timedelta,timezone
from pathlib import Path
import os,sys
from urllib.parse import urlencode
end=datetime.now(timezone.utc); start=end-timedelta(minutes=15)
since=os.environ.get('REPORT_SINCE',start.isoformat()); until=os.environ.get('REPORT_UNTIL',end.isoformat())
assert datetime.fromisoformat(since).utcoffset() is not None and datetime.fromisoformat(until).utcoffset() is not None
assert datetime.fromisoformat(since)<datetime.fromisoformat(until)
Path(sys.argv[1]).write_text(urlencode({'since':since,'until':until}))
PY
window="$(cat "$PRIVATE_DIR/window")"
http_request "/v1/summary?$window" - "$RESULT_DIR/management" "$REPORT_PRINCIPAL"
[[ "$CURL_EXIT" == 0 && "$HTTP_CODE" == 200 ]] || exit 2
cursor=''
for page in {1..20}; do
  query="$(python3 - "$window" "$cursor" <<'PY'
import sys
from urllib.parse import urlencode
print(sys.argv[1]+'&'+urlencode({'limit':1000,**({'cursor':sys.argv[2]} if sys.argv[2] else {})}))
PY
)"
  http_request "/v1/audit/export?$query" - "$RESULT_DIR/audit-$page" "$REPORT_PRINCIPAL"
  [[ "$CURL_EXIT" == 0 && "$HTTP_CODE" == 200 ]] || exit 2
  cursor="$(python3 - "$RESULT_DIR/audit-$page" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); headers={}
for line in (p/'response.headers').read_text().splitlines():
 if ':' in line:
  k,v=line.split(':',1); headers[k.lower()]=v.strip()
for line in (p/'response.body').read_text().splitlines():
 if line.strip():
  event=json.loads(line); assert isinstance(event,dict) and 'kind' in event
truncated=headers.get('x-action-gate-truncated')
assert truncated in ('true','false'), 'Missing pagination metadata'
if truncated=='true':
 assert headers.get('x-action-gate-next-cursor'), 'Truncated without cursor'
 print(headers['x-action-gate-next-cursor'])
PY
)"
  [[ -n "$cursor" ]] || break
done
[[ -z "$cursor" ]] || { echo 'BLOCKED: audit exceeds 20 pages; narrow the report window'; exit 2; }
python3 - "$RESULT_DIR" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); summary=json.loads((p/'management/response.body').read_text())
assert 'window' in summary and 'budget' in summary and 'invocations' in summary
(p/'result.json').write_text(json.dumps({'status':'OBSERVED','security_verified':False,'required_evidence':'Check model and MCP coverage, correlation, redaction, policy versions, counters and provider usage. A valid legacy report alone does not prove model-proxy coverage.'},indent=2)+'\n')
print('OBSERVED: management snapshot and complete audit export for one fixed window')
PY
echo "Evidence: $RESULT_DIR"
exit 3
