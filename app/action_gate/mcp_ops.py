"""Operator CLI for the durable MCP side of the Gate.

These are the only paths that can resolve an operation the Gate could not finish, and none of them
re-dispatches a stored request:

``reconcile``
    Read the service receipt for every unknown operation in the active run. A receipt resolves the
    operation as succeeded-withheld; a missing receipt leaves it visible as unknown.
``close-admission`` / ``open-admission``
    Stop and restart new admissions. A reset closes admission first and only reopens it once the Gate
    and every service report the same run id.
``set-run``
    Move the Gate to a new demonstration run. This does not touch a service: the reset script moves
    both sides and verifies they agree.
``confirm-fence``
    After the local admin CLI of a service has fenced an operation id as having no effect, record the
    same terminal decision for the Gate operation. The fence itself must happen inside the service
    container, where the write lock lives.
``status``
    Print one operation row and its audit events.
"""
import argparse
import asyncio
import json
import os
import sys

from .execution import ExecutionCoordinator
from .identity import Principal
from .mcp_upstream import McpUpstream
from .policy_reader import PanelPolicyReader
from .service_registry import ServiceRegistry
from .storage.operations import STATUS_FAILED, TERMINAL_STATUSES, build_operations

OPERATOR = Principal(id='operator-local', role='operator', token='')


