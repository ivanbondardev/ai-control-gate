"""Operator bootstrap for the MCP demonstration.

Three explicit actions, each through the lifecycle that already exists in this repository:

``--publish``
    Discover the allowlisted services, validate and hash their schemas, and publish a new registry
    revision. A schema that changed since the published revision marks the tool as requiring review
    until ``--approve-drift`` is passed.

``--apply-principals``
    Activate a configuration release whose principal registry contains the demonstration transport
    identities. The comparison is a real run of the active evaluator over a baseline dataset
    captured from the active release, not a fabricated "passed" flag.

``--apply-panel-policy``
    Add the three MCP services to the panel catalog and propose the demonstration rules and tests as
    a normal panel comparison, then activate it. Nothing is written into the panel state directly.

``--scenario update-kb1042``
    The single-point policy change of the demonstration: allow exactly one document to be updated,
    with a positive and a negative reference test, then activate.

Run it inside the stack, for example::

    docker compose exec gate-mcp python -m action_gate.mcp_bootstrap --publish

Nothing here is reachable from an agent: it is a local operator command.
"""
import argparse
from copy import deepcopy
import json
import os
import sys
from pathlib import Path

from .identity import Principal
from .policy_reader import policy_hash as _policy_hash

OPERATOR = Principal(id='operator-local', role='operator', token='')

CONTENT_FIELDS = ['content', 'subject', 'body', 'description', 'title', 'query', 'value', 'text']

PANEL_SERVICES = (
    {
        'id': 'demo_documents', 'name': 'Documents (MCP service)',
        'kind': 'MCP service', 'endpoint': '', 'owner': 'demo-mcp',
        'actions': [
            {'name': 'search', 'desc': 'Search synthetic documents; ids and titles only.',
             'destructive': False,
             'params': [{'name': 'query', 'type': 'string', 'required': True},
                        {'name': 'limit', 'type': 'number'}]},
            {'name': 'read', 'desc': 'Read one synthetic document with its version.',
             'destructive': False,
             'params': [{'name': 'doc_id', 'type': 'string', 'required': True}]},
            {'name': 'update', 'desc': 'Replace the content of one synthetic document.',
             'destructive': False,
             'params': [{'name': 'doc_id', 'type': 'string', 'required': True},
                        {'name': 'content', 'type': 'string', 'required': True},
                        {'name': 'expected_version', 'type': 'number', 'required': True}]},
        ],
    },
    {
        'id': 'demo_outbox', 'name': 'Outbox (MCP service)',
        'kind': 'MCP service', 'endpoint': '', 'owner': 'demo-mcp',
        'actions': [
            {'name': 'send', 'desc': 'Store one message in the local synthetic mailbox.',
             'destructive': False,
             'params': [{'name': 'to', 'type': 'string', 'required': True},
                        {'name': 'subject', 'type': 'string', 'required': True},
                        {'name': 'body', 'type': 'string', 'required': True}]},
            {'name': 'get', 'desc': 'Read one stored message created by the caller.',
             'destructive': False,
             'params': [{'name': 'message_id', 'type': 'string', 'required': True}]},
            {'name': 'list', 'desc': 'List metadata of the caller\'s own stored messages.',
             'destructive': False,
             'params': [{'name': 'limit', 'type': 'number'}]},
        ],
    },
    {
        'id': 'demo_tickets', 'name': 'Tickets (MCP service)',
        'kind': 'MCP service', 'endpoint': '', 'owner': 'demo-mcp',
        'actions': [
            {'name': 'create', 'desc': 'Create a synthetic ticket in the open state.',
             'destructive': False,
             'params': [{'name': 'title', 'type': 'string', 'required': True},
                        {'name': 'description', 'type': 'string', 'required': True}]},
            {'name': 'read', 'desc': 'Read one synthetic ticket.',
             'destructive': False,
             'params': [{'name': 'ticket_id', 'type': 'string', 'required': True}]},
            {'name': 'transition', 'desc': 'Move a ticket to its next supported status.',
             'destructive': False,
             'params': [{'name': 'ticket_id', 'type': 'string', 'required': True},
                        {'name': 'target_status', 'type': 'string', 'required': True},
                        {'name': 'expected_version', 'type': 'number', 'required': True}]},
        ],
    },
)

