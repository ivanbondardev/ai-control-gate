"""Durable store for remote MCP execution.

One logical client operation is one ``mcp_operations`` row. The row is the durable claim that makes
retries safe, the anchor for the audit trail and the place where an unknown outcome stays visible
until an operator reconciles or fences it.

Three invariants are enforced here rather than in the caller:

* ``UNIQUE (demo_run_id, principal_id, client_operation_key)`` — replay is decided by the database,
  not by a cache;
* a replayed key with a different request fingerprint is a conflict, including for a claim that has
  already finished;
* rate accounting counts attempts, and a replay of a completed claim records no new attempt.

Both a PostgreSQL implementation and an in-memory implementation are provided. The runtime uses
PostgreSQL; the memory implementation exists so the coordinator's state machine can be tested
without a database.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import threading
import uuid

STATUS_CLAIMED = 'claimed'
STATUS_BLOCKED = 'not_started'
STATUS_DISPATCH_STARTED = 'dispatch_started'
STATUS_SUCCEEDED = 'succeeded'
STATUS_FAILED = 'failed'
STATUS_UNKNOWN = 'outcome_unknown'
STATUS_INTERRUPTED = 'interrupted'

TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_BLOCKED, STATUS_INTERRUPTED)

# Advisory lock key shared by policy activation and admission. Both paths take it for a short
# transaction so that "which policy version admitted this operation" has one answer.
MCP_ADMISSION_LOCK_KEY = 0x4D43504C  # 'MCPL'


class OperationsError(RuntimeError):
    def __init__(self, code, detail=None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class IdempotencyConflict(OperationsError):
    def __init__(self, detail='This operation key was already used with a different request'):
        super().__init__('idempotency_conflict', detail)


def utc_now():
    return datetime.now(timezone.utc)


class BaseOperations:
    """Interface shared by both implementations."""

    def health(self):
        raise NotImplementedError

    def run_state(self):
        raise NotImplementedError

    def set_run_state(self, run_id=None, admission_open=None, note=None):
        raise NotImplementedError

    def claim(self, record):
        raise NotImplementedError

    def record_attempt(self, record):
        raise NotImplementedError

    def rate_context(self, principal_id, fingerprint, window_seconds=60):
        raise NotImplementedError

    def mark_dispatch_started(self, operation_id, lease, lease_seconds, upstream_operation_id=None):
        raise NotImplementedError

    def finish(self, operation_id, fields):
        raise NotImplementedError

    def reserve(self, record):
        raise NotImplementedError

    def release(self, operation_id, reason):
        raise NotImplementedError

    def open_reservations(self, service_id, run_id=None):
        raise NotImplementedError

    def audit(self, event):
        raise NotImplementedError

    def get(self, operation_id):
        raise NotImplementedError

    def list_operations(self, run_id=None, status=None, limit=200):
        raise NotImplementedError

    def close_interrupted(self, run_id):
        raise NotImplementedError

    def counters(self, run_id=None):
        raise NotImplementedError

    # -- registry ------------------------------------------------------------------
    def publish_registry(self, document, document_hash, source, created_by):
        raise NotImplementedError

    def active_registry(self):
        raise NotImplementedError

    def registry_revision(self, revision):
        raise NotImplementedError

    def record_service_health(self, service_id, connection_ref, status, detail):
        raise NotImplementedError

    def service_health(self):
        raise NotImplementedError


class MemoryOperations(BaseOperations):
    """Thread-safe in-memory store with the same semantics as PostgreSQL."""

    def __init__(self, run_id='run-0001'):
        self._lock = threading.RLock()
        self.operations = {}
        self.claims = {}
        self.attempts = []
        self.events = []
        self.reservations = {}
        self.registries = []
        self.health = {}
        self.state = {'run_id': run_id, 'admission_open': True, 'updated_at': utc_now(),
                      'note': 'memory'}

    def health(self):
        return {'backend': 'memory', 'durable': False}

    def run_state(self):
        with self._lock:
            return dict(self.state)

    def set_run_state(self, run_id=None, admission_open=None, note=None):
        with self._lock:
            if run_id is not None:
                self.state['run_id'] = run_id
            if admission_open is not None:
                self.state['admission_open'] = bool(admission_open)
            if note is not None:
                self.state['note'] = note
            self.state['updated_at'] = utc_now()
            return dict(self.state)

    def claim(self, record):
        with self._lock:
            if not self.state['admission_open'] or record['demo_run_id'] != self.state['run_id']:
                raise OperationsError('admission_closed')
            key = (record['demo_run_id'], record['principal_id'], record['client_operation_key'])
            existing = self.claims.get(key)
            row = dict(record)
            row.setdefault('id', str(record.get('id') or uuid.uuid4()))
            row['created_at'] = utc_now()
            row['updated_at'] = row['created_at']
            row.setdefault('status', STATUS_CLAIMED)
            row.setdefault('decision', 'pending')
            row.setdefault('disclosure', 'none')
            row.setdefault('attempts', 0)
            if existing is not None:
                if existing['request_fingerprint'] != record['request_fingerprint']:
                    raise IdempotencyConflict()
                return {'row': dict(existing), 'created': False}
            self.claims[key] = row
            self.operations[row['id']] = row
            return {'row': dict(row), 'created': True}

    def record_attempt(self, record):
        with self._lock:
            self.attempts.append(dict(record, at=utc_now()))
            row = self.operations.get(record.get('operation_id'))
            if row is not None:
                row['attempts'] = row.get('attempts', 0) + 1

    def rate_context(self, principal_id, fingerprint, window_seconds=60):
        with self._lock:
            since = utc_now() - timedelta(seconds=window_seconds)
            recent = [row for row in self.attempts
                      if row['principal_id'] == principal_id and row['at'] >= since]
            similar = [row for row in recent if row.get('request_fingerprint') == fingerprint]
            return {'attempts': len(recent), 'similar': len(similar)}

    def mark_dispatch_started(self, operation_id, lease, lease_seconds, upstream_operation_id=None):
        with self._lock:
            row = self.operations.get(operation_id)
            if row is None:
                raise OperationsError('operation_unknown', operation_id)
            row.update(status=STATUS_DISPATCH_STARTED, owner_lease=lease,
                       upstream_operation_id=upstream_operation_id,
                       lease_expires_at=utc_now() + timedelta(seconds=lease_seconds),
                       dispatch_started_at=utc_now(), updated_at=utc_now())
            return dict(row)

    def finish(self, operation_id, fields):
        with self._lock:
            row = self.operations.get(operation_id)
            if row is None:
                raise OperationsError('operation_unknown', operation_id)
            payload = {key: value for key, value in fields.items() if value is not None}
            if 'result' in payload:
                payload['result_document'] = payload.pop('result')
            row.update(payload)
            row['finished_at'] = utc_now()
            row['updated_at'] = utc_now()
            return dict(row)

    def reserve(self, record):
        with self._lock:
            if record['operation_id'] in self.reservations and \
                    self.reservations[record['operation_id']].get('released_at') is None:
                return False
            self.reservations[record['operation_id']] = dict(record, acquired_at=utc_now(),
                                                             released_at=None)
            return True

    def release(self, operation_id, reason):
        with self._lock:
            row = self.reservations.get(operation_id)
            if row is None or row.get('released_at') is not None:
                return False
            row['released_at'] = utc_now()
            row['release_reason'] = reason
            return True

    def open_reservations(self, service_id, run_id=None):
        with self._lock:
            return sum(1 for row in self.reservations.values()
                       if row['service_id'] == service_id and row.get('released_at') is None
                       and (run_id is None or row['demo_run_id'] == run_id))

    def audit(self, event):
        with self._lock:
            self.events.append(dict(event, at=utc_now()))

    def get(self, operation_id):
        with self._lock:
            row = self.operations.get(operation_id)
            return dict(row) if row else None

    def report_operations(self, since, until):
        def stamp(value):
            return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z') if isinstance(value, datetime) else value
        with self._lock:
            return [dict(row) for row in self.operations.values() if since <= stamp(row['created_at']) <= until]

    def list_operations(self, run_id=None, status=None, limit=200):
        with self._lock:
            rows = [dict(row) for row in self.operations.values()
                    if (run_id is None or row['demo_run_id'] == run_id)
                    and (status is None or row['status'] == status)]
            rows.sort(key=lambda row: row['created_at'])
            return rows[:limit]

    def close_interrupted(self, run_id):
        with self._lock:
            closed = []
            for row in self.operations.values():
                if row['demo_run_id'] == run_id and row['status'] == STATUS_CLAIMED:
                    row.update(status=STATUS_INTERRUPTED, decision='allow',
                               reason='gate restarted before dispatch', finished_at=utc_now())
                    closed.append(dict(row))
            return closed

    def counters(self, run_id=None):
        with self._lock:
            rows = [row for row in self.operations.values()
                    if run_id is None or row['demo_run_id'] == run_id]
            by_status = {}
            for row in rows:
                by_status[row['status']] = by_status.get(row['status'], 0) + 1
            upstream = sum(1 for row in self.attempts if row.get('upstream_called'))
            return {'operations': len(rows), 'byStatus': by_status,
                    'upstreamCalls': upstream, 'attempts': len(self.attempts),
                    'openReservations': sum(1 for row in self.reservations.values()
                                            if row.get('released_at') is None)}

    # -- registry ------------------------------------------------------------------
    def publish_registry(self, document, document_hash, source, created_by):
        with self._lock:
            revision = len(self.registries) + 1
            for row in self.registries:
                row['active'] = False
            self.registries.append({'revision': revision, 'document_hash': document_hash,
                                    'document': document, 'source': source,
                                    'created_by': created_by, 'active': True,
                                    'created_at': utc_now()})
            return revision

    def active_registry(self):
        with self._lock:
            row = next((row for row in self.registries if row['active']), None)
            return dict(row) if row else None

    def registry_revision(self, revision):
        with self._lock:
            row = next((row for row in self.registries if row['revision'] == revision), None)
            return dict(row) if row else None

    def record_service_health(self, service_id, connection_ref, status, detail):
        with self._lock:
            self.health[service_id] = {'service_id': service_id, 'connection_ref': connection_ref,
                                       'status': status, 'detail': detail, 'checked_at': utc_now()}

    def service_health(self):
        with self._lock:
            return [dict(row) for row in self.health.values()]


class PostgresOperations(BaseOperations):
    """Durable implementation. Every method uses a short transaction."""

    def __init__(self, repository):
        self.repository = repository

    @contextmanager
    def _cursor(self):
        with self.repository.raw_connection() as connection:
            with connection.cursor() as cursor:
                yield cursor

    @staticmethod
    def _row(cursor):
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row))

    def health(self):
        return self.repository.health()

    def run_state(self):
        with self._cursor() as cursor:
            cursor.execute('SELECT run_id, admission_open, updated_at, note FROM demo_run_state '
                           "WHERE id = 'default'")
            row = self._row(cursor)
            if row is None:
                return {'run_id': 'run-0001', 'admission_open': True, 'updated_at': None,
                        'note': 'not initialised'}
            return row

    def set_run_state(self, run_id=None, admission_open=None, note=None):
        with self._cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (MCP_ADMISSION_LOCK_KEY,))
            cursor.execute(
                'INSERT INTO demo_run_state (id, run_id, admission_open, note) '
                "VALUES ('default', COALESCE(%s, 'run-0001'), COALESCE(%s, true), %s) "
                'ON CONFLICT (id) DO UPDATE SET run_id = COALESCE(%s, demo_run_state.run_id), '
                'admission_open = COALESCE(%s, demo_run_state.admission_open), '
                'note = COALESCE(%s, demo_run_state.note), updated_at = now() '
                'RETURNING run_id, admission_open, updated_at, note',
                (run_id, admission_open, note, run_id, admission_open, note))
            return self._row(cursor)

    def claim(self, record):
        from psycopg.types.json import Jsonb
        columns = ('id', 'demo_run_id', 'principal_id', 'client_operation_key',
                   'request_fingerprint', 'request_id', 'published_tool', 'upstream_tool',
                   'service_id', 'panel_service', 'panel_action', 'registry_revision',
                   'policy_version', 'policy_hash', 'status', 'decision')
        row = dict(record)
        row.setdefault('id', str(uuid.uuid4()))
        row.setdefault('status', STATUS_CLAIMED)
        row.setdefault('decision', 'pending')
        with self._cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (MCP_ADMISSION_LOCK_KEY,))
            cursor.execute("SELECT run_id, admission_open FROM demo_run_state WHERE id = 'default'")
            state = cursor.fetchone()
            if state and (not state[1] or state[0] != record['demo_run_id']):
                raise OperationsError('admission_closed')
            placeholders = ', '.join(['%s'] * len(columns))
            cursor.execute(
                f'INSERT INTO mcp_operations ({", ".join(columns)}) VALUES ({placeholders}) '
                'ON CONFLICT ON CONSTRAINT mcp_operations_client_key DO NOTHING RETURNING id',
                tuple(row.get(column) for column in columns))
            inserted = cursor.fetchone() is not None
            cursor.execute(
                'SELECT *, result_document FROM mcp_operations WHERE demo_run_id = %s AND '
                'principal_id = %s AND client_operation_key = %s',
                (record['demo_run_id'], record['principal_id'], record['client_operation_key']))
            existing = self._row(cursor)
            if existing is None:  # pragma: no cover - the insert above cannot lose the row
                raise OperationsError('claim_unavailable')
            if existing['request_fingerprint'] != record['request_fingerprint']:
                raise IdempotencyConflict()
            return {'row': existing, 'created': inserted}

    def record_attempt(self, record):
        with self._cursor() as cursor:
            cursor.execute(
                'INSERT INTO mcp_attempts (operation_id, demo_run_id, principal_id, service_id, '
                'published_tool, outcome, admitted) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (record.get('operation_id'), record['demo_run_id'], record['principal_id'],
                 record['service_id'], record['published_tool'], record['outcome'],
                 bool(record.get('admitted'))))
            if record.get('operation_id'):
                cursor.execute('UPDATE mcp_operations SET attempts = attempts + 1, updated_at = now() '
                               'WHERE id = %s', (record['operation_id'],))

    def rate_context(self, principal_id, fingerprint, window_seconds=60):
        with self._cursor() as cursor:
            cursor.execute(
                'SELECT COUNT(*) AS attempts, COUNT(*) FILTER (WHERE request_fingerprint = %s) '
                'AS similar FROM mcp_attempts a JOIN mcp_operations o ON o.id = a.operation_id '
                'WHERE a.principal_id = %s AND a.at > now() - make_interval(secs => %s)',
                (fingerprint, principal_id, window_seconds))
            row = self._row(cursor)
            return {'attempts': row['attempts'], 'similar': row['similar']}

    def mark_dispatch_started(self, operation_id, lease, lease_seconds, upstream_operation_id=None):
        with self._cursor() as cursor:
            cursor.execute(
                'UPDATE mcp_operations SET status = %s, owner_lease = %s, upstream_operation_id = %s, '
                'lease_expires_at = now() + make_interval(secs => %s), dispatch_started_at = now(), '
                'updated_at = now() WHERE id = %s RETURNING *',
                (STATUS_DISPATCH_STARTED, lease, upstream_operation_id, lease_seconds, operation_id))
            row = self._row(cursor)
            if row is None:
                raise OperationsError('operation_unknown', str(operation_id))
            return row

    def finish(self, operation_id, fields):
        from psycopg.types.json import Jsonb
        allowed = ('status', 'decision', 'reason', 'disclosure', 'receipt_id', 'resource_id',
                   'before_version', 'after_version', 'error_code', 'bytes_in', 'bytes_out',
                   'admission_ms', 'upstream_ms', 'output_ms', 'total_ms', 'upstream_operation_id')
        updates = {key: value for key, value in fields.items() if key in allowed}
        assignments = ', '.join(f'{key} = %s' for key in updates)
        values = list(updates.values())
        if 'result' in fields:
            assignments += ', result_document = %s'
            values.append(Jsonb(fields['result']) if fields['result'] is not None else None)
        if not assignments:
            assignments = 'updated_at = now()'
        values.append(operation_id)
        with self._cursor() as cursor:
            cursor.execute(
                f'UPDATE mcp_operations SET {assignments}, finished_at = now(), updated_at = now() '
                'WHERE id = %s RETURNING *', tuple(values))
            row = self._row(cursor)
            if row is None:
                raise OperationsError('operation_unknown', str(operation_id))
            return row

    def reserve(self, record):
        with self._cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (MCP_ADMISSION_LOCK_KEY,))
            cursor.execute(
                'INSERT INTO mcp_limit_reservations (operation_id, service_id, demo_run_id, '
                'principal_id) VALUES (%s, %s, %s, %s) '
                'ON CONFLICT (operation_id) DO UPDATE SET released_at = NULL, '
                'release_reason = NULL, acquired_at = now() WHERE '
                'mcp_limit_reservations.released_at IS NOT NULL RETURNING operation_id',
                (record['operation_id'], record['service_id'], record['demo_run_id'],
                 record['principal_id']))
            return cursor.fetchone() is not None

    def release(self, operation_id, reason):
        with self._cursor() as cursor:
            cursor.execute(
                'UPDATE mcp_limit_reservations SET released_at = now(), release_reason = %s '
                'WHERE operation_id = %s AND released_at IS NULL', (reason, operation_id))
            return cursor.rowcount > 0

    def open_reservations(self, service_id, run_id=None):
        with self._cursor() as cursor:
            cursor.execute(
                # The explicit cast keeps PostgreSQL able to infer the type of a NULL run filter.
                'SELECT COUNT(*) AS open FROM mcp_limit_reservations WHERE service_id = %s '
                'AND released_at IS NULL AND (%s::text IS NULL OR demo_run_id = %s::text)',
                (service_id, run_id, run_id))
            return self._row(cursor)['open']

    def audit(self, event):
        from psycopg.types.json import Jsonb
        with self._cursor() as cursor:
            cursor.execute(
                'INSERT INTO mcp_audit_events (operation_id, demo_run_id, principal_id, '
                'published_tool, upstream_tool, service_id, policy_version, policy_hash, '
                'registry_revision, decision, reason, effect_outcome, disclosure, receipt_id, '
                'request_id, detail) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '
                '%s, %s, %s)',
                (event.get('operation_id'), event['demo_run_id'], event['principal_id'],
                 event['published_tool'], event['upstream_tool'], event['service_id'],
                 event['policy_version'], event['policy_hash'], event['registry_revision'],
                 event['decision'], event.get('reason'), event['effect_outcome'],
                 event['disclosure'], event.get('receipt_id'), event.get('request_id'),
                 Jsonb(event.get('detail') or {})))

    def get(self, operation_id):
        with self._cursor() as cursor:
            cursor.execute('SELECT * FROM mcp_operations WHERE id = %s', (operation_id,))
            return self._row(cursor)

    def report_operations(self, since, until):
        with self._cursor() as cursor:
            cursor.execute('SELECT * FROM mcp_operations WHERE created_at >= %s AND created_at <= %s ORDER BY created_at, id', (since, until))
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def list_operations(self, run_id=None, status=None, limit=200):
        with self._cursor() as cursor:
            cursor.execute(
                'SELECT * FROM mcp_operations WHERE (%s::text IS NULL OR demo_run_id = %s::text) '
                'AND (%s::text IS NULL OR status = %s::text) ORDER BY created_at LIMIT %s',
                (run_id, run_id, status, status, limit))
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close_interrupted(self, run_id):
        with self._cursor() as cursor:
            cursor.execute(
                'UPDATE mcp_operations SET status = %s, decision = decision, '
                'reason = COALESCE(reason, %s), finished_at = now(), updated_at = now() '
                'WHERE demo_run_id = %s AND status = %s RETURNING *',
                (STATUS_INTERRUPTED, 'gate restarted before dispatch', run_id, STATUS_CLAIMED))
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def counters(self, run_id=None):
        with self._cursor() as cursor:
            cursor.execute(
                'SELECT status, COUNT(*) AS count FROM mcp_operations '
                'WHERE (%s::text IS NULL OR demo_run_id = %s::text) GROUP BY status',
                (run_id, run_id))
            by_status = {row[0]: row[1] for row in cursor.fetchall()}
            cursor.execute(
                'SELECT COUNT(*) FROM mcp_attempts WHERE (%s::text IS NULL OR demo_run_id = %s::text) '
                'AND admitted', (run_id, run_id))
            admitted = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM mcp_limit_reservations WHERE released_at IS NULL')
            open_reservations = cursor.fetchone()[0]
            return {'operations': sum(by_status.values()), 'byStatus': by_status,
                    'upstreamCalls': admitted, 'openReservations': open_reservations}

    # -- registry ------------------------------------------------------------------
    def publish_registry(self, document, document_hash, source, created_by):
        from psycopg.types.json import Jsonb
        with self._cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (MCP_ADMISSION_LOCK_KEY,))
            cursor.execute('UPDATE mcp_registry_revisions SET active = false WHERE active')
            cursor.execute('SELECT COALESCE(MAX(revision), 0) + 1 AS revision '
                           'FROM mcp_registry_revisions')
            revision = self._row(cursor)['revision']
            cursor.execute(
                'INSERT INTO mcp_registry_revisions (revision, document_hash, document, source, '
                'created_by, active) VALUES (%s, %s, %s, %s, %s, true)',
                (revision, document_hash, Jsonb(document), source, created_by))
            return revision

    def active_registry(self):
        with self._cursor() as cursor:
            cursor.execute('SELECT revision, document_hash, document, source, created_by, '
                           'created_at FROM mcp_registry_revisions WHERE active')
            return self._row(cursor)

    def registry_revision(self, revision):
        with self._cursor() as cursor:
            cursor.execute('SELECT revision, document_hash, document, source, created_by, '
                           'created_at FROM mcp_registry_revisions WHERE revision = %s', (revision,))
            return self._row(cursor)

    def record_service_health(self, service_id, connection_ref, status, detail):
        from psycopg.types.json import Jsonb
        with self._cursor() as cursor:
            cursor.execute(
                'INSERT INTO mcp_service_health (service_id, connection_ref, status, detail, '
                'checked_at) VALUES (%s, %s, %s, %s, now()) ON CONFLICT (service_id) DO UPDATE '
                'SET connection_ref = excluded.connection_ref, status = excluded.status, '
                'detail = excluded.detail, checked_at = now()',
                (service_id, connection_ref, status, Jsonb(detail)))

    def service_health(self):
        with self._cursor() as cursor:
            cursor.execute('SELECT service_id, connection_ref, status, detail, checked_at '
                           'FROM mcp_service_health ORDER BY service_id')
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def build_operations(repository):
    """Durable in production, in-memory only when the whole storage backend is in-memory."""
    if getattr(repository, 'name', '') == 'postgres':
        return PostgresOperations(repository)
    return MemoryOperations()