class McpOperator:
    def __init__(self, environ=None):
        from .http_server import GateApplication
        self.environ = dict(os.environ if environ is None else environ)
        self.core = GateApplication(self.environ)
        if self.core.repository is None:
            raise SystemExit(f'storage is unavailable: {self.core.startup_error}')
        self.operations = build_operations(self.core.repository)
        self.policy_reader = PanelPolicyReader(self.core.repository)
        credentials_path = self.environ.get('DEMO_CREDENTIALS_FILE') or '/run/demo/credentials.json'
        from dummy_mcp.common.auth import load_credentials
        credentials = load_credentials(credentials_path)
        allowed = self.environ.get('APP_MCP_ALLOWED_HOSTS')
        allowed_hosts = ({host.strip() for host in allowed.split(',') if host.strip()}
                         if allowed else {'documents-mcp', 'outbox-mcp', 'tickets-mcp'})
        allowlist_path = self.environ.get('APP_MCP_ALLOWLIST') or str(
            self.core.policy_dir + '/mcp_services.json')
        allowlist = ServiceRegistry.load_allowlist(allowlist_path, allowed_hosts=allowed_hosts)
        self.upstream = McpUpstream(credentials)
        self.registry_service = ServiceRegistry(allowlist, credentials, self.operations,
                                                self.upstream, allowed_hosts=allowed_hosts)
        self.coordinator = ExecutionCoordinator(
            operations=self.operations, policy_reader=self.policy_reader,
            registry_provider=self.registry_service.active, upstream=self.upstream,
            salt=self.core.salt or self.environ.get('APP_HASH_SALT', 'local-development-salt'))

    def reconcile(self):
        return asyncio.run(self.coordinator.reconcile())

    def admission(self, open_state, note=None):
        return self.operations.set_run_state(admission_open=open_state, note=note)

    def set_run(self, run_id, note=None):
        return self.operations.set_run_state(run_id=run_id, note=note)

    def fence_target(self, operation_id):
        row = self.operations.get(operation_id)
        if row is None:
            raise SystemExit(f'unknown operation {operation_id}')
        upstream_id = row.get('upstream_operation_id')
        if not upstream_id:
            raise SystemExit('operation has no durable upstream ID; fence refused')
        return {'operationId': str(row['id']), 'service': row['service_id'],
                'upstreamOperationId': upstream_id, 'runId': row['demo_run_id']}

    def confirm_fence(self, operation_id, *, kind='cancelled_no_effect', actor='operator-local',
                      note=None):
        target = self.fence_target(operation_id)
        row = self.operations.get(operation_id)
        registry = self.registry_service.active()
        binding = registry.binding(row['published_tool']) if registry else None
        if binding is None or binding.service_id != target['service']:
            raise SystemExit('operation service is unavailable in the registry')
        status = asyncio.run(self.upstream.operation_status(
            binding.status_endpoint, binding.service_id, target['upstreamOperationId'],
            credential_id=binding.credential_id))
        if status.get('operationId') != target['upstreamOperationId']:
            raise SystemExit('service returned a different operation ID')
        if status.get('status') == 'committed':
            receipt = status.get('receipt') or {}
            if receipt.get('demo_run_id') != target['runId'] or not receipt.get('receipt_id'):
                raise SystemExit('service receipt does not match the operation run')
            confirmed = asyncio.run(self.coordinator._probe_receipt(
                row, binding, target['upstreamOperationId']))
            if confirmed is None:
                raise SystemExit('committed receipt could not be confirmed')
            return {'operationId': operation_id, 'status': 'succeeded',
                    'receiptId': confirmed['receipt_id']}
        fence = status.get('fence') or {}
        if (status.get('status') != 'no_effect' or fence.get('demo_run_id') != target['runId']
                or fence.get('kind') != kind):
            raise SystemExit('no matching service fence; outcome remains unresolved')
        if row['status'] in TERMINAL_STATUSES:
            return {'operationId': operation_id, 'status': row['status']}
        finished = self.operations.finish(operation_id, {
            'status': STATUS_FAILED, 'decision': 'allow',
            'reason': f'operator fence: {kind}', 'disclosure': 'none',
            'error_code': 'operator_fence'})
        self.operations.release(operation_id, 'operator fence')
        self.operations.audit({
            'operation_id': operation_id, 'demo_run_id': row['demo_run_id'],
            'principal_id': row['principal_id'], 'published_tool': row['published_tool'],
            'upstream_tool': row['upstream_tool'], 'service_id': row['service_id'],
            'policy_version': row.get('policy_version') or 1,
            'policy_hash': row.get('policy_hash') or '',
            'registry_revision': row.get('registry_revision') or 1, 'decision': 'allow',
            'reason': f'operator fence: {kind}', 'effect_outcome': 'no_effect',
            'disclosure': 'none', 'receipt_id': None, 'request_id': None,
            'detail': {'fenceKind': kind, 'actor': actor, 'note': note,
                       'upstreamOperationId': target['upstreamOperationId']}})
        return {'operationId': operation_id, 'status': finished['status'], 'fence': kind}

    def assert_reset_ready(self):
        # No pagination limit: every unresolved row must prevent a run transition.
        with self.operations._cursor() as cursor:
            cursor.execute('SELECT id, status FROM mcp_operations '
                           'WHERE demo_run_id = %s AND NOT (status = ANY(%s))',
                           (self.operations.run_state()['run_id'], list(TERMINAL_STATUSES)))
            pending = cursor.fetchall()
        if pending:
            raise SystemExit(f'reset blocked by {len(pending)} unfinished operation(s)')
        return {'ready': True}

    def status(self, operation_id):
        row = self.operations.get(operation_id)
        if row is None:
            return {'operationId': operation_id, 'found': False}
        return {'operationId': operation_id, 'found': True,
                'operation': {key: row.get(key) for key in
                              ('status', 'decision', 'disclosure', 'published_tool',
                               'upstream_tool', 'resource_id', 'receipt_id', 'attempts',
                               'policy_version', 'registry_revision', 'demo_run_id')},
                'counters': self.operations.counters(row['demo_run_id'])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='action_gate.mcp_ops', description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('reconcile', help='read receipts for unknown operations')
    subparsers.add_parser('assert-reset-ready', help='refuse reset while any operation is unfinished')
    target = subparsers.add_parser('fence-target', help='resolve the trusted service operation ID')
    target.add_argument('--operation-id', required=True)
    admission = subparsers.add_parser('close-admission', help='refuse new admissions')
    admission.add_argument('--note', default=None)
    reopen = subparsers.add_parser('open-admission', help='accept new admissions again')
    reopen.add_argument('--note', default=None)
    run = subparsers.add_parser('set-run', help='move the Gate to another demonstration run')
    run.add_argument('--run', required=True)
    run.add_argument('--note', default=None)
    fence = subparsers.add_parser('confirm-fence', help='record a terminal no-effect outcome')
    fence.add_argument('--operation-id', required=True)
    fence.add_argument('--kind', default='cancelled_no_effect')
    fence.add_argument('--note', default=None)
    status = subparsers.add_parser('status', help='print one operation row')
    status.add_argument('--operation-id', required=True)
    arguments = parser.parse_args(argv)

    operator = McpOperator()
    if arguments.command == 'reconcile':
        payload = operator.reconcile()
    elif arguments.command == 'fence-target':
        payload = operator.fence_target(arguments.operation_id)
    elif arguments.command == 'assert-reset-ready':
        payload = operator.assert_reset_ready()
    elif arguments.command == 'close-admission':
        payload = operator.admission(False, arguments.note or 'operator closed admission')
    elif arguments.command == 'open-admission':
        payload = operator.admission(True, arguments.note or 'operator opened admission')
    elif arguments.command == 'set-run':
        payload = operator.set_run(arguments.run, arguments.note)
    elif arguments.command == 'confirm-fence':
        payload = operator.confirm_fence(arguments.operation_id, kind=arguments.kind,
                                         note=arguments.note)
    else:
        payload = operator.status(arguments.operation_id)
    json.dump(payload, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
