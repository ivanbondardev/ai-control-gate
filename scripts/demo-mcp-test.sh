#!/usr/bin/env sh
# Acceptance run for the MCP slice against the running stack.
#
# The plan's matrix needs three kinds of action that a client cannot perform: installing a fault rule,
# restarting a container and activating a policy change. Each is done here on the host through the
# documented operator paths, and the client-side observation is always made through the Gate.
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

compose="docker compose --env-file .env --profile demo-mcp"
# Default to fresh volumes and a random loopback port, never the rehearsal database.
if [ "${DEMO_MCP_TEST_IN_PLACE:-0}" != 1 ]; then
    export COMPOSE_PROJECT_NAME="mcp-test-$(date -u +%Y%m%d%H%M%S)-$$"
    export TRAEFIK_HTTP_PORT=0
    trap '$compose down --volumes --remove-orphans' EXIT
    ./scripts/demo-mcp-secrets.sh
    $compose up -d --build --wait
    $compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --publish
    $compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --apply-principals
    DEMO_MCP_TEST_IN_PLACE=1 "$0"
    exit $?
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
evidence="$root/evidence/demo-mcp-$stamp"
mkdir -p "$evidence"

failures=0

phase() {
    name="$1"; shift
    echo "--- phase: $name"
    if $compose exec -T gate-mcp python tests/acceptance/mcp_acceptance.py "$@" \
            > "$evidence/$name.json" 2> "$evidence/$name.err"; then
        echo "    ok"
    else
        echo "    FAILED (see $evidence/$name.json)"
        failures=$((failures + 1))
    fi
    cat "$evidence/$name.json" 2>/dev/null | tail -n +1 | grep -E '"failed"|"id"|"ok"' | head -5 >/dev/null || true
}

service_admin() {
    service="$1"; shift
    $compose exec -T "${service}-mcp" python -m dummy_mcp.admin --service "$service" "$@"
}

gate() {
    $compose exec -T gate-mcp python -m action_gate.mcp_ops "$@"
}

echo '=== unit suites (inside the image) ==='
if $compose exec -T gate-mcp python -m unittest discover -s tests > "$evidence/unit.log" 2>&1; then
    tail -3 "$evidence/unit.log"
else
    cat "$evidence/unit.log"
    exit 1
fi

echo '=== bootstrap: the panel policy is applied idempotently before the checks ==='
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --apply-panel-policy \
    > "$evidence/panel-policy.json"
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --scenario baseline \
    > "$evidence/scenario-baseline.json"

echo '=== P, D, O, F: protocol, admission, policy refusals, output controls ==='
phase p --phase p
phase d --phase d
phase o --phase o
phase f --phase f

echo '=== O03/O04 and D01 on the service side: the stored row is the independent proof ==='
service_admin outbox inspect > "$evidence/outbox-after-o.json"
if $compose exec -T gate-mcp python tests/acceptance/service_checks.py /dev/stdin outbox \
        < "$evidence/outbox-after-o.json"; then
    echo '    ok: the internal recipient is stored exactly and no external message exists'
else
    echo '    FAILED: the stored mailbox does not match the policy decision'
    failures=$((failures + 1))
fi

echo '=== C02: a comparison and activation must not dispatch ==='
before="$(service_admin documents inspect | python3 -c 'import json,sys; print(sum(row["count"] for row in json.load(sys.stdin)["calls"]))')"
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --scenario update-kb1042 \
    > "$evidence/scenario-update-kb1042.json"
after="$(service_admin documents inspect | python3 -c 'import json,sys; print(sum(row["count"] for row in json.load(sys.stdin)["calls"]))')"
echo "{\"before\": $before, \"after\": $after}" > "$evidence/c02-no-dispatch.json"
if [ "$before" != "$after" ]; then
    echo '    FAILED: the policy change reached the service'
    failures=$((failures + 1))
else
    echo '    ok: no service call happened during compare/activate'
fi

echo '=== D after the operator change: the same call is now permitted for one document ==='
phase d-after --phase d-after

echo '=== D01/D02 on the service side: the document rows are the independent proof ==='
service_admin documents inspect > "$evidence/documents-after-d.json"
if $compose exec -T gate-mcp python tests/acceptance/service_checks.py /dev/stdin documents \
        < "$evidence/documents-after-d.json"; then
    echo '    ok: exactly the granted document changed, the protected one did not'
else
    echo '    FAILED: the stored documents do not match the policy decision'
    failures=$((failures + 1))
fi

echo '=== T: tickets, when the third service is running ==='
phase t --phase t

echo '=== R01: repeat key, conflict, one commit ==='
phase r --phase r

echo '=== R02: commit then lost response, then reconciliation ==='
service_admin outbox clear-faults > /dev/null
service_admin outbox fault --mode commit_then_drop_response --tool send_message
key="acc-r02-$(date -u +%s)"
phase unknown --phase unknown --key "$key"
operation_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["operationId"])' "$evidence/unknown.json")"
echo "    unknown operation: $operation_id"
gate reconcile > "$evidence/reconcile.json"
phase reconciled --phase reconciled --operation-id "$operation_id"
service_admin outbox clear-faults > /dev/null

echo '=== R02 (restart): a Gate restart reconciles without a new dispatch ==='
service_admin outbox fault --mode commit_then_drop_response --tool send_message
key="acc-r02b-$(date -u +%s)"
phase unknown-restart --phase unknown --key "$key"
operation_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["operationId"])' "$evidence/unknown-restart.json")"
$compose restart gate-mcp > /dev/null
sleep 3
gate reconcile > "$evidence/reconcile-after-restart.json"
phase reconciled-restart --phase reconciled --operation-id "$operation_id"
service_admin outbox clear-faults > /dev/null

