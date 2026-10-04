"""Durable original control-panel lifecycle and local synthetic runtime.

The panel schema is distinct from the legacy gateway bundle. All mutations, admission checks,
idempotency claims and synthetic effects share one transaction and one row lock. No panel path
makes a network call. Untrusted invocation content is scrubbed before persistence; explicitly
authored synthetic test fixtures are kept separately from invocation audit and replay records.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import threading
import time
import uuid
from urllib.parse import urlsplit

from .config_service import ConfigConflict
from .contracts import ContractError
from .storage.base import RepositoryError


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return sha256(_json(value).encode()).hexdigest()


def _policy_hash(policy):
    return _hash({key: value for key, value in policy.items() if key != 'version'})


def _version_instructions(policy, active):
    """Instruction provenance is server-owned and compared against the active instruction."""
    previous = {node['id']: node for node in active['checks'] if node['type'] == 'semantic'}
    for node in policy['checks']:
        if node['type'] != 'semantic':
            continue
        old = previous.get(node['id'])
        if old:
            node['instruction_version'] = old['instruction_version'] + int(node.get('instruction') != old['instruction'])
        else:
            node['instruction_version'] = 1
    return policy


def _candidate(state, policy):
    # Fill validated defaults first, then derive provenance once from the current active policy.
    # Compare and activate receive the same editor JSON and therefore obtain the same hash.
    normalized = _validate(deepcopy(policy), state['services'])
    return _validate(_version_instructions(normalized, state['policy']), state['services'])


def _required(value, name, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError('panel_schema_invalid', f'{name} must be a non-empty string, up to {limit} characters')
    return value.strip()


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ContractError('panel_schema_invalid', f'{name} must be an integer >= {minimum}')
    return value


def _engine():
    # Lazy import keeps legacy app startup independent of this optional panel surface.
    from . import panel_engine
    return panel_engine


def _validate(policy, services):
    try:
        return _engine().validate_policy(policy, services)
    except _engine().PanelValidationError as exc:
        raise ContractError(exc.code, exc.message) from exc


def _evaluate(policy, request, context=None):
    try:
        return _engine().evaluate(policy, request, context=context or {})
    except _engine().PanelValidationError as exc:
        raise ContractError(exc.code, exc.message) from exc


def _clean(value):
    return _engine().sanitize_value(value)


def _clean_result(result):
    """Sanitize content without rewriting validated identifiers or typed engine metadata.

    A timestamp-like check id is a correlation key, not a phone number. Scrubbing whole JSON
    envelopes breaks references, so only content-bearing fields cross the text sanitizer.
    """
    if result is None:
        return None
    clean = deepcopy(result)
    for name in ('processed', 'processedParams', 'marks', 'triggerDetail'):
        if name in clean:
            clean[name] = _clean(clean[name])
    for check in clean.get('checks', []):
        for name in ('input', 'detail'):
            if name in check:
                check[name] = _clean(check[name])
    return clean


def _clean_request(request):
    clean = deepcopy(request)
    clean['text'] = _clean(clean.get('text', ''))
    clean['params'] = _clean(clean.get('params', {}))
    clean['target'] = _clean(clean.get('target'))
    clean['meta'] = {}
    return clean


def _diff(previous, candidate):
    """Original UI-compatible structured change list, without inventing authors or times."""
    result = []
    if previous['default_reaction'] != candidate['default_reaction']:
        result.append({'op': 'change', 'sec': 'policy', 'id': '_default',
                       'label': 'Calls without a matching rule', 'field': 'default_reaction',
                       'from': previous['default_reaction'], 'to': candidate['default_reaction']})
    for section, name in (('check', 'checks'), ('rule', 'rules')):
        old = {item['id']: item for item in previous[name]}
        new = {item['id']: item for item in candidate[name]}
        def label(item):
            return item.get('name') or f"{item.get('subject')} → {item.get('service')}.{item.get('action')}"
        for index, item in enumerate(candidate[name]):
            if item['id'] not in old:
                result.append({'op': 'add', 'sec': section, 'id': item['id'],
                               'label': label(item), 'item': item, 'index': index})
            else:
                before = old[item['id']]
                for field in sorted(set(before) | set(item)):
                    if before.get(field) != item.get(field):
                        result.append({'op': 'change', 'sec': section, 'id': item['id'],
                                       'label': label(item), 'field': field,
                                       'from': before.get(field), 'to': item.get(field)})
        for item in previous[name]:
            if item['id'] not in new:
                result.append({'op': 'remove', 'sec': section, 'id': item['id'],
                               'label': label(item), 'item': item})
        a = [item['id'] for item in previous[name] if item['id'] in new]
        b = [item['id'] for item in candidate[name] if item['id'] in old]
        if a != b:
            result.append({'op': 'order', 'sec': section, 'from': a, 'to': b})
    return result


class PanelService:
    """Repository-backed state machine. PostgreSQL and memory obey the same lock boundary."""

    def __init__(self, repository):
        self.repository = repository
        # Memory state belongs to the repository, so a second service instance sees the same data.
        if repository.name != 'postgres' and not hasattr(repository, '_lock'):
            repository._lock = threading.RLock()

    @staticmethod
    def _seed():
        seed = json.loads((Path(__file__).resolve().parents[1] / 'panel_seed.json').read_text())
        seed['policy'] = _validate(seed['policy'], seed['services'])
        now = _now()
        return {
            'schemaVersion': 1, 'revision': 1, 'registryRevision': 1,
            'policy': seed['policy'], 'draft': {'policy': deepcopy(seed['policy']), 'revision': 1,
                'id': str(uuid.uuid4()), 'baseVersion': seed['policy']['version']},
            'services': seed['services'], 'tests': seed['tests'], 'events': [], 'training': [],
            'history': [{'v': seed['policy']['version'], 'policy': deepcopy(seed['policy']),
                'author': 'bootstrap', 'source': 'Bootstrap', 'at': now, 'ops': [],
                'summary': 'Initial policy loaded from the checked-in synthetic panel seed'}],
            'evaluations': {}, 'corpus': {}, 'audit': [], 'effects': [], 'claims': {},
            'usage': {}, 'hashSalt': secrets.token_hex(32),
            'documents': {'KB-1042': {'text': 'To reset two-factor authentication, verify the customer and issue a recovery link.', 'deleted': False},
                          'POL-0007': {'text': 'Refund requests are reviewed under the current refund policy.', 'deleted': False}},
        }

    @contextmanager
    def _transaction(self):
        if self.repository.name != 'postgres':
            with self.repository._lock:
                state = deepcopy(getattr(self.repository, '_panel_state', None) or self._seed())
                yield state
                self.repository._panel_state = state
            return
        from psycopg.types.json import Jsonb
        with self.repository.raw_connection() as connection:
            with connection.cursor() as cursor:
                # The insert participates in the same transaction as the lock, including bootstrap.
                cursor.execute('SELECT 1 FROM control_panel_state WHERE id = %s', ('default',))
                if cursor.fetchone() is None:
                    seed = self._seed()
                    cursor.execute('INSERT INTO control_panel_state (id, revision, state) VALUES (%s, %s, %s) '
                                   'ON CONFLICT (id) DO NOTHING', ('default', 1, Jsonb(seed)))
                cursor.execute('SELECT state FROM control_panel_state WHERE id = %s FOR UPDATE', ('default',))
                row = cursor.fetchone()
                if row is None:
                    raise RepositoryError('panel_state_unavailable')
                state = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                yield state
                cursor.execute('UPDATE control_panel_state SET state=%s, revision=%s, updated_at=now() WHERE id=%s',
                               (Jsonb(state), state['revision'], 'default'))

    def _public(self, state):
        return deepcopy({
            'policy': state['policy'], 'draft': state['draft'], 'services': state['services'],
            'tests': state['tests'], 'history': state['history'], 'events': state['events'][-500:],
            'training': state['training'][-1500:], 'revision': state['revision'],
            'registryRevision': state['registryRevision'], 'semanticMode': 'baseline',
            'storage': self.repository.name, 'durable': self.repository.name == 'postgres',
            'runtime': 'panel-local-synthetic', 'effectCount': len(state['effects']),
            'eventCount': len(state['events']), 'trainingCount': len(state['training']),
            'usage': [{'agent': json.loads(key)[0], 'period': json.loads(key)[1], 'tokensEstimated': value,
                       'usageKind': 'estimated', 'periodKind': 'utc_day'} for key, value in state['usage'].items()],
            'usageNote': 'Per synthetic agent admission-token estimates, reset by UTC day; no LLM is called or billed. Rate and loop counts use persisted attempts from the last 60 seconds.',
            'note': 'Original panel schema. Synthetic local adapters only; baseline is a deterministic heuristic. No external model or service calls.',
        })

    def dispatch(self, method, path, body, principal):
        if principal is None:
            raise ContractError('identity_required', 'A transport identity is required', 401)
        if not isinstance(body, dict):
            raise ContractError('panel_schema_invalid', 'Expected a JSON object')
        try:
            if len(_json(body)) > 1_000_000:
                raise ValueError('Panel request exceeds the size limit')
        except (TypeError, ValueError, RecursionError) as exc:
            raise ContractError('panel_schema_invalid', 'Panel request must be bounded, finite JSON') from exc
        if path.startswith('/v1/panel'):
            path = path[len('/v1/panel'):]
        path = '/' + path.strip('/')
        method = method.upper()
        if not (method == 'POST' and path == '/invoke') and principal.role != 'operator':
            raise ContractError('operator_required', 'The panel requires the operator role', 403)
        with self._transaction() as state:
            before = state['revision']
            result, mutated = self._dispatch(state, method, path, body, principal)
            if mutated:
                self._capacity(state)
                state['revision'] = before + 1
            # Full state responses are constructed after updating the monotonic state revision.
            if result is None:
                result = self._public(state)
            return 200, deepcopy(result)

    @staticmethod
    def _capacity(state):
        limits = {'services': 256, 'events': 10000, 'effects': 10000, 'claims': 10000,
                  'corpus': 10000, 'training': 30000, 'evaluations': 2000, 'history': 500, 'documents': 5000}
        for field, maximum in limits.items():
            if len(state[field]) > maximum:
                raise ContractError('panel_capacity', f'Local panel capacity reached for {field} ({maximum}); nothing was committed', 413)
        if len(_json(state).encode()) > 32_000_000:
            raise ContractError('panel_capacity', 'Local panel state reached its 32 MB capacity; nothing was committed', 413)

    def _dispatch(self, state, method, path, body, principal):
        if method == 'GET' and path == '/state':
            return self._public(state), False
        if method == 'POST' and path == '/draft':
            expected = _integer(body.get('expectedRevision'), 'expectedRevision', 1)
            if expected != state['draft']['revision']:
                raise ConfigConflict('draft_changed', 'Reload the latest draft revision before saving')
            policy = deepcopy(body.get('policy'))
            self._draft_shape(policy)
            _version_instructions(policy, state['policy'])
            policy['version'] = state['policy']['version']
            state['draft'] = {'policy': policy, 'revision': expected + 1,
                              'id': state['draft']['id'], 'baseVersion': state['draft']['baseVersion']}
            return None, True
        if method == 'POST' and path == '/compare':
            return self._compare(state, body, principal), True
        if method == 'POST' and path == '/activate':
            self._activate(state, body, principal)
            return None, True
        if method == 'PUT' and path == '/tests':
            self._tests(body.get('tests'), state['services'], strict=False)
            state['tests'] = deepcopy(body['tests'])
            return None, True
        if method == 'POST' and path == '/services':
            service = self._service(body.get('service'))
            if any(item['id'] == service['id'] for item in state['services']):
                raise ConfigConflict('service_exists', 'A service with this id already exists')
            state['services'].append(service)
            state['registryRevision'] += 1
            return None, True
        if method == 'POST' and path.startswith('/services/') and path.endswith('/verify'):
            identifier = path[len('/services/'):-len('/verify')]
            service = next((item for item in state['services'] if item['id'] == identifier), None)
            if service is None:
                raise ContractError('not_found', 'Unknown local service schema', 404)
            self._service(service)
            service['verified'] = _now()
            service['verification'] = {'status': 'verified', 'scope': 'local_synthetic_schema',
                'note': 'Schema checked against the local synthetic adapter. No network reachability was tested.',
                'actions': len(service['actions'])}
            return None, True
        if method == 'POST' and path == '/invoke':
            return self._invoke(state, body, principal)
        if path.startswith('/events/') and method == 'POST':
            identifier, _, operation = path[len('/events/'):].partition('/')
            event = next((event for event in state['events'] if event['id'] == identifier), None)
            if event is None:
                raise ContractError('not_found', 'Unknown event', 404)
            if operation == 'replay':
                req = deepcopy(state['corpus'][identifier])
                result = {'current': _clean_result(_evaluate(state['policy'], req)), 'sanitizedReplay': True,
                          'note': 'Re-evaluated sanitized replay content, without dispatch or budget charge.'}
                if body.get('policy') is not None:
                    _validate(body['policy'], state['services'])
                    result['draft'] = _clean_result(_evaluate(body['policy'], req))
                return result, False
            if operation == 'review':
                comment = body.get('comment', '')
                if not isinstance(comment, str) or len(comment) > 2000:
                    raise ContractError('panel_schema_invalid', 'Review comment must be at most 2000 characters')
                event['fp'] = ({'comment': _clean(comment), 'by': principal.id, 'at': _now()}
                               if body.get('fp', True) else False)
                for example in state['training']:
                    if example['eventId'] == identifier and event['fp']:
                        example['review'] = 'needs review'
                return event, True
        if path == '/training/export' and method == 'GET':
            records = []
            for example in state['training']:
                if example['review'] in ('confirmed', 'corrected'):
                    records.append(_json({'input': example['input'], 'label': example.get('corrected') or example['label'],
                        'model_label': example['label'], 'human_reviewed': True, 'check': example['checkId'],
                        'model': example['model'], 'instruction_version': example['instruction_version'],
                        'policy_version': example['policy_version'], 'semantic_mode': 'baseline',
                        'detector': 'deterministic-baseline-v1'}))
            return {'jsonl': '\n'.join(records), 'count': len(records), 'semanticMode': 'baseline'}, False
        if path.startswith('/training/') and method == 'PATCH':
            example = next((row for row in state['training'] if row['id'] == path[len('/training/'):]), None)
            if example is None:
                raise ContractError('not_found', 'Unknown training example', 404)
            review = body.get('review')
            if review not in ('confirmed', 'corrected', 'needs review', 'unreviewed'):
                raise ContractError('panel_schema_invalid', 'Unknown review status')
            if review == 'corrected':
                corrected = _required(body.get('corrected'), 'corrected', 80)
                if corrected not in example.get('allowedLabels', []):
                    raise ContractError('panel_schema_invalid', 'Corrected label must belong to the recorded classifier labels')
                example['corrected'] = corrected
            else:
                example['corrected'] = None
            example.update(review=review, reviewer=principal.id, reviewedAt=_now())
            return example, True
        raise ContractError('not_found', 'Unknown panel route', 404)

    @staticmethod
    def _draft_shape(policy):
        """Permit incomplete form values, while keeping every persisted UI structure renderable."""
        if (not isinstance(policy, dict) or not isinstance(policy.get('checks'), list)
                or not isinstance(policy.get('rules'), list) or len(policy['checks']) > 128
                or len(policy['rules']) > 256 or len(_json(policy)) > 1_000_000):
            raise ContractError('panel_schema_invalid', 'Draft must contain bounded checks and rules lists')
        for name in ('checks', 'rules'):
            seen = set()
            for item in policy[name]:
                if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                        or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', item['id']) or item['id'] in seen):
                    raise ContractError('panel_schema_invalid', 'Draft entries need unique valid ids')
                seen.add(item['id'])
                if name == 'checks' and item.get('type') not in _engine().NODE_TYPES:
                    raise ContractError('panel_schema_invalid', 'Unknown draft check type')
                for key in ('name', 'type', 'mode', 'subject', 'service', 'action', 'reaction', 'note', 'instruction'):
                    if key in item and not isinstance(item[key], str):
                        raise ContractError('panel_schema_invalid', f'Draft {key} must be text')
                for key in ('entities', 'patterns', 'models', 'deny_paths', 'fields'):
                    if key in item and (not isinstance(item[key], list) or any(not isinstance(v, str) for v in item[key])):
                        raise ContractError('panel_schema_invalid', f'Draft {key} must be a text list')
                for key, fields in (('labels', ('label', 'reaction')), ('conditions', ('param', 'op', 'value')),
                                    ('exceptions', ('agent', 'match'))):
                    if key in item and (not isinstance(item[key], list) or any(
                            not isinstance(v, dict) or any(field in v and not isinstance(v[field], (str, int, float))
                                                          for field in fields) for v in item[key])):
                        raise ContractError('panel_schema_invalid', f'Draft {key} must contain structured entries')

    @staticmethod
    def _tests(tests, services, strict=True):
        if not isinstance(tests, list) or not (1 if strict else 0) <= len(tests) <= 200:
            raise ContractError('panel_schema_invalid', 'Supply up to 200 synthetic test cases (at least one for comparison)')
        if len(_json(tests)) > 1_000_000:
            raise ContractError('panel_schema_invalid', 'Synthetic test corpus exceeds the size limit')
        seen = set()
        for case in tests:
            if not isinstance(case, dict):
                raise ContractError('panel_schema_invalid', 'Each test must be an object')
            identifier = _required(case.get('id'), 'test id', 100)
            if identifier in seen:
                raise ContractError('panel_schema_invalid', 'Test ids must be unique')
            seen.add(identifier)
            if case.get('expected') not in ('allow', 'redact', 'block', 'throttle', 'monitor'):
                raise ContractError('panel_schema_invalid', 'Every test must state an expected decision')
            if 'expected_output' in case and not isinstance(case['expected_output'], str):
                raise ContractError('panel_schema_invalid', 'expected_output must be a string')
            if strict:
                PanelService._request(case, services, fixture=True)

    @staticmethod
    def _request(raw, services, fixture=False):
        if not isinstance(raw, dict):
            raise ContractError('panel_schema_invalid', 'request must be an object')
        if not fixture and set(raw) - {'agent', 'dir', 'target', 'service', 'action', 'params', 'text', 'meta'}:
            raise ContractError('panel_schema_invalid', 'Unknown request fields')
        direction = raw.get('dir')
        if direction not in ('input', 'output', 'tool_call'):
            raise ContractError('panel_schema_invalid', 'dir must be input, output or tool_call')
        agent = _required(raw.get('agent'), 'agent', 100)
        req = {'agent': agent, 'dir': direction, 'target': raw.get('target'), 'service': raw.get('service'),
               'action': raw.get('action'), 'params': deepcopy(raw.get('params') or {}), 'meta': {}}
        if direction == 'tool_call':
            req['target'] = None
            service = next((s for s in services if s['id'] == req['service']), None)
            action = next((a for a in service['actions'] if a['name'] == req['action']), None) if service else None
            if action is None:
                raise ContractError('panel_schema_invalid', 'Unknown local service/action schema')
            if not isinstance(req['params'], dict):
                raise ContractError('panel_schema_invalid', 'params must be an object')
            fields = {p['name']: p for p in action['params']}
            if set(req['params']) - set(fields):
                raise ContractError('panel_schema_invalid', 'Unknown action parameter')
            for name, definition in fields.items():
                value = req['params'].get(name)
                if name not in req['params']:
                    if definition.get('required'):
                        raise ContractError('panel_schema_invalid', f'Missing required parameter {name}')
                    continue
                kind = definition['type']
                if fixture and kind == 'number' and isinstance(value, str):
                    try:
                        value = float(value)
                        req['params'][name] = value
                    except ValueError:
                        pass
                valid = ((kind == 'string' and isinstance(value, str) and len(value) <= 32000)
                         or (kind == 'boolean' and type(value) is bool)
                         or (kind == 'number' and type(value) in (int, float) and math.isfinite(value)))
                if not valid:
                    raise ContractError('panel_schema_invalid', f'Wrong type for parameter {name}')
            req['text'] = f"{req['service']}.{req['action']}(" + ', '.join(
                name + '=' + json.dumps(value, ensure_ascii=False) for name, value in req['params'].items()) + ')'
        else:
            req['params'] = {}
            req['service'] = None
            req['action'] = None
            req['target'] = _required(req['target'], 'target', 200)
            if not isinstance(raw.get('text'), str) or len(raw['text'].encode()) > 32000:
                raise ContractError('panel_schema_invalid', 'text must be a string up to 32000 bytes')
            req['text'] = raw['text']
        if len(req['text'].encode()) > 32000:
            raise ContractError('panel_schema_invalid', 'The rendered request exceeds 32000 bytes')
        return req

    @staticmethod
    def _service(raw):
        if not isinstance(raw, dict):
            raise ContractError('panel_schema_invalid', 'service must be an object')
        if set(raw) - {'id', 'name', 'kind', 'endpoint', 'owner', 'verified', 'verification', 'actions'}:
            raise ContractError('panel_schema_invalid', 'Unknown service schema fields; credentials are not accepted')
        identifier = _required(raw.get('id'), 'service id', 80)
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', identifier):
            raise ContractError('panel_schema_invalid', 'Invalid service id')
        endpoint = raw.get('endpoint') or ''
        if not isinstance(endpoint, str) or len(endpoint) > 500 or re.search(r'://[^/]*@', endpoint):
            raise ContractError('panel_schema_invalid', 'Endpoint metadata must not contain credentials')
        try:
            parsed_endpoint = urlsplit(endpoint)
        except ValueError as exc:
            raise ContractError('panel_schema_invalid', 'Invalid endpoint metadata') from exc
        if parsed_endpoint.query or parsed_endpoint.fragment:
            raise ContractError('panel_schema_invalid', 'Endpoint metadata cannot contain query strings or fragments')
        if not isinstance(raw.get('owner', ''), str):
            raise ContractError('panel_schema_invalid', 'Service owner must be text')
        service = {'id': identifier, 'name': _required(raw.get('name'), 'service name', 120),
                   'kind': _required(raw.get('kind', 'Local synthetic'), 'service kind', 80),
                   'endpoint': endpoint, 'owner': str(raw.get('owner') or '')[:120],
                   'verified': None, 'verification': {'status': 'not_verified', 'scope': 'local_synthetic_schema'},
                   'actions': []}
        actions = raw.get('actions')
        if not isinstance(actions, list) or not 1 <= len(actions) <= 100:
            raise ContractError('panel_schema_invalid', 'A service needs 1–100 actions')
        names = set()
        for action in actions:
            if not isinstance(action, dict):
                raise ContractError('panel_schema_invalid', 'Action schema must be an object')
            if set(action) - {'name', 'desc', 'destructive', 'params'}:
                raise ContractError('panel_schema_invalid', 'Unknown action schema fields')
            if not isinstance(action.get('desc', ''), str) or type(action.get('destructive', False)) is not bool:
                raise ContractError('panel_schema_invalid', 'Action description and destructive flag have invalid types')
            name = _required(action.get('name'), 'action name', 80)
            if name in names or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', name):
                raise ContractError('panel_schema_invalid', 'Action names must be valid and unique')
            names.add(name)
            params = action.get('params', [])
            if not isinstance(params, list) or len(params) > 50:
                raise ContractError('panel_schema_invalid', 'Action params must be a list with at most 50 entries')
            fields, typed = set(), []
            for param in params:
                if not isinstance(param, dict):
                    raise ContractError('panel_schema_invalid', 'Parameter schema must be an object')
                if set(param) - {'name', 'type', 'required'}:
                    raise ContractError('panel_schema_invalid', 'Unknown parameter schema fields')
                field = _required(param.get('name'), 'parameter name', 80)
                if field in fields or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', field):
                    raise ContractError('panel_schema_invalid', 'Parameter names must be valid and unique')
                kind = param.get('type', 'string')
                if kind not in ('string', 'number', 'boolean') or type(param.get('required', False)) is not bool:
                    raise ContractError('panel_schema_invalid', 'Unsupported parameter type or required flag')
                fields.add(field)
                typed.append({'name': field, 'type': kind, 'required': param.get('required', False)})
            service['actions'].append({'name': name, 'desc': str(action.get('desc') or '')[:1000],
                                      'destructive': bool(action.get('destructive')), 'params': typed})
        return service

    def _compare(self, state, body, principal):
        expected = _integer(body.get('expectedVersion'), 'expectedVersion', 1)
        if expected != state['policy']['version']:
            raise ConfigConflict('active_changed', 'The active panel policy version changed')
        policy, tests = deepcopy(body.get('policy')), deepcopy(body.get('tests', state['tests']))
        policy = _candidate(state, policy)
        self._tests(tests, state['services'])
        faults = body.get('faults') or {}
        if not isinstance(faults, dict) or any(value not in ('unknown', 'timeout') for value in faults.values()):
            raise ContractError('panel_schema_invalid', 'faults maps check ids to unknown or timeout')
        results = []
        complete = True
        for case in tests:
            req = self._request(case, state['services'], fixture=True)
            meta = case.get('meta') or {}
            if not isinstance(meta, dict):
                raise ContractError('panel_schema_invalid', 'Fixture meta must be an object')
            context = {'faults': faults, 'rpm': meta.get('rpm', 0), 'similar': meta.get('similar', 0),
                       'tokens_over': meta.get('tokens_over', False),
                       'tokens_used': meta.get('tokens_used', 0),
                       'tokens_requested': meta.get('tokens_requested', max(1, (len(req['text'].encode()) + 3) // 4))}
            live, candidate = _evaluate(state['policy'], req, context), _evaluate(policy, req, context)
            unfinished = any(check.get('error') == 'evaluation_time_budget'
                             for result in (live, candidate) for check in result.get('checks', []))
            complete = complete and not unfinished
            decision = candidate['decision'] if candidate['decision'] != 'monitor' else 'allow'
            passed = not unfinished and decision == ('allow' if case['expected'] == 'monitor' else case['expected'])
            if passed and case.get('expected_output') is not None:
                passed = candidate.get('processed') == case['expected_output']
            results.append({'id': case['id'], 'live': live, 'draft': candidate, 'expected': case['expected'],
                            'passed': passed, 'changed': live['decision'] != candidate['decision']})
        identifier = str(uuid.uuid4())
        result = {'id': identifier, 'version': expected, 'candidateHash': _policy_hash(policy),
                  'results': results, 'complete': complete, 'passed': complete and all(row['passed'] for row in results),
                  'targetDispatchCount': 0, 'semanticMode': 'baseline', 'modelCalls': 0,
                  'registryRevision': state['registryRevision'], 'faults': faults,
                  'budgetContext': 'Independent fixtures: estimated input tokens plus explicit tokens_used (default 0); no live counters are consumed.'}
        state['evaluations'][identifier] = {'version': expected, 'candidateHash': _policy_hash(policy),
            'testsHash': _hash(tests), 'storedTestsHash': _hash(state['tests']), 'registryRevision': state['registryRevision'],
            'complete': complete, 'passed': result['passed'], 'faults': faults, 'actor': principal.id,
            'at': _now(), 'failedCases': [row['id'] for row in results if not row['passed']]}
        # Evidence stores hashes and verdicts, not copies of ad-hoc input text.
        result['results'] = [dict(row, live=_clean_result(row['live']), draft=_clean_result(row['draft'])) for row in results]
        return result

    def _activate(self, state, body, principal):
        expected = _integer(body.get('expectedVersion'), 'expectedVersion', 1)
        if expected != state['policy']['version']:
            raise ConfigConflict('active_changed', 'The active panel policy version changed')
        policy, tests = deepcopy(body.get('policy')), deepcopy(body.get('tests', state['tests']))
        policy = _candidate(state, policy)
        self._tests(tests, state['services'])
        evidence = state['evaluations'].get(body.get('evaluationId'))
        if not evidence:
            raise ConfigConflict('evaluation_required', 'A stored comparison is required')
        if (evidence['version'] != expected or evidence['candidateHash'] != _policy_hash(policy)
                or evidence['testsHash'] != _hash(tests) or evidence['storedTestsHash'] != _hash(state['tests'])
                or evidence['registryRevision'] != state['registryRevision']):
            raise ConfigConflict('evaluation_stale', 'Policy, tests, registry or active version changed after comparison')
        if evidence['faults']:
            raise ConfigConflict('simulated_evaluation', 'Fault-injection comparisons cannot authorize activation')
        if not evidence['complete'] or (not evidence['passed'] and body.get('overrideMismatches') is not True):
            raise ConfigConflict('evaluation_mismatch', 'Confirm the mismatches explicitly or fix the candidate')
        previous = state['policy']
        if _policy_hash(policy) == _policy_hash(previous):
            raise ConfigConflict('no_change', 'The candidate policy is already active')
        policy['version'] = expected + 1
        source = body.get('source', 'Console')
        source = source if source in ('Console', 'Rollback', 'Import') else 'Console'
        state['policy'], state['tests'] = policy, tests
        state['draft'] = {'policy': deepcopy(policy), 'revision': state['draft']['revision'] + 1,
                          'id': state['draft']['id'], 'baseVersion': policy['version']}
        state['history'].append({'v': policy['version'], 'policy': deepcopy(policy), 'author': principal.id,
            'source': source, 'at': _now(), 'ops': _diff(previous, policy),
            'summary': _clean(str(body.get('reason') or 'Policy activated after comparison')[:500]),
            'evaluationId': body['evaluationId'], 'overrideMismatches': body.get('overrideMismatches') is True,
            'failedCases': evidence['failedCases']})

    def _invoke(self, state, body, principal):
        if set(body) - {'request', 'idempotencyKey', 'onBehalfOf'}:
            raise ContractError('panel_schema_invalid', 'Unknown invocation fields; runtime fault/context overrides are not allowed')
        identifier = _required(body.get('idempotencyKey'), 'idempotencyKey', 200)
        raw = deepcopy(body.get('request'))
        if not isinstance(raw, dict):
            raise ContractError('panel_schema_invalid', 'request must be an object')
        if principal.role != 'operator':
            raw['agent'] = principal.id
            if body.get('onBehalfOf') not in (None, principal.id):
                raise ContractError('on_behalf_denied', 'Only operators can choose a synthetic agent', 403)
        elif body.get('onBehalfOf') not in (None, raw.get('agent')):
            raise ContractError('panel_schema_invalid', 'onBehalfOf must match the selected synthetic agent')
        req = self._request(raw, state['services'])
        fingerprint = hmac.new(bytes.fromhex(state['hashSalt']), _json(req).encode(), sha256).hexdigest()
        claim_key = _hash([principal.id, identifier])
        existing = state['claims'].get(claim_key)
        if existing:
            if existing['fingerprint'] != fingerprint:
                raise ConfigConflict('idempotency_conflict', 'This principal already used the key for another request')
            event = deepcopy(next(row for row in state['events'] if row['id'] == existing['eventId']))
            event['replayed'] = True
            return event, False
        now, started = _now(), time.perf_counter()
        period = now[:10]
        token_estimate = max(1, (len(req['text'].encode()) + 3) // 4)
        usage_key = _json([req['agent'], period])
        usage = state['usage'].get(usage_key, 0)
        recent = [event for event in state['events'] if event['req']['agent'] == req['agent']
                  and (datetime.fromisoformat(now.replace('Z', '+00:00'))
                       - datetime.fromisoformat(event['ts'].replace('Z', '+00:00'))).total_seconds() < 60]
        projection = hmac.new(bytes.fromhex(state['hashSalt']), _json(req).encode(), sha256).hexdigest()
        context = {'rpm': len(recent) + 1,
                   'similar': sum(event.get('projection') == projection for event in recent) + 1,
                   'tokens_used': usage, 'tokens_requested': token_estimate}
        policy = deepcopy(state['policy'])
        result = _evaluate(policy, req, context)
        event_id = 'req_' + str(uuid.uuid4())
        action = {'outcome': 'not_started', 'dispatched': False, 'detail': {}}
        output = {'disclosure': 'none', 'text': None}
        output_result = None
        if result['decision'] not in ('block', 'throttle'):
            if req['dir'] == 'tool_call':
                action, text = self._effect(state, req, result, event_id, now)
            else:
                action = {'outcome': 'succeeded', 'dispatched': False,
                          'detail': {'scope': 'content-only', 'note': 'Content evaluated locally; no model provider was called.'}}
                text = result.get('processed') or ''
            if text is not None:
                out_req = dict(req, dir='output', text=text, target=req.get('target') or 'llama3.1:8b')
                output_result = _evaluate(policy, out_req, dict(context, rpm=0, similar=0, tokens_requested=0))
                if output_result['decision'] in ('block', 'throttle'):
                    output = {'disclosure': 'withheld', 'text': None}
                else:
                    disclosed = _clean(output_result.get('processed') or '')
                    output = {'disclosure': 'redacted' if (output_result['decision'] == 'redact' or disclosed != text) else 'full',
                              'text': disclosed}
            state['usage'][usage_key] = usage + token_estimate
        elif result['decision'] == 'throttle':
            action['detail'] = {'reason': 'throttled', 'retryAfterMs': result.get('throttle') or 1000,
                                'note': 'Admission refused; no sleep, queue or dispatch occurred.'}
        safe_req = _clean_request(req)
        if output['disclosure'] == 'withheld' and output_result:
            # A withheld result must not be reconstructed from its trace or training examples.
            output_result = deepcopy(output_result)
            output_result['processed'] = None
            output_result['marks'] = []
            output_result['triggerDetail'] = 'Output withheld by policy'
            for check in output_result.get('checks', []):
                if 'input' in check:
                    check['input'] = '[WITHHELD OUTPUT]'
                check['detail'] = 'Output withheld; content omitted from the trace'
        event = {'id': event_id, 'ts': now, 'req': safe_req, 'r': _clean_result(result), 'key': '',
                 'user': principal.id, 'actor': principal.id, 'onBehalfOf': req['agent'] if principal.role == 'operator' else None,
                 'session': [], 'fp': False, 'tokens': token_estimate if result['decision'] not in ('block', 'throttle') else 0,
                 'tokensStatus': 'synthetic_estimate', 'tokensEstimated': token_estimate,
                 'usageKind': 'estimated', 'projection': projection, 'replayed': False,
                 'evaluationContext': deepcopy(context),
                 'action': _clean(action), 'output': output, 'outputR': _clean_result(output_result),
                 'policy': {'decision': result['decision'], 'outputDecision': output_result['decision'] if output_result else 'not_run',
                            'version': policy['version']},
                 'semanticMode': 'baseline', 'sanitized': True,
                 'latencyMs': round((time.perf_counter() - started) * 1000, 3)}
        # Every content-bearing nested field was scrubbed above. Correlation ids and trusted
        # typed metadata retain their exact values, including timestamp-shaped ids.
        state['events'].append(event)
        state['corpus'][event_id] = safe_req
        state['claims'][claim_key] = {'fingerprint': fingerprint, 'eventId': event_id}
        state['audit'].append({'id': event_id, 'at': now, 'actor': principal.id, 'agent': req['agent'],
            'policyVersion': policy['version'], 'decision': result['decision'],
            'actionOutcome': action['outcome'], 'disclosure': output['disclosure']})
        self._training(state, event, policy, result, output_result)
        return event, True

    @staticmethod
    def _effect(state, req, result, event_id, now):
        # The only adapters are local state transformations. Catalog endpoint strings are inert.
        params = result.get('processedParams')
        if not isinstance(params, dict):
            raise ContractError('panel_evaluation_invalid', 'An admitted call requires processed parameters', 503)
        service, action = req['service'], req['action']
        detail = {'adapter': 'local-synthetic', 'service': service, 'action': action}
        text = 'Synthetic local action completed. No external system was contacted.'
        outcome = 'succeeded'
        if service == 'documents':
            doc_id = params.get('doc_id')
            # Selection uses exactly the engine-approved argument. New identifiers are keyed so
            # the document index itself cannot retain a sensitive user-supplied identifier.
            doc_key = hmac.new(bytes.fromhex(state['hashSalt']), str(doc_id).encode(), sha256).hexdigest()
            if doc_id in ('KB-1042', 'POL-0007'):
                doc_key = doc_id
            record = state['documents'].get(doc_key)
            if action == 'read':
                if not record or record.get('deleted'):
                    outcome, text = 'failed', 'Synthetic document not found.'
                else:
                    text = record['text']
            elif action == 'search':
                query = str(params.get('query', '')).lower()
                found = [value.get('id', key) for key, value in state['documents'].items()
                         if not value.get('deleted') and query in value['text'].lower()]
                limit = max(0, int(params.get('limit', 10)))
                text = json.dumps(found[:limit])
            elif action == 'update':
                state['documents'][doc_key] = {'id': _clean(doc_id), 'text': _clean(params.get('content', '')), 'deleted': False}
                text = 'Synthetic document updated.'
            elif action == 'delete':
                if not record or record.get('deleted'):
                    outcome, text = 'failed', 'Synthetic document not found.'
                else:
                    record['deleted'] = True
                    text = 'Synthetic document deleted.'
        state['effects'].append({'eventId': event_id, 'at': now, 'service': service,
                                'action': action, 'params': _clean(params), 'outcome': outcome})
        return {'outcome': outcome, 'dispatched': True, 'detail': detail}, text

    @staticmethod
    def _training(state, event, policy, result, output_result):
        for evaluation in (result, output_result):
            if not evaluation:
                continue
            for check in evaluation.get('checks', []):
                if check.get('kind') != 'ai' or not (check.get('label') or check.get('timeout')):
                    continue
                definition = next((node for node in policy['checks'] if node['id'] == check['id']), {})
                example = {'id': 'ex_' + str(uuid.uuid4()), 'ts': event['ts'], 'checkId': check['id'],
                    'check': check['name'], 'model': 'deterministic-baseline',
                    'instruction_version': check.get('instruction_version', 1), 'policy_version': policy['version'],
                    'input': check.get('input') or '', 'label': check.get('label') or '(timeout)',
                    'review': 'unreviewed', 'corrected': None, 'lat': check.get('lat', 0),
                    'tokens_in': 0, 'tokens_out': 0, 'cache': 'not_applicable', 'eventId': event['id'],
                    'semanticMode': 'baseline', 'detector': 'deterministic-baseline-v1',
                    'allowedLabels': [item['label'] for item in definition.get('labels', [])]}
                example['input'] = _clean(example['input'])
                state['training'].append(example)
