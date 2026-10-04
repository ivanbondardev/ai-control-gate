"""Configuration records: the durable state behind the policy lifecycle.

Two backends implement the same operations, so a unit test on the memory backend means the same
thing as a Postgres test:

* PostgreSQL is the deployment backend. The active pointer, the immutable releases, the drafts and
  the activation log live in tables added by migration ``0003``.
* Memory is for tests and for running the gate without Docker. It is not durable and both
  ``/version`` and ``/v1/config/active`` say so.

The service above this layer never touches SQL; it works with plain dictionaries so the same
compare-and-swap logic runs in both environments.
"""
from contextlib import contextmanager
import threading
import uuid

from .base import iso_utc, utc_now_iso


class ConfigStoreError(RuntimeError):
    pass


class MemoryConfigStore:
    name = 'memory'

    def __init__(self):
        self._lock = threading.RLock()
        self._releases = {}
        self._drafts = {}
        self._active = None
        self._activations = []
        self._evaluations = {}

    # -- releases ------------------------------------------------------------------
    def put_release(self, record: dict) -> None:
        with self._lock:
            self._releases.setdefault(record['release_hash'],
                                      dict(record, created_at=utc_now_iso()))

    def get_release(self, release_hash: str) -> dict | None:
        with self._lock:
            record = self._releases.get(release_hash)
            return dict(record) if record else None

    def list_releases(self, limit: int, before: str | None = None) -> list:
        with self._lock:
            records = [dict(record) for record in self._releases.values()]
        records.sort(key=lambda record: (record['created_at'], record['release_hash']), reverse=True)
        if before:
            records = [record for record in records if record['created_at'] < before]
        return records[:limit]

    def get_active(self, environment: str) -> dict | None:
        with self._lock:
            return dict(self._active) if self._active else None

    def set_active(self, environment: str, release_hash: str, generation: int) -> None:
        with self._lock:
            self._active = {'environment': environment, 'release_hash': release_hash,
                            'generation': generation, 'updated_at': utc_now_iso()}

    # -- drafts --------------------------------------------------------------------
    def create_draft(self, record: dict) -> None:
        with self._lock:
            self._drafts[record['draft_id']] = dict(record)

    def get_draft(self, draft_id: str) -> dict | None:
        with self._lock:
            record = self._drafts.get(draft_id)
            return dict(record) if record else None

    def update_draft(self, draft_id: str, revision: int, documents: dict, expected_revision: int):
        with self._lock:
            record = self._drafts.get(draft_id)
            if record is None:
                return None
            if record['revision'] != expected_revision:
                return 'stale'
            record['revision'] = revision
            record['documents'] = documents
            record['updated_at'] = utc_now_iso()
            return dict(record)

    def list_drafts(self, limit: int = 20) -> list:
        with self._lock:
            records = [dict(record) for record in self._drafts.values()]
        records.sort(key=lambda record: record['updated_at'], reverse=True)
        return records[:limit]

    # -- activations ---------------------------------------------------------------
    def append_activation(self, record: dict):
        with self._lock:
            for existing in self._activations:
                if record.get('operation_key') and \
                        existing.get('operation_key') == record['operation_key']:
                    return 'duplicate', dict(existing)
            stored = dict(record, created_at=utc_now_iso())
            self._activations.append(stored)
            return 'recorded', dict(stored)

    def find_activation(self, environment: str, operation_key: str) -> dict | None:
        with self._lock:
            for record in self._activations:
                if record.get('operation_key') == operation_key:
                    return dict(record)
        return None

    def list_activations(self, environment: str, limit: int = 50) -> list:
        with self._lock:
            records = [dict(record) for record in self._activations]
        records.sort(key=lambda record: record['created_at'], reverse=True)
        return records[:limit]

    # -- evaluations ---------------------------------------------------------------
    def put_evaluation(self, record: dict) -> None:
        with self._lock:
            self._evaluations[record['evaluation_id']] = dict(record, created_at=utc_now_iso())

    def get_evaluation(self, evaluation_id: str) -> dict | None:
        with self._lock:
            record = self._evaluations.get(evaluation_id)
            return dict(record) if record else None

    def latest_evaluation(self, environment: str, candidate_hash: str) -> dict | None:
        with self._lock:
            records = [dict(record) for record in self._evaluations.values()
                       if record['candidate_hash'] == candidate_hash]
        if not records:
            return None
        records.sort(key=lambda record: record['created_at'], reverse=True)
        return records[0]

    # -- ledger caps ---------------------------------------------------------------
    def install_caps(self, repository, budgets: dict, generation: int) -> None:
        """Apply the caps of a new generation to ledgers that already exist."""
        from ..budget import utc_day_key
        for scope in budgets['scopes']:
            repository.set_ledger_caps(scope['id'], utc_day_key(), scope['limits'], generation)


