"""Operator recovery acceptance against an isolated stack, including a delayed old dispatch."""
import asyncio
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from action_gate.mcp_ops import McpOperator


def main():
    operator = McpOperator()
    mode = sys.argv[1]
    state = operator.operations.run_state()
    if mode == 'pending':
        binding = operator.registry_service.active().binding('outbox_send')
        policy = operator.policy_reader.read()
        row = operator.operations.claim({
            'demo_run_id': state['run_id'], 'principal_id': 'support-agent',
            'client_operation_key': 'recovery-' + uuid.uuid4().hex,
            'request_fingerprint': uuid.uuid4().hex, 'request_id': 'recovery-test',
            'published_tool': binding.published_name, 'upstream_tool': binding.upstream_name,
            'service_id': binding.service_id, 'panel_service': binding.panel_service,
            'panel_action': binding.panel_action, 'registry_revision': operator.registry_service.active().revision,
            'policy_version': policy['policyVersion'], 'policy_hash': policy['policyHash']})['row']
        op_id = str(row['id'])
        operator.operations.mark_dispatch_started(op_id, 'recovery-test', 1, 'op-' + uuid.uuid4().hex)
        operator.operations.finish(op_id, {'status': 'outcome_unknown'})
        try:
            operator.confirm_fence(op_id)
        except SystemExit:
            pass
        else:
            raise AssertionError('unconfirmed no_effect was accepted')
        print(json.dumps(operator.fence_target(op_id)))
    elif mode == 'late':
        target = json.load(sys.stdin)
        binding = operator.registry_service.active().binding('outbox_send')
        result = asyncio.run(operator.upstream.call_tool(
            binding.endpoint, binding.service_id, binding.upstream_name,
            {'to': 'colleague@acme.example', 'subject': 'Late dispatch', 'body': 'Must not commit'},
            {'operation_id': target['upstreamOperationId'], 'demo_run_id': target['runId'],
             'actor': 'support-agent'}, credential_id=binding.credential_id))
        assert result.is_error and result.structured['error']['code'] == 'operation_fenced', result.as_dict()
        row = operator.operations.get(target['operationId'])
        assert row['status'] == 'failed' and row['error_code'] == 'operator_fence'
        status = asyncio.run(operator.upstream.operation_status(
            binding.status_endpoint, binding.service_id, target['upstreamOperationId'],
            credential_id=binding.credential_id))
        assert status['status'] == 'no_effect', status
        print(json.dumps({'passed': True, 'lateDispatch': 'operation_fenced', 'serviceStatus': status}))
    elif mode == 'closed':
        assert not state['admission_open'], state
        print(json.dumps({'admissionClosed': True, 'runId': state['run_id']}))
    else:
        raise ValueError(mode)


if __name__ == '__main__':
    main()
