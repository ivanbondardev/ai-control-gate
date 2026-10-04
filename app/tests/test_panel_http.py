"""Real HTTP contract checks for the restored original policy builder."""
import copy
import json
from http.server import ThreadingHTTPServer
import threading
import unittest
import urllib.error
import urllib.request

from action_gate.http_server import GateHandler, build_application

OPERATOR = {'X-Action-Gate-Principal': 'operator-local',
            'X-Action-Gate-Token': 'local-operator-token'}
AGENT = {'X-Action-Gate-Principal': 'agent-local',
         'X-Action-Gate-Token': 'local-agent-token'}


class PanelHttpTests(unittest.TestCase):
    def setUp(self):
        self.app = build_application({'APP_STORAGE': 'memory', 'APP_RUNTIME_CACHE': 'off'})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), GateHandler)
        self.server.daemon_threads = True
        self.server.app = self.app
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, suffix, body=None, headers=OPERATOR):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.origin + '/v1/panel' + suffix, data=data,
                                     headers=dict(headers, **({'Content-Type': 'application/json'}
                                                              if data else {})), method=method)
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    def test_unified_report_and_export_include_panel_with_owner_isolation(self):
        _, event = self.request('POST', '/invoke', {'idempotencyKey': 'report', 'request': {
            'agent': 'support-bot', 'dir': 'input', 'target': 'llama3.1:8b', 'text': 'Hello'}})
        def get(path, headers=OPERATOR):
            with urllib.request.urlopen(urllib.request.Request(self.origin + path, headers=headers)) as response:
                return response.read().decode()
        report = json.loads(get('/v1/report'))
        self.assertEqual([r['invocation_id'] for r in report['records']], [event['id']])
        self.assertEqual(json.loads(get('/v1/summary'))['unified']['total'], 1)
        self.assertEqual(json.loads(get('/v1/report', AGENT))['total'], 0)
        exported = [json.loads(line) for line in get('/v1/audit/export').splitlines()]
        self.assertEqual([r['invocation_id'] for r in exported], [event['id']])

    def test_operator_role_required_for_configuration_and_corpus(self):
        for suffix in ('/state', '/training/export'):
            self.assertEqual(self.request('GET', suffix, headers={})[0], 401)
            self.assertEqual(self.request('GET', suffix, headers=AGENT)[0], 403)
        for method, suffix in [('POST', '/draft'), ('POST', '/activate'), ('POST', '/compare'),
                               ('PUT', '/tests'), ('POST', '/services'),
                               ('PATCH', '/training/missing')]:
            self.assertEqual(self.request(method, suffix, {}, AGENT)[0], 403)
        status, data = self.request('GET', '/state')
        self.assertEqual(status, 200)
        self.assertEqual(data['events'], [])
        self.assertEqual(data['training'], [])
        self.assertIn('rules', data['policy'])
        self.assertIn('checks', data['policy'])

    def test_agent_subject_cannot_be_forged_in_invocation(self):
        status, event = self.request('POST', '/invoke', {'idempotencyKey': 'spoof', 'request': {
            'agent': 'support-bot', 'dir': 'tool_call', 'service': 'documents',
            'action': 'read', 'params': {'doc_id': 'KB-1042'}, 'text': ''}}, AGENT)
        # A server may reject impersonation outright or bind the real subject and deny it.
        self.assertIn(status, (200, 403, 422))
        if status == 200:
            self.assertEqual(event['req']['agent'], 'agent-local')
            self.assertFalse(event['action']['dispatched'])
            self.assertEqual(event['r']['decision'], 'block')

    def test_rule_expansion_is_reported_by_server_before_activation(self):
        _, initial = self.request('GET', '/state')
        policy = copy.deepcopy(initial['policy'])
        rule = next(r for r in policy['rules'] if r['id'] == 'r1')
        rule['action'] = '*'
        case = {'id': 'no-delete', 'name': 'Support cannot delete', 'agent': 'support-bot',
                'dir': 'tool_call', 'service': 'documents', 'action': 'delete',
                'params': {'doc_id': 'POL-0007'}, 'expected': 'block'}
        status, result = self.request('POST', '/compare', {
            'policy': policy, 'tests': [case], 'expectedVersion': initial['policy']['version']})
        self.assertEqual(status, 200, result)
        self.assertTrue(result['complete'])
        self.assertFalse(result['passed'])
        row = result['results'][0]
        self.assertEqual(row['live']['decision'], 'block')
        self.assertEqual(row['draft']['decision'], 'allow')
        status, error = self.request('POST', '/activate', {
            'policy': policy, 'tests': [case], 'expectedVersion': initial['policy']['version'],
            'evaluationId': result['id'], 'reason': 'HTTP regression', 'overrideMismatches': False})
        self.assertEqual(status, 409, error)
        _, after = self.request('GET', '/state')
        self.assertEqual(after['policy'], initial['policy'])
        self.assertEqual(after['events'], [])

    def test_json_body_required_and_unknown_panel_routes_do_not_mutate(self):
        self.assertEqual(self.request('POST', '/draft', [1, 2])[0], 422)
        self.assertEqual(self.request('GET', '/no-such-resource')[0], 404)
        status, state = self.request('GET', '/state')
        self.assertEqual(status, 200)
        self.assertEqual(state['events'], [])

    def test_training_review_and_replay_use_stored_sanitized_event(self):
        status, event = self.request('POST', '/invoke', {'idempotencyKey': 'pii', 'request': {
            'agent': 'support-bot', 'dir': 'input', 'target': 'llama3.1:8b',
            'text': 'Please summarize a message from alice@example.org.'}})
        self.assertEqual(status, 200, event)
        _, state = self.request('GET', '/state')
        stored = next(e for e in state['events'] if e['id'] == event['id'])
        self.assertNotIn('alice@example.org', json.dumps(stored))
        self.assertTrue(state['training'])
        example = state['training'][0]
        self.assertNotIn('alice@example.org', json.dumps(example))
        status, _ = self.request('PATCH', '/training/' + example['id'], {'review': 'confirmed'})
        self.assertEqual(status, 200)
        status, exported = self.request('GET', '/training/export')
        self.assertEqual(status, 200)
        self.assertTrue(exported['jsonl'])
        self.assertNotIn('alice@example.org', exported['jsonl'])
        status, replay = self.request('POST', '/events/' + event['id'] + '/replay', {})
        self.assertEqual(status, 200)
        self.assertTrue(replay['sanitizedReplay'])


if __name__ == '__main__':
    unittest.main()