class PostgresConfigStore:
    """The same operations against PostgreSQL, inside one connection per transaction."""

    name = 'postgres'

    def __init__(self, repository):
        self.repository = repository

    @contextmanager
    def _connection(self):
        with self.repository.raw_connection() as connection:
            yield connection

    @staticmethod
    def _json(value):
        from psycopg.types.json import Jsonb
        return Jsonb(value)

    def put_release(self, record: dict) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO config_release (release_hash, bundle_id, components, snapshot,
                                                schema_version, source, created_by,
                                                activation_generation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (release_hash) DO NOTHING
                """, (record['release_hash'], record['bundle_id'], self._json(record['components']),
                      self._json(record['snapshot']), record['schema_version'], record['source'],
                      record.get('created_by'), record.get('activation_generation')))

    def get_release(self, release_hash: str) -> dict | None:
        return self.repository._one("""
            SELECT release_hash, bundle_id, components, snapshot, schema_version, source, created_by,
                   activation_generation, created_at
            FROM config_release WHERE release_hash = %s
        """, (release_hash,))

    def list_releases(self, limit: int, before: str | None = None) -> list:
        if before:
            return self.repository._rows("""
                SELECT release_hash, bundle_id, components, snapshot, schema_version, source,
                       created_by, activation_generation, created_at
                FROM config_release WHERE created_at < %s::timestamptz
                ORDER BY created_at DESC, release_hash DESC LIMIT %s
            """, (before, limit))
        return self.repository._rows("""
            SELECT release_hash, bundle_id, components, snapshot, schema_version, source, created_by,
                   activation_generation, created_at
            FROM config_release ORDER BY created_at DESC, release_hash DESC LIMIT %s
        """, (limit,))

    def get_active(self, environment: str) -> dict | None:
        return self.repository._one("""
            SELECT environment, release_hash, generation, updated_at
            FROM config_active WHERE environment = %s
        """, (environment,))

    def set_active(self, environment: str, release_hash: str, generation: int) -> None:
        self.repository._execute("""
            INSERT INTO config_active (environment, release_hash, generation)
            VALUES (%s, %s, %s)
            ON CONFLICT (environment) DO UPDATE
               SET release_hash = EXCLUDED.release_hash,
                   generation = EXCLUDED.generation,
                   updated_at = now()
        """, (environment, release_hash, generation))

    def create_draft(self, record: dict) -> None:
        self.repository._execute("""
            INSERT INTO config_draft (draft_id, base_release, revision, documents, source, created_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s)
        """, (record['draft_id'], record['base_release'], record['revision'],
              self._json(record['documents']), record['source'], record.get('created_by')))

    def get_draft(self, draft_id: str) -> dict | None:
        return self.repository._one("""
            SELECT draft_id::text, base_release, revision, documents, source, created_by,
                   created_at, updated_at
            FROM config_draft WHERE draft_id = %s::uuid
        """, (draft_id,))

    def update_draft(self, draft_id: str, revision: int, documents: dict, expected_revision: int):
        row = self.repository._one("""
            UPDATE config_draft SET revision = %s, documents = %s, updated_at = now()
            WHERE draft_id = %s::uuid AND revision = %s
            RETURNING draft_id::text, base_release, revision, documents, source, created_by,
                      created_at, updated_at
        """, (revision, self._json(documents), draft_id, expected_revision))
        if row is not None:
            return row
        existing = self.get_draft(draft_id)
        return 'missing' if existing is None else 'stale'

    def list_drafts(self, limit: int = 20) -> list:
        return self.repository._rows("""
            SELECT draft_id::text, base_release, revision, source, created_by, created_at, updated_at
            FROM config_draft ORDER BY updated_at DESC LIMIT %s
        """, (limit,))

    def append_activation(self, record: dict):
        with self._connection() as connection:
            with connection.cursor() as cursor:
                if record.get('operation_key'):
                    cursor.execute("""
                        SELECT activation_id::text, environment, previous_hash, next_hash, generation,
                               actor, reason, kind, created_at
                        FROM config_activation
                        WHERE environment = %s AND operation_key = %s
                    """, (record['environment'], record['operation_key']))
                    existing = cursor.fetchone()
                    if existing is not None:
                        columns = [column.name for column in cursor.description]
                        return 'duplicate', dict(zip(columns, existing))
                cursor.execute("""
                    INSERT INTO config_activation (activation_id, environment, previous_hash,
                                                   next_hash, generation, actor, reason, kind,
                                                   operation_key, request_hash)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING activation_id::text, environment, previous_hash, next_hash, generation,
                              actor, reason, kind, created_at
                """, (record['activation_id'], record['environment'], record.get('previous_hash'),
                      record['next_hash'], record['generation'], record['actor'],
                      record.get('reason'), record.get('kind', 'activation'),
                      record.get('operation_key'), record.get('request_hash')))
                row = cursor.fetchone()
                columns = [column.name for column in cursor.description]
                return 'recorded', dict(zip(columns, row))

    def find_activation(self, environment: str, operation_key: str) -> dict | None:
        return self.repository._one("""
            SELECT activation_id::text, environment, previous_hash, next_hash, generation, actor,
                   reason, kind, created_at
            FROM config_activation WHERE environment = %s AND operation_key = %s
        """, (environment, operation_key))

    def list_activations(self, environment: str, limit: int = 50) -> list:
        return self.repository._rows("""
            SELECT activation_id::text, environment, previous_hash, next_hash, generation, actor,
                   reason, kind, created_at
            FROM config_activation WHERE environment = %s ORDER BY created_at DESC LIMIT %s
        """, (environment, limit))

    def put_evaluation(self, record: dict) -> None:
        self.repository._execute("""
            INSERT INTO config_evaluation (evaluation_id, environment, active_hash,
                                           active_generation, candidate_hash, candidate_revision,
                                           dataset_hash, detector_profile, detector_identity,
                                           instruction_version, mode, status, passed, model_calls,
                                           case_count, summary, created_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (evaluation_id) DO NOTHING
        """, (record['evaluation_id'], record['environment'], record['active_hash'],
              record['active_generation'], record['candidate_hash'], record.get('candidate_revision'),
              record.get('dataset_hash'), record['detector_profile'],
              self._json(record.get('detector_identity') or {}), record.get('instruction_version'),
              record.get('mode', 'full'), record['status'], record.get('passed', False),
              record.get('model_calls', 0), record.get('case_count', 0),
              self._json(record.get('summary') or {}), record.get('created_by')))

    def get_evaluation(self, evaluation_id: str) -> dict | None:
        return self.repository._one("""
            SELECT evaluation_id::text, environment, active_hash, active_generation, candidate_hash,
                   candidate_revision, dataset_hash, detector_profile, detector_identity,
                   instruction_version, mode, status, passed, model_calls, case_count, summary,
                   created_by, created_at
            FROM config_evaluation WHERE evaluation_id = %s::uuid
        """, (evaluation_id,))

    def latest_evaluation(self, environment: str, candidate_hash: str) -> dict | None:
        return self.repository._one("""
            SELECT evaluation_id::text, environment, active_hash, active_generation, candidate_hash,
                   candidate_revision, dataset_hash, detector_profile, detector_identity,
                   instruction_version, mode, status, passed, model_calls, case_count, summary,
                   created_by, created_at
            FROM config_evaluation
            WHERE environment = %s AND candidate_hash = %s
            ORDER BY created_at DESC LIMIT 1
        """, (environment, candidate_hash))

    def install_caps(self, repository, budgets: dict, generation: int) -> None:
        from ..budget import utc_day_key
        for scope in budgets['scopes']:
            repository.set_ledger_caps(scope['id'], utc_day_key(), scope['limits'], generation)


def build_config_store(repository):
    if getattr(repository, 'name', '') == 'postgres':
        return PostgresConfigStore(repository)
    return MemoryConfigStore()


def new_id() -> str:
    return str(uuid.uuid4())
