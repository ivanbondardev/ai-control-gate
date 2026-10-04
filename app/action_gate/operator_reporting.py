"""Read-only, content-free reporting across the three durable execution surfaces."""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json

from .contracts import ContractError
from .storage.memory import encode_cursor, decode_cursor
from .storage.operations import build_operations


def stamp(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    return value


class OperatorReporting:
    def __init__(self, repository, panel, operations=None):
        self.repository, self.panel = repository, panel
        self.operations = operations or build_operations(repository)

    def supplemental(self, since, until, principal_id=None):
        rows = []
        with self.panel._transaction() as state:
            events = list(state['events'])
        for e in events:
            if not since <= e['ts'] <= until or (principal_id and e['actor'] != principal_id):
                continue
            rows.append({'event_id': 'panel:' + e['id'], 'invocation_id': e['id'],
                'created_at': e['ts'], 'kind': 'panel_outcome', 'source': 'panel',
                'principal_id': e['actor'], 'agent': e['req']['agent'], 'model': None,
                'target': e['req'].get('service') or e['req'].get('target'),
                'decision': e['r']['decision'], 'action_outcome': e['action']['outcome'],
                'dispatched': e['action']['dispatched'], 'disclosure': e['output']['disclosure'],
                'policy_version': e['r']['version'], 'tokensEstimated': e['tokens'],
                'usageKind': 'synthetic_estimate', 'reviewedFalsePositive': bool(e.get('fp'))})
        for e in self.operations.report_operations(since, until):
            if principal_id and e['principal_id'] != principal_id:
                continue
            rows.append({'event_id': 'mcp:' + str(e['id']), 'invocation_id': str(e['id']),
                'created_at': stamp(e['created_at']), 'kind': 'mcp_outcome', 'source': 'mcp',
                'principal_id': e['principal_id'], 'agent': e['principal_id'], 'model': None,
                'target': e['published_tool'], 'decision': e['decision'],
                'action_outcome': e['status'], 'dispatched': e.get('dispatch_started_at') is not None,
                'disclosure': e.get('disclosure', 'none'), 'policy_version': e['policy_version'],
                'receipt_id': e.get('receipt_id'), 'upstream_operation_id': e.get('upstream_operation_id'),
                'usageKind': 'not_model_usage'})
        return rows

    def audit_page(self, since, until, limit, cursor=None, filters=None):
        filters = filters or {}
        fingerprint = sha256(json.dumps([since, until, filters], sort_keys=True).encode()).hexdigest()
        position = decode_cursor(cursor)
        if cursor and not position:
            raise ContractError('invalid_cursor', 'Invalid report cursor')
        if position and (not isinstance(position, dict) or position.get('f') != fingerprint
                         or not isinstance(position.get('t'), str) or not isinstance(position.get('i'), str)):
            raise ContractError('invalid_cursor', 'Cursor belongs to a different report window or filter')
        rows = self.supplemental(since, until, filters.get('principal_id'))
        if filters.get('kind'):
            rows = [r for r in rows if r['kind'] == filters['kind']]
        legacy_cursor = None
        while True:
            page = self.repository.list_events_page(since, until, 1000, legacy_cursor, filters)
            rows.extend(page['events'])
            legacy_cursor = page['nextCursor']
            if not legacy_cursor:
                break
        key = lambda r: (stamp(r['created_at']), str(r['event_id']))
        rows.sort(key=key)
        if position:
            rows = [r for r in rows if key(r) > (position['t'], position['i'])]
        selected = rows[:limit]
        more = len(rows) > limit
        token = encode_cursor(dict(t=key(selected[-1])[0], i=key(selected[-1])[1], f=fingerprint)) if more else None
        return {'events': selected, 'nextCursor': token, 'truncated': more}

    def report(self, since, until, principal_id=None):
        rows = self.supplemental(since, until, principal_id)
        cursor = None
        while True:
            page = self.repository.list_invocations(since, until, 1000, cursor,
                                                    {'principal_id': principal_id} if principal_id else {})
            for item in page['invocations']:
                e = self.repository.get_invocation(item['invocationId'])
                rows.append({'invocation_id': e['invocation_id'], 'created_at': stamp(e['created_at']),
                    'source': 'model' if e['service_id'] == 'openai' else 'legacy',
                    'agent': e['principal_id'], 'target': e['service_id'] + '.' + e['action_id'],
                    'decision': e['decision'], 'action_outcome': e['action_outcome'],
                    'disclosure': e['disclosure'], 'usageKind': 'see_shared_ledger',
                    'model': (e.get('response') or {}).get('model'),
                    'providerReportedTokens': ((e.get('response') or {}).get('usage') or {}).get('total_tokens'),
                    'usageKnown': (e.get('response') or {}).get('usage') is not None})
            cursor = page['nextCursor']
            if not cursor:
                break
        rows.sort(key=lambda r: (r['created_at'], r['invocation_id']))
        groups = {}
        for r in rows:
            key = (r['source'], r['agent'], r.get('model'))
            g = groups.setdefault(key, {'source': key[0], 'agent': key[1], 'model': key[2],
                                       'requests': 0, 'syntheticEstimatedTokens': 0, 'providerReportedTokens': 0, 'unknownModelUsage': 0})
            g['requests'] += 1
            g['providerReportedTokens'] += r.get('providerReportedTokens') or 0
            g['unknownModelUsage'] += int(r['source'] == 'model' and not r.get('usageKnown'))
            g['syntheticEstimatedTokens'] += r.get('tokensEstimated', 0)
        return {'window': {'since': since, 'until': until}, 'total': len(rows),
                'bySource': dict(Counter(r['source'] for r in rows)),
                'decisions': dict(Counter(r['decision'] for r in rows)),
                'byAgentModel': list(groups.values()), 'records': rows,
                'note': 'One record per operation; blocks are not confirmed attacks. Synthetic token estimates are not provider billing. Snapshot of currently available records; in-flight outcomes may change.'}