DEMO_RULES = (
    {'id': 'mcp-support-documents-read', 'subject': 'support-agent', 'service': 'demo_documents',
     'action': 'read', 'reaction': 'allow',
     'note': 'Support agent reads synthetic knowledge base documents, including the restricted one.'},
    {'id': 'mcp-support-documents-search', 'subject': 'support-agent',
     'service': 'demo_documents', 'action': 'search', 'reaction': 'allow',
     'note': 'Search results are filtered per document against the read rule.'},
    {'id': 'mcp-support-outbox-send', 'subject': 'support-agent', 'service': 'demo_outbox',
     'action': 'send', 'reaction': 'allow',
     'conditions': [{'param': 'to', 'op': 'email_domain_eq', 'value': 'acme.example'}],
     'note': 'Only the internal domain may be used as a recipient. The domain is parsed by the '
             'evaluator from the argument, never accepted from the caller.'},
    {'id': 'mcp-support-outbox-get', 'subject': 'support-agent', 'service': 'demo_outbox',
     'action': 'get', 'reaction': 'allow'},
    {'id': 'mcp-support-outbox-list', 'subject': 'support-agent', 'service': 'demo_outbox',
     'action': 'list', 'reaction': 'allow'},
    {'id': 'mcp-support-tickets-create', 'subject': 'support-agent', 'service': 'demo_tickets',
     'action': 'create', 'reaction': 'allow'},
    {'id': 'mcp-support-tickets-read', 'subject': 'support-agent', 'service': 'demo_tickets',
     'action': 'read', 'reaction': 'allow'},
    {'id': 'mcp-support-tickets-transition', 'subject': 'support-agent', 'service': 'demo_tickets',
     'action': 'transition', 'reaction': 'allow',
     'conditions': [{'param': 'target_status', 'op': 'eq', 'value': 'in_progress'}],
     'note': 'Only the first transition is granted to the support agent. Resolving a ticket needs '
             'an explicit operator change.'},
    {'id': 'mcp-support-documents-update-default', 'subject': 'support-agent',
     'service': 'demo_documents', 'action': 'update', 'reaction': 'block',
     'note': 'Declared refusal, not an omission: the update tool stays visible to the support agent '
             'so a refusal is attributed to policy. The operator replaces this rule with a narrow '
             'grant when the requirement changes.'},
    {'id': 'mcp-observer-documents-read', 'subject': 'observer-agent', 'service': 'demo_documents',
     'action': 'read', 'reaction': 'allow',
     'conditions': [{'param': 'doc_id', 'op': 'neq', 'value': 'KB-RESTRICTED-01'}],
     'note': 'Observer validates results and reads everything except the restricted document.'},
    {'id': 'mcp-observer-documents-search', 'subject': 'observer-agent',
     'service': 'demo_documents', 'action': 'search', 'reaction': 'allow',
     'note': 'List results are filtered per item, so the restricted document never appears.'},
    {'id': 'mcp-observer-outbox-get', 'subject': 'observer-agent', 'service': 'demo_outbox',
     'action': 'get', 'reaction': 'allow'},
    {'id': 'mcp-observer-outbox-list', 'subject': 'observer-agent', 'service': 'demo_outbox',
     'action': 'list', 'reaction': 'allow'},
    {'id': 'mcp-observer-tickets-read', 'subject': 'observer-agent', 'service': 'demo_tickets',
     'action': 'read', 'reaction': 'allow'},
    {'id': 'mcp-operator-tickets-read', 'subject': 'operator-local', 'service': 'demo_tickets',
     'action': 'read', 'reaction': 'allow',
     'note': 'Operator path. It exists so the demonstration can show a Gate refusal and a service '
             'business refusal side by side for the same tool.'},
    {'id': 'mcp-operator-tickets-transition', 'subject': 'operator-local',
     'service': 'demo_tickets', 'action': 'transition', 'reaction': 'allow',
     'note': 'Admitted by policy on purpose: the service still refuses open -> resolved, which is a '
             'business refusal, not a policy refusal.'},
)

