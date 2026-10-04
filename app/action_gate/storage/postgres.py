"""PostgreSQL repository: the durable source of truth.

psycopg is imported lazily, so unit tests and the memory mode keep working on a stdlib-only
Python. Budget reservation is a single conditional UPDATE: two concurrent invocations cannot
reserve the same remainder twice.
"""
from contextlib import contextmanager
from datetime import datetime
import threading
import time

from .base import Repository, RepositoryError, iso_utc, utc_now_iso
from .memory import _invocation_public, _summarize, decode_cursor, encode_cursor, latency_stats,     _fingerprint
from ..audit import sanitize_detail

MIGRATION_APPLIED = 'schema_migrations'


def _ts(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class ConnectionPool:
    """Small bounded pool. Not a general-purpose pool: fixed size, no background reaping."""

    def __init__(self, conninfo: str, max_size: int = 8, timeout: float = 5.0):
        self._conninfo = conninfo
        self._max_size = max(1, max_size)
        self._timeout = timeout
        self._idle = []
        self._created = 0
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(self._max_size)

    def _connect(self):
        import psycopg
        connection = psycopg.connect(self._conninfo, autocommit=False,
                                     application_name='action-gate')
        with self._lock:
            self._created += 1
        return connection

    def _checkout(self):
        with self._lock:
            while self._idle:
                connection = self._idle.pop()
                if not connection.closed:
                    return connection
                self._created -= 1
        return self._connect()

    def _checkin(self, connection):
        if connection is None:
            return
        if connection.closed:
            with self._lock:
                self._created -= 1
            return
        with self._lock:
            self._idle.append(connection)

    @contextmanager
    def connection(self):
        if not self._slots.acquire(timeout=self._timeout):
            raise RepositoryError('storage_busy')
        connection = None
        try:
            connection = self._checkout()
            yield connection
            connection.commit()
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        finally:
            self._checkin(connection)
            self._slots.release()

    def close(self):
        with self._lock:
            for connection in self._idle:
                try:
                    connection.close()
                except Exception:
                    pass
            self._idle = []
            self._created = 0


class PostgresRepository(Repository):
    name = 'postgres'

    def __init__(self, conninfo: str, max_connections: int = 8):
        self._pool = ConnectionPool(conninfo, max_connections)
        self._conninfo = conninfo

    # -- plumbing ----------------------------------------------------------------
    def _json(self, value):
        from psycopg.types.json import Jsonb
        return Jsonb(value)

    def _rows(self, sql, params=()):
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                columns = [column.name for column in cursor.description] if cursor.description else []
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _one(self, sql, params=()):
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def _execute(self, sql, params=()):
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.rowcount

    def close(self):
        self._pool.close()

    @contextmanager
    def raw_connection(self):
        """A pooled connection for callers that need DDL (the migration runner)."""
        with self._pool.connection() as connection:
            yield connection

    # -- health ------------------------------------------------------------------
    def health(self) -> dict:
        row = self._one("""
            SELECT current_database() AS database,
                   (SELECT count(*) FROM invocation) AS invocations,
                   (SELECT count(*) FROM audit_event) AS events,
                   (SELECT count(*) FROM action_effect) AS effects
        """)
        return {'repository': self.name, 'durable': True, **row}

    # -- configuration releases ---------------------------------------------------
    def record_release(self, release: dict) -> None:
        self._execute("""
            INSERT INTO config_release (release_hash, bundle_id, components)
            VALUES (%s, %s, %s)
            ON CONFLICT (release_hash) DO NOTHING
        """, (release['release_hash'], release['bundle_id'], self._json(release['components'])))

    # -- invocations --------------------------------------------------------------
    def find_invocation(self, idempotency_key: str) -> dict | None:
        row = self._one("""
            SELECT invocation_id::text, idempotency_key, principal_id, request_hash, decision,
                   action_outcome, response, created_at
            FROM invocation WHERE idempotency_key = %s
        """, (idempotency_key,))
        if row is None:
            return None
        row['created_at'] = iso_utc(row['created_at'])
        return row

    def find_principal_invocation(self, principal_id: str, idempotency_key: str) -> dict | None:
        """Replay lookup scoped to the caller that owns the key.

        The physical key is unique per principal, so a key that is not owned by principal_id
        simply does not resolve here - it is never returned to another caller.
        """
        row = self._one("""
            SELECT invocation_id::text, idempotency_key, principal_id, request_hash, decision,
                   action_outcome, response, created_at
            FROM invocation WHERE idempotency_key = %s AND principal_id = %s
        """, (idempotency_key, principal_id))
        if row is None:
            return None
        row['created_at'] = iso_utc(row['created_at'])
        return row

    def claim_invocation(self, idempotency_key: str, invocation_id: str, request_hash: str,
                         principal_id: str | None = None) -> dict | None:
        row = self._one("""
            INSERT INTO invocation_claim (idempotency_key, principal_id, invocation_id, request_hash)
            VALUES (%s, %s, %s::uuid, %s)
            ON CONFLICT (COALESCE(principal_id, ''), idempotency_key) DO NOTHING
            RETURNING idempotency_key
        """, (idempotency_key, principal_id, invocation_id, request_hash))
        if row is not None:
            return None
        claim = self._one("""
            SELECT idempotency_key, principal_id, invocation_id::text, request_hash, state,
                   EXTRACT(EPOCH FROM (now() - created_at))::int AS age_seconds
            FROM invocation_claim
            WHERE idempotency_key = %s AND COALESCE(principal_id, '') = COALESCE(%s, '')
        """, (idempotency_key, principal_id))
        return claim

    def mark_claim_unknown(self, idempotency_key: str, invocation_id: str,
                           principal_id: str | None = None) -> None:
        self._execute("""
            UPDATE invocation_claim SET state = 'unknown', updated_at = now()
            WHERE idempotency_key = %s AND invocation_id = %s::uuid AND state = 'in_flight'
        """, (idempotency_key, invocation_id))

    def legacy_unowned_claims(self) -> list:
        """Claims with no trustworthy owner. Reported, never replayed automatically."""
        return self._rows("""
            SELECT idempotency_key, invocation_id::text, state, created_at
            FROM invocation_claim WHERE principal_id IS NULL ORDER BY created_at
        """)

    def read_ledger(self, scope_id: str, period_key: str) -> dict | None:
        return self._one("""
            SELECT scope_id, period_key, limit_tokens, limit_cost_micro, limit_ms, used_tokens,
                   used_cost_micro, used_ms, reserved_tokens, reserved_cost_micro, reserved_ms,
                   unknown_usage_count, overdraft_tokens
            FROM budget_ledger WHERE scope_id = %s AND period_key = %s
        """, (scope_id, period_key))

    def save_invocation(self, record: dict) -> None:
        self._execute("""
            INSERT INTO invocation (invocation_id, idempotency_key, principal_id, principal_role,
                                    service_id, action_id, request_hash, release_hash, decision,
                                    action_outcome, disclosure, reasons, findings, semantic_status,
                                    semantic_risk, detector_profile, latency_ms, dry_run, response)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (record['invocation_id'], record['idempotency_key'], record['principal_id'],
              record['principal_role'], record['service_id'], record['action_id'],
              record['request_hash'], record['release_hash'], record['decision'],
              record['action_outcome'], record['disclosure'], self._json(record['reasons']),
              self._json(record['findings']), record['semantic_status'], record['semantic_risk'],
              record['detector_profile'], record['latency_ms'], record['dry_run'],
              self._json(record['response'])))

    def save_outcome(self, record: dict, rows: list) -> None:
        """Invocation row, audit events and the completed claim in one transaction."""
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO invocation (invocation_id, idempotency_key, principal_id, principal_role,
                                            service_id, action_id, request_hash, release_hash, decision,
                                            action_outcome, disclosure, reasons, findings, semantic_status,
                                            semantic_risk, detector_profile, latency_ms, dry_run, response,
                                            budget_scope)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (record['invocation_id'], record['idempotency_key'], record['principal_id'],
                      record['principal_role'], record['service_id'], record['action_id'],
                      record['request_hash'], record['release_hash'], record['decision'],
                      record['action_outcome'], record['disclosure'], self._json(record['reasons']),
                      self._json(record['findings']), record['semantic_status'], record['semantic_risk'],
                      record['detector_profile'], record['latency_ms'], record['dry_run'],
                      self._json(record['response']), record.get('budget_scope', '')))
                if rows:
                    cursor.executemany("""
                        INSERT INTO audit_event (invocation_id, seq, kind, decision, reasons, findings, detail)
                        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                    """, [(row['invocation_id'], row['seq'], row['kind'], row['decision'],
                           self._json(row['reasons']), self._json(row['findings']),
                           self._json(sanitize_detail(row.get('detail')))) for row in rows])
                cursor.execute("""
                    UPDATE invocation_claim SET state = 'completed', updated_at = now()
                    WHERE idempotency_key = %s
                """, (record['idempotency_key'],))

    def save_model_checkpoint(self, record: dict, rows: list) -> None:
        """Upsert model checkpoints and append new audit events in one transaction."""
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO invocation (invocation_id, idempotency_key, principal_id, principal_role,
                                            service_id, action_id, request_hash, release_hash, decision,
                                            action_outcome, disclosure, reasons, findings, semantic_status,
                                            semantic_risk, detector_profile, latency_ms, dry_run, response,
                                            budget_scope)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (invocation_id) DO UPDATE SET
                      decision=EXCLUDED.decision, action_outcome=EXCLUDED.action_outcome,
                      disclosure=EXCLUDED.disclosure, reasons=EXCLUDED.reasons,
                      findings=EXCLUDED.findings, semantic_status=EXCLUDED.semantic_status,
                      semantic_risk=EXCLUDED.semantic_risk, latency_ms=EXCLUDED.latency_ms,
                      response=EXCLUDED.response, budget_scope=EXCLUDED.budget_scope
                """, (record['invocation_id'], record['idempotency_key'], record['principal_id'],
                      record['principal_role'], record['service_id'], record['action_id'],
                      record['request_hash'], record['release_hash'], record['decision'],
                      record['action_outcome'], record['disclosure'], self._json(record['reasons']),
                      self._json(record['findings']), record['semantic_status'], record['semantic_risk'],
                      record['detector_profile'], record['latency_ms'], record['dry_run'],
                      self._json(record['response']), record.get('budget_scope', '')))
                if rows:
                    cursor.executemany("""
                        INSERT INTO audit_event (invocation_id, seq, kind, decision, reasons, findings, detail)
                        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s) ON CONFLICT (invocation_id, seq) DO NOTHING
                    """, [(row['invocation_id'], row['seq'], row['kind'], row['decision'],
                           self._json(row['reasons']), self._json(row['findings']),
                           self._json(sanitize_detail(row.get('detail')))) for row in rows])

    def get_invocation(self, invocation_id: str) -> dict | None:
        row = self._one("""
            SELECT invocation_id::text, idempotency_key, principal_id, principal_role, service_id,
                   action_id, request_hash, release_hash, decision, action_outcome, disclosure,
                   reasons, findings, semantic_status, semantic_risk, detector_profile, latency_ms,
                   dry_run, response, budget_scope, created_at
            FROM invocation WHERE invocation_id = %s::uuid
        """, (invocation_id,))
        if row is None:
            return None
        row['created_at'] = iso_utc(row['created_at'])
        return row

    # -- audit --------------------------------------------------------------------
    def append_events(self, rows: list) -> None:
        if not rows:
            return
        # Sanitized here as well as in AuditTrail: a direct repository write must not be able to
        # bypass the audit sanitizer.
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO audit_event (invocation_id, seq, kind, decision, reasons, findings, detail)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (invocation_id, seq) DO NOTHING
                """, [(row['invocation_id'], row['seq'], row['kind'], row['decision'],
                       self._json(row['reasons']), self._json(row['findings']),
                       self._json(sanitize_detail(row.get('detail'))))
                      for row in rows])

    def list_events(self, invocation_id: str) -> list:
        rows = self._rows("""
            SELECT seq, kind, decision, reasons, findings, detail, created_at
            FROM audit_event WHERE invocation_id = %s::uuid ORDER BY seq
        """, (invocation_id,))
        for row in rows:
            row['created_at'] = iso_utc(row['created_at'])
        return rows

    def list_events_window(self, since: str, until: str, limit: int) -> list:
        rows = self._rows("""
            SELECT invocation_id::text, seq, kind, decision, reasons, findings, detail, created_at
            FROM audit_event
            WHERE created_at >= %s::timestamptz AND created_at <= %s::timestamptz
            ORDER BY created_at DESC, seq DESC
            LIMIT %s
        """, (_ts(since), _ts(until), limit))
        for row in rows:
            row['created_at'] = iso_utc(row['created_at'])
        return list(reversed(rows))

    # -- budget --------------------------------------------------------------------
    def list_events_page(self, since: str, until: str, limit: int, cursor: str | None = None,
                         filters: dict | None = None) -> dict:
        filters = filters or {}
        position = decode_cursor(cursor)
        clauses = ['created_at >= %s::timestamptz', 'created_at <= %s::timestamptz']
        params = [_ts(since), _ts(until)]
        if filters.get('kind'):
            clauses.append('kind = %s')
            params.append(filters['kind'])
        if filters.get('principal_id'):
            clauses.append('invocation_id IN (SELECT invocation_id FROM invocation '
                           'WHERE principal_id = %s)')
            params.append(filters['principal_id'])
        if position:
            clauses.append('(created_at, event_id) > (%s::timestamptz, %s)')
            params.extend([_ts(position['t']), position['i']])
        sql = """
            SELECT invocation_id::text, event_id, seq, kind, decision, reasons, findings, detail,
                   created_at
            FROM audit_event WHERE {} ORDER BY created_at, event_id LIMIT %s
        """.format(' AND '.join(clauses))
        params.append(limit + 1)
        rows = self._rows(sql, tuple(params))
        truncated = len(rows) > limit
        page = rows[:limit]
        token = None
        if truncated and page:
            last = page[-1]
            token = encode_cursor({'t': iso_utc(last['created_at']), 'i': last['event_id'],
                                   'f': _fingerprint([since, until, filters])})
        for row in page:
            row['created_at'] = iso_utc(row['created_at'])
        return {'events': page, 'nextCursor': token, 'truncated': truncated}

    def list_invocations(self, since: str, until: str, limit: int, cursor: str | None = None,
                         filters: dict | None = None) -> dict:
        filters = filters or {}
        position = decode_cursor(cursor)
        clauses = ['created_at >= %s::timestamptz', 'created_at <= %s::timestamptz']
        params = [_ts(since), _ts(until)]
        for name, column in (('decision', 'decision'), ('outcome', 'action_outcome'),
                             ('service', 'service_id'), ('action', 'action_id')):
            if filters.get(name):
                clauses.append(f'{column} = %s')
                params.append(filters[name])
        if filters.get('principal_id'):
            clauses.append('principal_id = %s')
            params.append(filters['principal_id'])
        if filters.get('dryRun') is not None:
            clauses.append('dry_run = %s')
            params.append(bool(filters['dryRun']))
        if position:
            clauses.append('(created_at, invocation_id) < (%s::timestamptz, %s::uuid)')
            params.extend([_ts(position['t']), position['i']])
        sql = """
            SELECT invocation_id::text, principal_id, principal_role, service_id, action_id,
                   decision, action_outcome, disclosure, reasons, findings, semantic_status,
                   dry_run, latency_ms, budget_scope, release_hash, created_at
            FROM invocation WHERE {} ORDER BY created_at DESC, invocation_id DESC LIMIT %s
        """.format(' AND '.join(clauses))
        params.append(limit + 1)
        rows = self._rows(sql, tuple(params))
        truncated = len(rows) > limit
        page = rows[:limit]
        token = None
        if truncated and page:
            last = page[-1]
            token = encode_cursor({'t': iso_utc(last['created_at']),
                                   'i': last['invocation_id'],
                                   'f': _fingerprint([since, until, filters])})
        for row in page:
            row['created_at'] = iso_utc(row['created_at'])
        return {'invocations': [_invocation_public(row) for row in page], 'nextCursor': token,
                'truncated': truncated}

    def list_summaries(self, since: str, until: str) -> dict:
        rows = self._rows("""
            SELECT invocation_id::text, principal_id, principal_role, service_id, action_id,
                   request_hash, decision, action_outcome, disclosure, reasons, findings,
                   semantic_status, dry_run, latency_ms, budget_scope, release_hash, created_at
            FROM invocation WHERE created_at >= %s::timestamptz AND created_at <= %s::timestamptz
        """, (_ts(since), _ts(until)))
        for row in rows:
            row['created_at'] = iso_utc(row['created_at'])
        return {'invocations': rows}

    def ensure_ledger(self, scope_id: str, period_key: str, limits: dict,
                      generation: int | None = None) -> dict:
        """Create the ledger row for a period once. Caps are never overwritten here."""
        return self._one("""
            INSERT INTO budget_ledger (scope_id, period_key, limit_tokens, limit_cost_micro,
                                       limit_ms, generation)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (scope_id, period_key) DO NOTHING
            RETURNING scope_id, period_key, limit_tokens, limit_cost_micro, limit_ms, used_tokens,
                      used_cost_micro, used_ms, reserved_tokens, reserved_cost_micro, reserved_ms,
                      unknown_usage_count, overdraft_tokens, generation
        """, (scope_id, period_key, limits['tokens'], limits['costMicro'], limits['wallClockMs'],
              generation))

    def set_ledger_caps(self, scope_id: str, period_key: str, limits: dict,
                        generation: int | None = None) -> dict:
        """Install caps for a period. Called by activation, inside its transaction."""
        return self._one("""
            INSERT INTO budget_ledger (scope_id, period_key, limit_tokens, limit_cost_micro,
                                       limit_ms, generation)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (scope_id, period_key) DO UPDATE
               SET limit_tokens = EXCLUDED.limit_tokens,
                   limit_cost_micro = EXCLUDED.limit_cost_micro,
                   limit_ms = EXCLUDED.limit_ms,
                   generation = EXCLUDED.generation,
                   updated_at = now()
            RETURNING scope_id, period_key, limit_tokens, limit_cost_micro, limit_ms, used_tokens,
                      used_cost_micro, used_ms, reserved_tokens, reserved_cost_micro, reserved_ms,
                      unknown_usage_count, overdraft_tokens, generation
        """, (scope_id, period_key, limits['tokens'], limits['costMicro'], limits['wallClockMs'],
              generation))

    def record_reservation_context(self, reservation_id: str, context: dict) -> None:
        """Provenance of one charge: which release and generation admitted it, at what price."""
        self._execute("""
            UPDATE budget_reservation
               SET release_hash = COALESCE(%s, release_hash),
                   activation_generation = COALESCE(%s, activation_generation),
                   pricing_identity = COALESCE(%s, pricing_identity),
                   principal_id = COALESCE(%s, principal_id),
                   invocation_id = COALESCE(%s::uuid, invocation_id)
             WHERE reservation_id = %s::uuid
        """, (context.get('release_hash'), context.get('activation_generation'),
              context.get('pricing_identity'), context.get('principal_id'),
              context.get('invocation_id'), reservation_id))

    def reserve_budget(self, plan, limits: dict) -> dict | None:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                # Caps are installed by activation only, so a reservation may create the period
                # row but must never rewrite an existing limit.
                cursor.execute("""
                    INSERT INTO budget_ledger (scope_id, period_key, limit_tokens, limit_cost_micro, limit_ms)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (scope_id, period_key) DO NOTHING
                """, (plan.scope_id, plan.period_key, limits['tokens'], limits['costMicro'],
                      limits['wallClockMs']))
                cursor.execute("""
                    UPDATE budget_ledger
                       SET reserved_tokens = reserved_tokens + %s,
                           reserved_cost_micro = reserved_cost_micro + %s,
                           reserved_ms = reserved_ms + %s,
                           updated_at = now()
                     WHERE scope_id = %s AND period_key = %s
                       AND used_tokens + overdraft_tokens + reserved_tokens + %s <= limit_tokens
                       AND used_cost_micro + reserved_cost_micro + %s <= limit_cost_micro
                       AND used_ms + reserved_ms + %s <= limit_ms
                    RETURNING scope_id, period_key, limit_tokens, limit_cost_micro, limit_ms,
                              used_tokens, used_cost_micro, used_ms, reserved_tokens,
                              reserved_cost_micro, reserved_ms, unknown_usage_count, overdraft_tokens
                """, (plan.tokens, plan.cost_micro, plan.ms, plan.scope_id, plan.period_key,
                      plan.tokens, plan.cost_micro, plan.ms))
                row = cursor.fetchone()
                if row is None:
                    return None
                columns = [column.name for column in cursor.description]
                state = dict(zip(columns, row))
                cursor.execute("""
                    INSERT INTO budget_reservation (reservation_id, scope_id, period_key, tokens,
                                                    cost_micro, ms)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s)
                    ON CONFLICT (reservation_id) DO NOTHING
                """, (plan.reservation_id, plan.scope_id, plan.period_key, plan.tokens,
                      plan.cost_micro, plan.ms))
                return state

    def commit_budget(self, reservation_id: str, tokens: int, cost_micro: int, ms: int,
                      usage_known: bool) -> dict:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT scope_id, period_key, tokens, cost_micro, ms, state
                    FROM budget_reservation WHERE reservation_id = %s::uuid FOR UPDATE
                """, (reservation_id,))
                row = cursor.fetchone()
                if row is None:
                    raise RepositoryError('unknown_reservation')
                scope_id, period_key, reserved_tokens, reserved_cost, reserved_ms, state = row
                if state == 'reserved':
                    cursor.execute("""
                        UPDATE budget_reservation SET state = 'committed', updated_at = now()
                        WHERE reservation_id = %s::uuid
                    """, (reservation_id,))
                    # A charge above its reservation is recorded as overdraft instead of pushing
                    # the remaining limit below zero, so the daily ceiling stays meaningful.
                    cursor.execute("""
                        UPDATE budget_ledger
                           SET reserved_tokens = reserved_tokens - %s,
                               reserved_cost_micro = reserved_cost_micro - %s,
                               reserved_ms = reserved_ms - %s,
                               used_tokens = used_tokens + LEAST(%s, %s),
                               overdraft_tokens = overdraft_tokens + GREATEST(%s - %s, 0),
                               used_cost_micro = used_cost_micro + LEAST(%s, %s),
                               used_ms = used_ms + %s,
                               unknown_usage_count = unknown_usage_count + %s,
                               updated_at = now()
                         WHERE scope_id = %s AND period_key = %s
                        RETURNING scope_id, period_key, limit_tokens, limit_cost_micro, limit_ms,
                                  used_tokens, used_cost_micro, used_ms, reserved_tokens,
                                  reserved_cost_micro, reserved_ms, unknown_usage_count,
                                  overdraft_tokens
                    """, (reserved_tokens, reserved_cost, reserved_ms, tokens, reserved_tokens,
                           tokens, reserved_tokens, cost_micro, reserved_cost, ms,
                           0 if usage_known else 1, scope_id, period_key))
                    result = cursor.fetchone()
                    columns = [column.name for column in cursor.description]
                    return dict(zip(columns, result))
                cursor.execute("""
                    SELECT scope_id, period_key, limit_tokens, limit_cost_micro, limit_ms, used_tokens,
                           used_cost_micro, used_ms, reserved_tokens, reserved_cost_micro, reserved_ms,
                           unknown_usage_count, overdraft_tokens
                    FROM budget_ledger WHERE scope_id = %s AND period_key = %s
                """, (scope_id, period_key))
                result = cursor.fetchone()
                columns = [column.name for column in cursor.description]
                return dict(zip(columns, result))

    def release_budget(self, reservation_id: str) -> dict:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT scope_id, period_key, tokens, cost_micro, ms, state
                    FROM budget_reservation WHERE reservation_id = %s::uuid FOR UPDATE
                """, (reservation_id,))
                row = cursor.fetchone()
                if row is None:
                    raise RepositoryError('unknown_reservation')
                scope_id, period_key, reserved_tokens, reserved_cost, reserved_ms, state = row
                if state == 'reserved':
                    cursor.execute("""
                        UPDATE budget_reservation SET state = 'released', updated_at = now()
                        WHERE reservation_id = %s::uuid
                    """, (reservation_id,))
                    cursor.execute("""
                        UPDATE budget_ledger
                           SET reserved_tokens = reserved_tokens - %s,
                               reserved_cost_micro = reserved_cost_micro - %s,
                               reserved_ms = reserved_ms - %s,
                               updated_at = now()
                         WHERE scope_id = %s AND period_key = %s
                    """, (reserved_tokens, reserved_cost, reserved_ms, scope_id, period_key))
        return self.read_ledger(scope_id, period_key)

    def budget_state(self, scope_id: str, period_key: str, limits: dict | None = None) -> dict:
        """Read the ledger. Never writes caps: reading a report must not change a limit."""
        row = self._one("""
            SELECT scope_id, period_key, limit_tokens, limit_cost_micro, limit_ms, used_tokens,
                   used_cost_micro, used_ms, reserved_tokens, reserved_cost_micro, reserved_ms,
                   unknown_usage_count, overdraft_tokens, generation
            FROM budget_ledger WHERE scope_id = %s AND period_key = %s
        """, (scope_id, period_key))
        return row

    # -- semantic observations ------------------------------------------------------
    def get_observation(self, key: dict) -> dict | None:
        return self._one("""
            SELECT observation_id, profile_id, model_id, direction, projection_hash, risk, category,
                   detector, mode, status, instruction_version, usage, latency_ms
            FROM semantic_observation
            WHERE profile_id = %s AND model_id = %s AND direction = %s AND projection_hash = %s
              AND instruction_version = %s
        """, (key['profile_id'], key['model_id'], key['direction'], key['projection_hash'],
              key['instruction_version']))

    def save_observation(self, key: dict, record: dict) -> int:
        row = self._one("""
            INSERT INTO semantic_observation (profile_id, model_id, direction, projection_hash, risk,
                                              category, detector, mode, status, instruction_version,
                                              usage, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (profile_id, model_id, direction, projection_hash, instruction_version)
            DO UPDATE SET risk = EXCLUDED.risk, category = EXCLUDED.category,
                          usage = EXCLUDED.usage, latency_ms = EXCLUDED.latency_ms
            RETURNING observation_id
        """, (key['profile_id'], key['model_id'], key['direction'], key['projection_hash'],
              record['risk'], record.get('category'), record['detector'], record['mode'],
              record['status'], key['instruction_version'], self._json(record.get('usage') or {}),
              record['latency_ms']))
        return row['observation_id']

    # -- synthetic service state ------------------------------------------------------
    def record_effect(self, effect: dict) -> None:
        self._execute("""
            INSERT INTO action_effect (invocation_id, service_id, action_id, outcome, result_bytes, detail)
            VALUES (%s::uuid, %s, %s, %s, %s, %s)
        """, (effect['invocation_id'], effect['service_id'], effect['action_id'], effect['outcome'],
              effect['result_bytes'], self._json(effect.get('detail') or {})))

    def dispatch_counts(self, since: str) -> dict:
        rows = self._rows("""
            SELECT action_id, count(*) AS count FROM action_effect
            WHERE created_at >= %s::timestamptz GROUP BY action_id
        """, (_ts(since),))
        return {row['action_id']: row['count'] for row in rows}

    def read_document(self, document_id: str) -> dict | None:
        return self._one("""
            SELECT document_id, title, body, classification FROM document
            WHERE document_id = %s AND deleted_at IS NULL
        """, (document_id,))

    def add_comment(self, document_id: str, body: str, author: str, invocation_id: str) -> dict | None:
        row = self._one("""
            INSERT INTO document_comment (document_id, body, author, invocation_id)
            SELECT %s, %s, %s, %s::uuid
            WHERE EXISTS (SELECT 1 FROM document WHERE document_id = %s AND deleted_at IS NULL)
            RETURNING comment_id, document_id, created_at
        """, (document_id, body, author, invocation_id, document_id))
        if row is not None:
            row['created_at'] = iso_utc(row['created_at'])
        return row

    def delete_document(self, document_id: str, invocation_id: str) -> bool:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE document SET deleted_at = now()
                    WHERE document_id = %s AND deleted_at IS NULL
                """, (document_id,))
                changed = cursor.rowcount
                if changed:
                    cursor.execute("""
                        INSERT INTO document_deletion (document_id, invocation_id)
                        VALUES (%s, %s::uuid)
                    """, (document_id, invocation_id))
                return bool(changed)

    # -- reporting ---------------------------------------------------------------------
    def summary(self, since: str, until: str, principal_id: str | None = None) -> dict:
        window = (_ts(since), _ts(until), principal_id, principal_id)
        counts = self._one("""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE decision = 'allow') AS allowed,
                   count(*) FILTER (WHERE decision = 'redact') AS redacted,
                   count(*) FILTER (WHERE decision = 'block') AS blocked,
                   count(*) FILTER (WHERE dry_run) AS dry_run,
                   count(*) FILTER (WHERE action_outcome = 'succeeded') AS succeeded,
                   count(*) FILTER (WHERE action_outcome = 'not_started') AS not_started,
                   count(*) FILTER (WHERE action_outcome = 'unknown') AS unknown,
                   count(*) FILTER (WHERE action_outcome = 'failed') AS failed,
                   count(*) FILTER (WHERE semantic_status = 'available') AS sem_available,
                   count(*) FILTER (WHERE semantic_status = 'unavailable') AS sem_unavailable,
                   count(*) FILTER (WHERE semantic_status = 'disabled') AS sem_disabled,
                   count(*) FILTER (WHERE semantic_status = 'not_run') AS sem_not_run
            FROM invocation WHERE created_at >= %s::timestamptz AND created_at < %s::timestamptz
              AND (%s::text IS NULL OR principal_id = %s)
        """, window)
        reasons = self._rows("""
            SELECT value, count(*) AS count FROM invocation,
                   jsonb_array_elements_text(reasons) AS value
            WHERE created_at >= %s::timestamptz AND created_at < %s::timestamptz
              AND (%s::text IS NULL OR principal_id = %s)
            GROUP BY value ORDER BY count DESC, value LIMIT 10
        """, window)
        findings = self._rows("""
            SELECT value, count(*) AS count FROM invocation,
                   jsonb_array_elements_text(findings) AS value
            WHERE created_at >= %s::timestamptz AND created_at < %s::timestamptz
              AND (%s::text IS NULL OR principal_id = %s)
            GROUP BY value ORDER BY count DESC, value LIMIT 10
        """, window)
        events = self._one("""
            SELECT count(*) AS events, max(e.created_at) AS last_event_at FROM audit_event e
            WHERE e.created_at >= %s::timestamptz AND e.created_at < %s::timestamptz
              AND (%s::text IS NULL OR EXISTS (
                  SELECT 1 FROM invocation i
                  WHERE i.invocation_id = e.invocation_id AND i.principal_id = %s))
        """, window)
        dispatch = self._rows("""
            SELECT e.action_id, count(*) AS count FROM action_effect e
            WHERE e.created_at >= %s::timestamptz AND e.created_at < %s::timestamptz
              AND (%s::text IS NULL OR EXISTS (
                  SELECT 1 FROM invocation i
                  WHERE i.invocation_id = e.invocation_id AND i.principal_id = %s))
            GROUP BY e.action_id
        """, window)
        disclosures = self._one("""
            SELECT count(*) FILTER (WHERE disclosure = 'full') AS full,
                   count(*) FILTER (WHERE disclosure = 'redacted') AS redacted,
                   count(*) FILTER (WHERE disclosure = 'withheld') AS withheld,
                   count(*) FILTER (WHERE disclosure = 'none') AS none
            FROM invocation WHERE created_at >= %s::timestamptz AND created_at < %s::timestamptz
              AND (%s::text IS NULL OR principal_id = %s)
        """, window)
        replays = self._one("""
            SELECT count(*) AS replayed FROM invocation
            WHERE created_at >= %s::timestamptz AND created_at < %s::timestamptz
              AND (%s::text IS NULL OR principal_id = %s)
              AND response->>'replayed' = 'true'
        """, window)
        dispatch_by_decision = self._rows("""
            SELECT i.decision, count(*) AS count FROM action_effect e
            JOIN invocation i ON i.invocation_id = e.invocation_id
            WHERE e.created_at >= %s::timestamptz AND e.created_at < %s::timestamptz
              AND (%s::text IS NULL OR i.principal_id = %s)
            GROUP BY i.decision
        """, window)
        return {
            'window': {'since': since, 'until': until},
            'invocations': {'total': counts['total'], 'allowed': counts['allowed'],
                            'redacted': counts['redacted'], 'blocked': counts['blocked'],
                            'dryRun': counts['dry_run'], 'replayed': replays['replayed']},
            'disclosure': {'full': disclosures['full'], 'redacted': disclosures['redacted'],
                           'withheld': disclosures['withheld'], 'none': disclosures['none']},
            'outcomes': {'succeeded': counts['succeeded'], 'notStarted': counts['not_started'],
                         'unknown': counts['unknown'], 'failed': counts['failed']},
            'semantic': {'available': counts['sem_available'],
                         'unavailable': counts['sem_unavailable'],
                         'disabled': counts['sem_disabled'],
                         'notRun': counts['sem_not_run']},
            'topReasons': [{'value': row['value'], 'count': row['count']} for row in reasons],
            'topFindings': [{'value': row['value'], 'count': row['count']} for row in findings],
            'dispatch': {row['action_id']: row['count'] for row in dispatch},
            'dispatchByDecision': {row['decision']: row['count'] for row in dispatch_by_decision},
            'latency': {'total': self.latency_percentiles(since, until, principal_id=principal_id)},
            'methodNotes': {
                'latency': 'nearest-rank percentile over the invocations in this window',
                'blockedShare': ('input decisions only; this is not a claim about attack detection '
                                 'and needs a labelled dataset to become one'),
                'window': 'identical bounds for every counter, dispatch and latency figure',
            },
            'events': events['events'],
            'lastEventAt': (iso_utc(events['last_event_at'])
                            if events['last_event_at'] else None),
        }

    def latency_percentiles(self, since: str, until: str,
                            principal_id: str | None = None) -> dict:
        rows = self._rows("""
            SELECT latency_ms FROM invocation
            WHERE created_at >= %s::timestamptz AND created_at < %s::timestamptz
              AND (%s::text IS NULL OR principal_id = %s)
        """, (_ts(since), _ts(until), principal_id, principal_id))
        return latency_stats([row['latency_ms'] or 0 for row in rows])