echo '=== R03: restart a dummy with the same volume ==='
service_admin documents inspect > "$evidence/documents-before-restart.json"
$compose restart documents-mcp > /dev/null
sleep 3
service_admin documents inspect > "$evidence/documents-after-restart.json"
if python3 - "$evidence/documents-before-restart.json" "$evidence/documents-after-restart.json" <<'PY'
import json
import sys
before, after = (json.load(open(path)) for path in sys.argv[1:3])
assert before['receipts'] == after['receipts'], 'receipts changed'
assert before['state']['documents'] == after['state']['documents'], 'state changed'
assert before['activeRunId'] == after['activeRunId'], 'run changed'
print('reinstated state and receipts match exactly')
PY
then
    echo '    ok: state and receipts survived the restart'
else
    echo '    FAILED: a restart changed the stored state'
    failures=$((failures + 1))
fi

echo '=== F02: an effect with an undisclosable result ==='
service_admin documents clear-faults > /dev/null
service_admin documents fault --mode malformed_result --tool read_document
phase f2 --phase f2
service_admin documents clear-faults > /dev/null
echo "    see $evidence/f2.json"

echo '=== F03: a deadline before confirmation stays unknown ==='
# The delay is held inside the service transaction, before its commit: the Gate must not report
# "no effect", and reconciliation is what establishes the truth once the service finishes.
service_admin outbox fault --mode delay_before_commit --tool send_message --delay-ms 7000
phase f03 --phase unknown --key "acc-f03-$(date -u +%s)"
service_admin outbox clear-faults > /dev/null
python3 - "$evidence/f03.json" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1]))
row = next(row for row in payload['checks'] if row['id'] == 'R02-lost-response-is-unknown')
print('unknown outcome recorded:', row['ok'], row['detail'])
raise SystemExit(0 if row['ok'] else 1)
PY

echo '=== A01: audit correlation ==='
operation_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["operationId"])' "$evidence/r.json")"
phase audit --phase audit --operation-id "$operation_id"
$compose exec -T gate-mcp python -m action_gate.mcp_ops reconcile > "$evidence/final-reconcile.json"
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --state > "$evidence/gate-state.json"
for service in documents outbox tickets; do
    service_admin "$service" inspect > "$evidence/service-$service.json"
done

if python3 - "$evidence" <<'PY'
import json
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
load = lambda name: json.loads((root / name).read_text())
r = load('r.json')
receipts = load('service-outbox.json')['receipts']
matches = [row for row in receipts if row['operation_id'] == r['serviceOperationId']]
assert len(matches) == 1 and matches[0]['receipt_id'] == r['receiptId'], 'R01/A01 receipt mismatch'
for name in ('unknown.json', 'unknown-restart.json', 'f03.json'):
    operation = load(name)['serviceOperationId']
    assert sum(row['operation_id'] == operation for row in receipts) == 1, name
f2 = load('f2.json')['serviceOperationId']
assert sum(row['operation_id'] == f2 for row in load('service-documents.json')['receipts']) == 1, 'F02 missing commit receipt'
print('R01/R02/F02/A01: independent service receipts match the tested operations')
PY
then
    echo '    ok: independent receipt correlation'
else
    failures=$((failures + 1))
fi

echo '=== R06/A02: unresolved reset, verified fence, late call and fresh run ==='
$compose exec -T gate-mcp python tests/acceptance/recovery_checks.py pending > "$evidence/fence-target.json"
if DEMO_RUN_ID=run-acceptance-reset ./scripts/demo-mcp-reset.sh > "$evidence/reset-blocked.log" 2>&1; then
    echo 'FAILED: reset accepted an unresolved operation'
    failures=$((failures + 1))
fi
$compose exec -T gate-mcp python tests/acceptance/recovery_checks.py closed > "$evidence/admission-closed.json"
operation_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["operationId"])' "$evidence/fence-target.json")"
SERVICE=outbox OPERATION_ID="$operation_id" ./scripts/demo-mcp-fence.sh > "$evidence/fence-confirmed.json"
$compose exec -T gate-mcp python tests/acceptance/recovery_checks.py late < "$evidence/fence-target.json" > "$evidence/late-dispatch.json"
# Fencing a committed operation must preserve its receipt and succeeded outcome.
operation_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["operationId"])' "$evidence/r.json")"
SERVICE=outbox OPERATION_ID="$operation_id" ./scripts/demo-mcp-fence.sh > "$evidence/fence-committed.json"
DEMO_RUN_ID=run-acceptance-reset ./scripts/demo-mcp-reset.sh > "$evidence/reset-success.log"
for service in documents outbox tickets; do
    service_admin "$service" inspect > "$evidence/reset-$service.json"
done
$compose exec -T gate-mcp python -m action_gate.mcp_bootstrap --state > "$evidence/reset-gate.json"
python3 - "$evidence" <<'PYCODE'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
load=lambda name: json.loads((root/name).read_text())
state=load('reset-gate.json')['runState']
assert state['run_id']=='run-acceptance-reset' and state['admission_open']
for service in ('documents','outbox','tickets'):
    snapshot=load('reset-'+service+'.json')
    assert snapshot['activeRunId']==state['run_id']
    assert not snapshot['receipts']
assert all(row['version']==1 for row in load('reset-documents.json')['state']['documents'])
assert not load('reset-outbox.json')['state']['messages']
print('R06/A02 passed: verified fence, no late commit, same run and fresh seed')
PYCODE
phase p-after-reset --phase p

echo '=== B01: explicit rate refusal ==='
phase b --phase b

echo
if [ "$failures" -eq 0 ]; then
    echo "acceptance finished with no failed phase; evidence in $evidence"
else
    echo "acceptance finished with $failures failed phase(s); evidence in $evidence"
fi
exit "$failures"