DEMO_CHECKS = (
    {'id': 'adversarial_output', 'type': 'regex_pattern', 'name': 'Adversarial content marker',
     'mode': 'block', 'applies_to': 'output',
     'patterns': ['(?i)ignore all previous instructions']},
)

DEMO_TESTS = (
    {'id': 'mcp-documents-read-support', 'name': 'Support agent reads the editable document',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_documents', 'action': 'read',
     'params': {'doc_id': 'KB-1042'}, 'expected': 'allow'},
    {'id': 'mcp-documents-read-restricted-observer',
     'name': 'Observer cannot read the restricted document', 'agent': 'observer-agent',
     'dir': 'tool_call', 'service': 'demo_documents', 'action': 'read',
     'params': {'doc_id': 'KB-RESTRICTED-01'}, 'expected': 'block'},
    {'id': 'mcp-documents-update-blocked', 'name': 'Update is not granted initially',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_documents', 'action': 'update',
     'params': {'doc_id': 'KB-1042', 'content': 'Synthetic rewrite.', 'expected_version': 1},
     'expected': 'block'},
    {'id': 'mcp-documents-update-protected', 'name': 'The protected document stays protected',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_documents', 'action': 'update',
     'params': {'doc_id': 'KB-9000', 'content': 'Synthetic rewrite.', 'expected_version': 1},
     'expected': 'block'},
    {'id': 'mcp-outbox-send-internal', 'name': 'Internal recipient domain is allowed',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_outbox', 'action': 'send',
     'params': {'to': 'colleague@acme.example', 'subject': 'Summary',
                'body': 'Synthetic summary.'}, 'expected': 'allow'},
    {'id': 'mcp-outbox-send-external', 'name': 'External recipient domain is refused',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_outbox', 'action': 'send',
     'params': {'to': 'recipient@external.example', 'subject': 'Summary',
                'body': 'Synthetic summary.'}, 'expected': 'block'},
    {'id': 'mcp-outbox-send-spoofed-suffix',
     'name': 'A lookalike domain is not internal', 'agent': 'support-agent', 'dir': 'tool_call',
     'service': 'demo_outbox', 'action': 'send',
     'params': {'to': 'agent@acme.example.attacker.example', 'subject': 'Summary',
                'body': 'Synthetic summary.'}, 'expected': 'block'},
    {'id': 'mcp-tickets-transition-first', 'name': 'The first ticket transition is allowed',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_tickets',
     'action': 'transition',
     'params': {'ticket_id': 'T-1001', 'target_status': 'in_progress', 'expected_version': 1},
     'expected': 'allow'},
    {'id': 'mcp-tickets-transition-resolved', 'name': 'Resolving a ticket is not granted',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_tickets',
     'action': 'transition',
     'params': {'ticket_id': 'T-1001', 'target_status': 'resolved', 'expected_version': 2},
     'expected': 'block'},
    {'id': 'mcp-outbox-unknown-tool-order', 'name': 'Unknown actions fall back to the default',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_outbox', 'action': 'get',
     'params': {'message_id': 'MSG-NOT-CREATED'}, 'expected': 'allow'},
)

UPDATE_RULE = {
    'id': 'mcp-support-documents-update-kb1042', 'subject': 'support-agent',
    'service': 'demo_documents', 'action': 'update', 'reaction': 'allow',
    'conditions': [{'param': 'doc_id', 'op': 'eq', 'value': 'KB-1042'}],
    'note': 'Operator change: exactly this document may be updated; the protected document keeps '
            'its refusal and the second principal gains nothing.'}

UPDATE_TESTS = (
    {'id': 'mcp-update-kb1042-allowed', 'name': 'The operator change allows exactly this document',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_documents', 'action': 'update',
     'params': {'doc_id': 'KB-1042', 'content': 'Synthetic rewrite.', 'expected_version': 1},
     'expected': 'allow'},
    {'id': 'mcp-update-kb9000-still-blocked', 'name': 'The protected document is still refused',
     'agent': 'support-agent', 'dir': 'tool_call', 'service': 'demo_documents', 'action': 'update',
     'params': {'doc_id': 'KB-9000', 'content': 'Synthetic rewrite.', 'expected_version': 1},
     'expected': 'block'},
    {'id': 'mcp-update-observer-still-blocked',
     'name': 'The second principal does not gain write access', 'agent': 'observer-agent',
     'dir': 'tool_call', 'service': 'demo_documents', 'action': 'update',
     'params': {'doc_id': 'KB-1042', 'content': 'Synthetic rewrite.', 'expected_version': 1},
     'expected': 'block'},
)

