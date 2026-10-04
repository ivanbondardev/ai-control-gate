"""SQLite storage for one dummy service.

Design constraints taken from the implementation plan:

* WAL journal, ``synchronous=FULL``, foreign keys on, bounded ``busy_timeout`` shorter than the
  upstream deadline the Gate allows;
* a business change, its receipt and its journal entry commit in one ``BEGIN IMMEDIATE``
  transaction, so a crash cannot leave a mutation without evidence or evidence without a mutation;
* run-scoped rows are keyed by ``demo_run_id``. A reset starts a new run and re-seeds the demo
  data without deleting the previous run's receipts, which stay as evidence;
* a read-only connection is used by the operator inspector and by ``GET /operations/{id}``, so the
  evidence channel cannot mutate state.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 2000

COMMON_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS operation_receipts (
    demo_run_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    service TEXT NOT NULL,
    tool TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    resource_id TEXT,
    before_version INTEGER,
    after_version INTEGER,
    result_json TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    PRIMARY KEY (demo_run_id, operation_id)
);
CREATE INDEX IF NOT EXISTS idx_receipts_operation ON operation_receipts (operation_id);
CREATE TABLE IF NOT EXISTS operation_fences (
    demo_run_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL,
    note TEXT,
    PRIMARY KEY (demo_run_id, operation_id)
);
CREATE TABLE IF NOT EXISTS service_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    demo_run_id TEXT,
    kind TEXT NOT NULL,
    tool TEXT,
    operation_id TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS service_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    demo_run_id TEXT,
    tool TEXT NOT NULL,
    operation_id TEXT,
    outcome TEXT NOT NULL,
    committed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_calls_at ON service_calls (at);
CREATE TABLE IF NOT EXISTS fault_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    tool TEXT,
    mode TEXT NOT NULL,
    delay_ms INTEGER NOT NULL DEFAULT 0,
    demo_run_id TEXT,
    remaining INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    note TEXT
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _dict_row(cursor, row):
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


class StorageError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class Store:
    """Owns the SQLite file. One process is the single writer for it."""

    def __init__(self, service: str, path, *, clock=now_iso):
        self.service = service
        self.path = str(path)
        self.clock = clock
        self._lock = threading.RLock()
        self._bootstrapped = False

    # -- connections ---------------------------------------------------------------
    def _connect(self, *, readonly=False):
        if readonly:
            uri = f'file:{self.path}?mode=ro'
            connection = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000,
                                         isolation_level=None, check_same_thread=False)
        else:
            connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000,
                                         isolation_level=None, check_same_thread=False)
        connection.row_factory = _dict_row
        connection.execute(f'PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}')
        connection.execute('PRAGMA foreign_keys = ON')
        if not readonly:
            connection.execute('PRAGMA journal_mode = WAL')
            connection.execute('PRAGMA synchronous = FULL')
        return connection

    @contextmanager
    def write(self):
        """One immediate transaction: the write lock is taken before the first read."""
        with self._lock:
            connection = self._connect()
            try:
                connection.execute('BEGIN IMMEDIATE')
                try:
                    yield connection
                except BaseException:
                    connection.execute('ROLLBACK')
                    raise
                else:
                    connection.execute('COMMIT')
            finally:
                connection.close()

    @contextmanager
    def read(self, *, readonly=True):
        connection = self._connect(readonly=readonly)
        try:
            yield connection
        finally:
            connection.close()

    # -- schema and bootstrap ------------------------------------------------------
    def migrate(self, extra_schema: str = ''):
        """Apply the idempotent schema.

        ``executescript`` commits any open transaction first, so migrations run in autocommit mode
        instead of inside the write transaction used for business changes. Every statement is
        ``IF NOT EXISTS``, so a partially applied migration converges on the next start.
        """
        directory = Path(self.path).parent
        directory.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.executescript(COMMON_SCHEMA)
            if extra_schema:
                connection.executescript(extra_schema)
            row = connection.execute('SELECT MAX(version) AS version FROM schema_migrations').fetchone()
            if not row or row['version'] is None:
                connection.execute('INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)',
                                   (SCHEMA_VERSION, self.clock()))
        finally:
            connection.close()
        self._bootstrapped = True

    def active_run(self, connection) -> str | None:
        row = connection.execute("SELECT value FROM service_state WHERE key = 'active_run_id'").fetchone()
        return row['value'] if row else None

    def secret(self, connection, name: str) -> bytes:
        """Per-instance local key, generated on first use and never exported."""
        row = connection.execute('SELECT value FROM service_state WHERE key = ?', (name,)).fetchone()
        if row:
            return bytes.fromhex(row['value'])
        value = secrets.token_bytes(32)
        connection.execute('INSERT INTO service_state (key, value) VALUES (?, ?)',
                           (name, value.hex()))
        return value

    def start_run(self, connection, run_id: str, *, note: str | None = None):
        connection.execute('INSERT INTO demo_runs (run_id, created_at, status, note) VALUES (?, ?, ?, ?)',
                           (run_id, self.clock(), 'active', note))
        connection.execute("INSERT INTO service_state (key, value) VALUES ('active_run_id', ?) "
                           'ON CONFLICT (key) DO UPDATE SET value = excluded.value', (run_id,))
        connection.execute("UPDATE demo_runs SET status = 'closed' WHERE run_id <> ?", (run_id,))

    def ensure_run(self, seed=None, run_id: str | None = None) -> str:
        """Seed once. An existing volume is never reseeded by a restart."""
        with self.write() as connection:
            active = self.active_run(connection)
            if active:
                return active
            start = run_id or 'run-0001'
            self.start_run(connection, start, note='initial bootstrap')
            if seed is not None:
                seed(connection, start)
            connection.execute('INSERT INTO service_events (at, demo_run_id, kind, detail) '
                               'VALUES (?, ?, ?, ?)',
                               (self.clock(), start, 'run_initialised',
                                json.dumps({'seed': seed is not None})))
            return start

    def reset_run(self, run_id: str, seed=None, *, note: str | None = None) -> dict:
        """Start a new run. Previous receipts and events are preserved as evidence."""
        with self.write() as connection:
            previous = self.active_run(connection)
            if previous == run_id:
                raise StorageError('run_exists', f'run {run_id} is already active')
            existing = connection.execute('SELECT run_id FROM demo_runs WHERE run_id = ?',
                                          (run_id,)).fetchone()
            if existing:
                self.start_run(connection, run_id, note=note)
            else:
                self.start_run(connection, run_id, note=note)
                if seed is not None:
                    seed(connection, run_id)
            connection.execute('INSERT INTO service_events (at, demo_run_id, kind, detail) '
                               'VALUES (?, ?, ?, ?)',
                               (self.clock(), run_id, 'run_reset',
                                json.dumps({'previous': previous, 'note': note})))
            return {'previousRunId': previous, 'runId': run_id, 'seeded': not existing}

    # -- receipts ------------------------------------------------------------------
    def receipt(self, connection, demo_run_id: str, operation_id: str):
        return connection.execute(
            'SELECT * FROM operation_receipts WHERE demo_run_id = ? AND operation_id = ?',
            (demo_run_id, operation_id)).fetchone()

    def fence(self, connection, demo_run_id: str, operation_id: str):
        return connection.execute(
            'SELECT * FROM operation_fences WHERE demo_run_id = ? AND operation_id = ?',
            (demo_run_id, operation_id)).fetchone()

    def record_receipt(self, connection, *, demo_run_id, operation_id, tool, fingerprint,
                       receipt_id, outcome, result, resource_id=None, before_version=None,
                       after_version=None):
        connection.execute(
            'INSERT INTO operation_receipts (demo_run_id, operation_id, service, tool, '
            'request_fingerprint, receipt_id, outcome, resource_id, before_version, after_version, '
            'result_json, committed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (demo_run_id, operation_id, self.service, tool, fingerprint, receipt_id, outcome,
             resource_id, before_version, after_version, json.dumps(result, sort_keys=True), self.clock()))

    def record_event(self, connection, *, demo_run_id, kind, tool=None, operation_id=None, detail=None):
        connection.execute(
            'INSERT INTO service_events (at, demo_run_id, kind, tool, operation_id, detail) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (self.clock(), demo_run_id, kind, tool, operation_id,
             json.dumps(detail, sort_keys=True) if detail is not None else None))

    def record_call(self, connection, *, demo_run_id, tool, operation_id, outcome, committed=False):
        connection.execute(
            'INSERT INTO service_calls (at, demo_run_id, tool, operation_id, outcome, committed) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (self.clock(), demo_run_id, tool, operation_id, outcome, 1 if committed else 0))

    # -- inspection ------------------------------------------------------------------
    def snapshot(self, *, run_id: str | None = None, inspect=None) -> dict:
        with self.read() as connection:
            active = self.active_run(connection)
            run = run_id or active
            calls = connection.execute(
                'SELECT tool, outcome, COUNT(*) AS count FROM service_calls WHERE demo_run_id = ? '
                'GROUP BY tool, outcome ORDER BY tool, outcome', (run,)).fetchall()
            receipts = connection.execute(
                'SELECT operation_id, tool, receipt_id, outcome, resource_id, after_version, '
                'committed_at FROM operation_receipts WHERE demo_run_id = ? ORDER BY committed_at',
                (run,)).fetchall()
            fences = connection.execute(
                'SELECT operation_id, kind, actor, at FROM operation_fences WHERE demo_run_id = ? '
                'ORDER BY at', (run,)).fetchall()
            events = connection.execute(
                'SELECT at, kind, tool, operation_id, detail FROM service_events '
                'WHERE demo_run_id = ? ORDER BY id DESC LIMIT 50', (run,)).fetchall()
            faults = connection.execute('SELECT id, tool, mode, remaining, expires_at FROM fault_rules '
                                        'ORDER BY id').fetchall()
            state = (inspect or self.inspect)(connection, run)
            return {'service': self.service, 'activeRunId': active, 'runId': run,
                    'schemaVersion': SCHEMA_VERSION, 'calls': calls, 'receipts': receipts,
                    'fences': fences, 'events': events, 'faults': faults, 'state': state,
                    'database': {'path': self.path, 'bytes': self._size()}}

    def inspect(self, connection, run_id: str) -> dict:
        """Service-specific state. Overridden by each service."""
        return {}

    def _size(self) -> int:
        total = 0
        for suffix in ('', '-wal', '-shm'):
            try:
                total += os.path.getsize(self.path + suffix)
            except OSError:
                pass
        return total

    # -- faults ----------------------------------------------------------------------
    def add_fault(self, *, mode, tool=None, delay_ms=0, demo_run_id=None, remaining=1,
                  ttl_seconds=None, actor='operator', note=None):
        expires = None
        if ttl_seconds:
            expires = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + float(ttl_seconds), timezone.utc
            ).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        with self.write() as connection:
            cursor = connection.execute(
                'INSERT INTO fault_rules (service, tool, mode, delay_ms, demo_run_id, remaining, '
                'expires_at, created_at, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (self.service, tool, mode, int(delay_ms), demo_run_id, int(remaining), expires,
                 self.clock(), note))
            return {'id': cursor.lastrowid, 'mode': mode, 'tool': tool, 'remaining': remaining,
                    'delayMs': delay_ms, 'demoRunId': demo_run_id, 'expiresAt': expires}

    def clear_faults(self) -> int:
        with self.write() as connection:
            cursor = connection.execute('DELETE FROM fault_rules')
            return cursor.rowcount

    def take_fault(self, connection, tool: str, demo_run_id: str):
        """Consume one matching fault rule inside the caller's transaction."""
        now = self.clock()
        rows = connection.execute(
            'SELECT * FROM fault_rules WHERE service = ? AND (tool IS NULL OR tool = ?) '
            'AND (demo_run_id IS NULL OR demo_run_id = ?) AND remaining > 0 '
            'AND (expires_at IS NULL OR expires_at > ?) ORDER BY id',
            (self.service, tool, demo_run_id, now)).fetchall()
        if not rows:
            return None
        rule = rows[0]
        if rule['remaining'] <= 1:
            connection.execute('DELETE FROM fault_rules WHERE id = ?', (rule['id'],))
        else:
            connection.execute('UPDATE fault_rules SET remaining = remaining - 1 WHERE id = ?',
                               (rule['id'],))
        return rule

    def fence_operation(self, *, operation_id, demo_run_id, kind='cancelled_no_effect',
                        actor='operator', note=None) -> dict:
        """Operator fence: terminal no-effect record that blocks a late commit.

        The caller must hold the local write lock, so a handler that is already committing either
        finishes first (and the fence reports its receipt) or starts after the fence and refuses.
        """
        with self.write() as connection:
            receipt = self.receipt(connection, demo_run_id, operation_id)
            if receipt:
                return {'outcome': 'already_committed', 'receiptId': receipt['receipt_id'],
                        'operationId': operation_id, 'runId': demo_run_id}
            connection.execute(
                'INSERT INTO operation_fences (demo_run_id, operation_id, kind, actor, at, note) '
                'VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (demo_run_id, operation_id) DO NOTHING',
                (demo_run_id, operation_id, kind, actor, self.clock(), note))
            self.record_event(connection, demo_run_id=demo_run_id, kind='fenced',
                              operation_id=operation_id, detail={'kind': kind, 'actor': actor})
            return {'outcome': 'fenced', 'kind': kind, 'operationId': operation_id,
                    'runId': demo_run_id}

    def operation_status(self, operation_id: str) -> dict:
        """Read-only status for the Gate. Metadata only: never the business payload."""
        with self.read() as connection:
            receipt = connection.execute(
                'SELECT demo_run_id, tool, receipt_id, outcome, resource_id, before_version, '
                'after_version, committed_at FROM operation_receipts WHERE operation_id = ? '
                'ORDER BY committed_at DESC LIMIT 1', (operation_id,)).fetchone()
            fence = connection.execute(
                'SELECT demo_run_id, kind, at FROM operation_fences WHERE operation_id = ? '
                'ORDER BY at DESC LIMIT 1', (operation_id,)).fetchone()
            if receipt:
                return {'operationId': operation_id, 'status': 'committed',
                        'receipt': dict(receipt)}
            if fence:
                return {'operationId': operation_id, 'status': 'no_effect',
                        'fence': dict(fence)}
            return {'operationId': operation_id, 'status': 'not_found'}


def state_hash(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
