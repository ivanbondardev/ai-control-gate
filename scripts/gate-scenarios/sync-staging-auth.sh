#!/usr/bin/env bash
# Fetch only Gate client identities. Provider credentials stay on the server.
set -euo pipefail
umask 077
root="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$root/secrets/staging-client"
chmod 700 "$root/secrets/staging-client"
tmp=$(mktemp "$root/secrets/staging-client/.principals.XXXXXX")
trap 'rm -f "$tmp"' EXIT
ssh -i "$HOME/.ssh/grisha_htz_id_ed25519" -o BatchMode=yes -o StrictHostKeyChecking=yes \
    root@95.217.5.223 'cat /opt/action-gate/shared/secrets/staging/principals.json' > "$tmp"
python3 - "$tmp" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1]))['principals']
assert {'support-agent','observer-agent','operator-local'} <= {row['id'] for row in rows}
assert all(isinstance(row['token'],str) and row['token'] for row in rows)
PY
chmod 600 "$tmp"
mv "$tmp" "$root/secrets/staging-client/principals.json"
echo 'Staging Gate client credentials saved privately; no token values printed.'
