#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
case "${1:---help}" in
  --list) exec python3 "$here/support.py" list ;;
  --check) exec python3 "$here/support.py" check ;;
  --help) cat <<'TXT'
Usage:
  run.sh --list | --check
  OPENAI_MODEL=<enabled-model> run.sh --case L01
  OPENAI_MODEL=<enabled-model> run.sh --profile baseline
  run.sh --case M02

Runs on the host with Bash, curl and Python; default Gate URL: https://ai-control-gate.ivbon.dev.
Set GATE_BASE_URL=http://localhost to explicitly use the local demo.
Profiles are operator-prepared preconditions, not installed by this script.
OPENAI_MODEL is required for model requests; provider key stays on Gate.
Exit: 1 assertion failure; 2 blocked; 3 client checks observed, evidence pending.
No retries, redirects, provider emulator, automatic policy changes or full-suite spending loop.
TXT
    exit 0 ;;
  --case|--profile) [[ $# == 2 ]] || exit 2; kind="${1#--}"; [[ "$kind" != case ]] || kind=id; value="$2" ;;
  *) echo 'Use --help' >&2; exit 2 ;;
esac
source "$here/common.sh"
helper select "$kind" "$value" > "$PRIVATE_DIR/selected"
mkdir -p "$RESULT_DIR"
stop_reason=""
while IFS= read -r id; do
  group="$(helper field "$id" group)"
  profile="$(helper field "$id" profile)"
  # A single ID is also an explicit choice of the documented policy preconditions.
  echo "$id requires policy profile: $profile"
  principal="$(helper field "$id" principal "$GATE_PRINCIPAL")"
  auth_mode="$(helper field "$id" auth normal)"
  folder="$RESULT_DIR/$id"
  mkdir -p "$folder"
  if [[ -n "$stop_reason" ]]; then
    printf '{"case":"%s","status":"BLOCKED","reason":"Earlier transport or endpoint failure; not attempted"}\n' "$id" > "$folder/result.json"
    continue
  fi
  if ! helper prepare "$id" "$folder/request.json" "$RUN_ID"; then
    printf '{"case":"%s","status":"BLOCKED","reason":"Request preparation failed; inspect configuration"}\n' "$id" > "$folder/result.json"
    continue
  fi
  path=/v1/responses
  if [[ "$group" == mcp ]]; then
    path=/mcp
    if ! initialize_mcp "$principal"; then
      printf '{"case":"%s","status":"BLOCKED","reason":"MCP initialization failed"}\n' "$id" > "$folder/result.json"
      continue
    fi
  fi
  http_request "$path" "$folder/request.json" "$folder" "$principal" "$auth_mode"
  helper validate "$id" "$folder" "$HTTP_CODE" "$CURL_EXIT" || true
  if [[ ! -f "$folder/result.json" ]]; then
    printf '{"case":"%s","status":"FAIL","reason":"Validator failed without a result"}\n' "$id" > "$folder/result.json"
  fi
  # Endpoint absence blocks the model profile without sending the remaining paid requests.
  if [[ "$CURL_EXIT" != 0 || ( "$group" != mcp && ( "$HTTP_CODE" == 404 || "$HTTP_CODE" == 405 ) ) ]]; then stop_reason=unavailable; fi
done < "$PRIVATE_DIR/selected"
echo "Evidence: $RESULT_DIR"
helper summary "$RESULT_DIR"