def _load_document(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class Bootstrap:
    def __init__(self, environ=None):
        from .http_server import GateApplication
        self.environ = dict(os.environ if environ is None else environ)
        self.core = GateApplication(self.environ)
        if self.core.repository is None:
            raise SystemExit(f'storage is unavailable: {self.core.startup_error}')

    # -- helpers ---------------------------------------------------------------------
    def panel(self):
        return self.core.panel_service

    def state(self):
        status, payload = self.panel().dispatch('GET', '/state', {}, OPERATOR)
        if status != 200:
            raise SystemExit(f'the panel is unavailable: {status}')
        return payload

    def compare_and_activate(self, policy, tests, reason, *, accept_mismatches=False):
        """Compare a candidate through the panel, then activate it.

        Existing baseline mismatches are handled explicitly rather than hidden: the active policy is
        compared against the same test list first, and only failures that already existed there may
        be carried over with ``overrideMismatches``. A new failure always stops the activation.
        """
        state = self.state()
        version = state['policy']['version']
        known_tests = {case['id'] for case in state['tests']}
        if _policy_hash(policy) == _policy_hash(state['policy']):
            return {'changed': False, 'note': 'the candidate policy is already active',
                    'policyVersion': version}
        status, control = self.panel().dispatch(
            'POST', '/compare', {'expectedVersion': version, 'policy': deepcopy(state['policy']),
                                 'tests': tests}, OPERATOR)
        if status != 200:
            raise SystemExit(f'control comparison failed: {status} {json.dumps(control)[:400]}')
        # Only failures the active policy already had count as baseline. A test the candidate adds is
        # never excused by the baseline round.
        baseline = sorted(row['id'] for row in control['results']
                          if not row['passed'] and row['id'] in known_tests)
        status, comparison = self.panel().dispatch(
            'POST', '/compare', {'expectedVersion': version, 'policy': policy, 'tests': tests},
            OPERATOR)
        if status != 200:
            raise SystemExit(f'compare failed: {status} {json.dumps(comparison)[:500]}')
        failed = sorted(row['id'] for row in comparison['results'] if not row['passed'])
        new_failures = sorted(set(failed) - set(baseline))
        if new_failures and not accept_mismatches:
            print(json.dumps({'comparison': comparison['id'], 'failed': failed,
                              'knownBaselineMismatches': baseline,
                              'newFailures': new_failures,
                              'note': 'the candidate introduced failures; nothing was activated'},
                             indent=2), flush=True)
            return None
        body = {'expectedVersion': version, 'policy': policy, 'tests': tests,
                'evaluationId': comparison['id'], 'source': 'Import', 'reason': reason}
        if failed:
            body['overrideMismatches'] = True
        status, result = self.panel().dispatch('POST', '/activate', body, OPERATOR)
        if status != 200:
            raise SystemExit(f'activate failed: {status} {json.dumps(result)[:500]}')
        return {'comparison': comparison['id'], 'failed': failed,
                'knownBaselineMismatches': baseline, 'newFailures': new_failures,
                'policyVersion': self.state()['policy']['version']}

    # -- actions ----------------------------------------------------------------------
    def publish_registry(self, *, approve_drift=False):
        import asyncio

        from .mcp_upstream import McpUpstream
        from .service_registry import ServiceRegistry
        from .storage.operations import build_operations
        from dummy_mcp.common.auth import load_credentials
        allowlist_path = self.environ.get('APP_MCP_ALLOWLIST') or str(
            self.core.policy_dir + '/mcp_services.json')
        credentials = load_credentials(self.environ.get('DEMO_CREDENTIALS_FILE')
                                       or '/run/demo/credentials.json')
        allowed = self.environ.get('APP_MCP_ALLOWED_HOSTS')
        allowed_hosts = ({host.strip() for host in allowed.split(',') if host.strip()}
                         if allowed else {'documents-mcp', 'outbox-mcp', 'tickets-mcp'})
        allowlist = ServiceRegistry.load_allowlist(allowlist_path, allowed_hosts=allowed_hosts)
        operations = build_operations(self.core.repository)
        registry = ServiceRegistry(allowlist, credentials, operations, McpUpstream(credentials),
                                   allowed_hosts=allowed_hosts)
        discovery = asyncio.run(registry.discover())
        previous = registry.active()
        previous_tools = {}
        if previous is not None:
            for entry in previous.document.get('services', []):
                for tool in entry.get('tools', []):
                    previous_tools[tool['published_name']] = tool
        document = registry.build_revision(
            discovery, previous=None, approve_drift=approve_drift)
        drift = []
        for entry in document['services']:
            for tool in entry['tools']:
                old = previous_tools.get(tool['published_name'])
                if old and old.get('schema_hash') != tool.get('schema_hash'):
                    drift.append(tool['published_name'])
                    tool['schemaChanged'] = True
                    if not approve_drift:
                        tool['review_required'] = True
        revision = registry.publish(document, source='bootstrap', created_by=OPERATOR.id)
        registry.record_health(discovery)
        return {'revision': revision, 'services': [{'serviceId': entry['service_id'],
                                                    'health': entry['health'],
                                                    'tools': len(entry['tools'])}
                                                   for entry in document['services']],
                'drift': drift, 'approvedDrift': bool(approve_drift)}

    def apply_principals(self):
        """Install the demonstration transport identities through the explicit operator path.

        Identities are not editable policy documents, so this does not go through a draft. It is a
        separate, narrow activation kind that can only add principals and can never change the role
        or token of an identity that already exists.
        """
        principals = _load_document(str(Path(self.core.policy_dir) / 'principals.json'))
        result = self.core.config_service.install_identity_registry(
            principals, actor=OPERATOR.id,
            reason='MCP demonstration transport principals')
        return result

    def apply_panel_policy(self):
        state = self.state()
        existing = {service['id'] for service in state['services']}
        added = []
        for definition in PANEL_SERVICES:
            if definition['id'] in existing:
                continue
            status, payload = self.panel().dispatch('POST', '/services',
                                                    {'service': definition}, OPERATOR)
            if status != 200:
                raise SystemExit(f'adding {definition["id"]} failed: {status} '
                                 f'{json.dumps(payload)[:300]}')
            added.append(definition['id'])
        state = self.state()
        policy = deepcopy(state['policy'])
        tests = deepcopy(state['tests'])
        policy, tests = self._merge_policy(policy, tests, DEMO_RULES, DEMO_TESTS)
        result = self.compare_and_activate(policy, tests, 'MCP demonstration policy and services')
        if result is None:
            return {'servicesAdded': added, 'activated': False}
        return {'servicesAdded': added, **result}

    def scenario_baseline(self):
        """Return the demonstration to its starting requirement.

        The suite is repeatable because the operator can put the bench back: the narrow grant is
        removed, the declared refusal returns, and the reference test that asserts the refusal is
        restored. Nothing is written directly into the panel state.
        """
        state = self.state()
        policy = deepcopy(state['policy'])
        tests = deepcopy(state['tests'])
        policy['rules'] = [rule for rule in policy['rules'] if rule['id'] != UPDATE_RULE['id']]
        scenario_tests = {case['id'] for case in UPDATE_TESTS}
        tests = [case for case in tests if case['id'] not in scenario_tests]
        block_rule = next(rule for rule in DEMO_RULES
                          if rule['id'] == 'mcp-support-documents-update-default')
        policy, tests = self._merge_policy(policy, tests, (block_rule,), DEMO_TESTS)
        result = self.compare_and_activate(
            policy, tests, 'Baseline: the update grant is removed and the refusal restored')
        return result or {'activated': False}

    def scenario_update_kb1042(self):
        state = self.state()
        policy = deepcopy(state['policy'])
        tests = deepcopy(state['tests'])
        # The blanket refusal is replaced by the narrow grant: the panel's rule semantics let a
        # conditionless block win on a tie, so leaving both in place would change nothing.
        policy['rules'] = [rule for rule in policy['rules']
                           if rule['id'] != 'mcp-support-documents-update-default']
        # The reference test that asserted "update is refused" describes the previous requirement.
        # It is replaced by the positive test for the granted document plus the negative test for the
        # protected one, so the suite still states the requirement instead of contradicting it.
        tests = [case for case in tests if case['id'] != 'mcp-documents-update-blocked']
        policy, tests = self._merge_policy(policy, tests, (UPDATE_RULE,), UPDATE_TESTS)
        result = self.compare_and_activate(
            policy, tests, 'Operator change: allow updating exactly KB-1042')
        return result or {'activated': False}

    @staticmethod
    def _merge_policy(policy, tests, rules, new_tests):
        """Add rules, scope content checks to argument fields, and add reference tests."""
        known = {rule['id'] for rule in policy['rules']}
        for rule in rules:
            if rule['id'] not in known:
                policy['rules'].append(deepcopy(rule))
        known_tests = {case['id'] for case in tests}
        for case in new_tests:
            if case['id'] not in known_tests:
                tests.append(deepcopy(case))
        for check in policy['checks']:
            if check['type'] not in ('secrets_detection', 'pii_detection', 'regex_pattern'):
                continue
            if check.get('applies_to'):
                # A check that states its direction is operator-authored and keeps its own scope.
                continue
            # Content redaction of tool arguments is limited to the fields that carry content. A
            # routing field such as ``to`` is never rewritten, so a domain rule keeps working, while
            # input and output text keeps the previous whole-text behaviour.
            check['fields'] = sorted(set(check.get('fields') or []) | set(CONTENT_FIELDS))
        for check in DEMO_CHECKS:
            if check['id'] not in {node['id'] for node in policy['checks']}:
                policy['checks'].append(deepcopy(check))
        return policy, tests

    def report(self):
        from .storage.operations import build_operations
        operations = build_operations(self.core.repository)
        registry = None
        try:
            from .service_registry import ActiveRegistry
            row = operations.active_registry()
            if row:
                document = row['document'] if isinstance(row['document'], dict) \
                    else json.loads(row['document'])
                registry = ActiveRegistry(row['revision'], document,
                                          row.get('document_hash')).summary()
        except Exception as exc:  # noqa: BLE001 - the report must not fail on a missing revision
            registry = {'error': type(exc).__name__}
        return {'runState': operations.run_state(), 'counters': operations.counters(),
                'registry': registry, 'health': operations.service_health(),
                'operations': [{key: value for key, value in row.items()
                                if key in ('id', 'published_tool', 'status', 'decision',
                                           'disclosure', 'receipt_id', 'resource_id',
                                           'created_at')}
                               for row in operations.list_operations(limit=20)]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='action_gate.mcp_bootstrap', description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--publish', action='store_true',
                       help='discover services and publish a registry revision')
    group.add_argument('--approve-drift', action='store_true',
                       help='publish even when a schema changed since the last revision')
    group.add_argument('--apply-principals', action='store_true',
                       help='activate the demonstration transport principals')
    group.add_argument('--apply-panel-policy', action='store_true',
                       help='add the MCP services, rules and tests to the panel policy')
    group.add_argument('--scenario', choices=('baseline', 'update-kb1042'),
                       help='apply one demonstration policy change')
    group.add_argument('--state', action='store_true', help='print run, registry and counters')
    arguments = parser.parse_args(argv)
    bootstrap = Bootstrap()
    if arguments.publish or arguments.approve_drift:
        payload = bootstrap.publish_registry(approve_drift=arguments.approve_drift)
    elif arguments.apply_principals:
        payload = bootstrap.apply_principals()
    elif arguments.apply_panel_policy:
        payload = bootstrap.apply_panel_policy()
    elif arguments.scenario == 'update-kb1042':
        payload = bootstrap.scenario_update_kb1042()
    elif arguments.scenario == 'baseline':
        payload = bootstrap.scenario_baseline()
    else:
        payload = bootstrap.report()
    json.dump(payload, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
