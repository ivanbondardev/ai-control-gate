"""Migration runner.

Migrations live in ``app/migrations`` as plain SQL, are applied in filename order and recorded in
``schema_migrations``. The container runs this before serving, so a fresh environment converges
without manual SQL. Applying an already-applied file is a no-op.
"""
import os
from pathlib import Path
import sys

from .storage.postgres import PostgresRepository

MIGRATIONS_DIR = Path(os.environ.get('APP_MIGRATIONS_DIR') or (Path(__file__).resolve().parents[1] / 'migrations'))
# One advisory lock for the whole migration run, so a second job waits instead of applying the same
# file concurrently.
MIGRATION_LOCK_KEY = 0x4D43504D  # 'MCPM'


def apply_migrations(conninfo: str, directory: Path | None = None, verbose: bool = True) -> list:
    directory = Path(directory or MIGRATIONS_DIR)
    files = sorted(path for path in directory.glob('*.sql'))
    if not files:
        raise RuntimeError(f'no migrations found in {directory}')
    repository = PostgresRepository(conninfo, max_connections=1)
    applied = []
    try:
        with repository.raw_connection() as connection:
            with connection.cursor() as cursor:
                # Session-level lock: held until this connection closes.
                cursor.execute('SELECT pg_advisory_lock(%s)', (MIGRATION_LOCK_KEY,))
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version text PRIMARY KEY,
                        applied_at timestamptz NOT NULL DEFAULT now()
                    )
                """)
                cursor.execute('SELECT version FROM schema_migrations')
                done = {row[0] for row in cursor.fetchall()}
            for path in files:
                version = path.name
                if version in done:
                    if verbose:
                        print(f'migration already applied: {version}', flush=True)
                    continue
                sql = path.read_text(encoding='utf-8')
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    cursor.execute('INSERT INTO schema_migrations (version) VALUES (%s)', (version,))
                applied.append(version)
                if verbose:
                    print(f'migration applied: {version}', flush=True)
    finally:
        repository.close()
    return applied


def main() -> int:
    conninfo = os.environ.get('APP_DATABASE_DSN') or _dsn_from_environment()
    if not conninfo:
        print('no PostgreSQL connection settings found', file=sys.stderr, flush=True)
        return 2
    try:
        apply_migrations(conninfo)
    except Exception as exc:
        print(f'migration failed: {type(exc).__name__}', file=sys.stderr, flush=True)
        return 1
    return 0


def _dsn_from_environment() -> str | None:
    host = os.environ.get('POSTGRES_HOST')
    if not host:
        return None
    return 'host={} port={} dbname={} user={} password={}'.format(
        host, os.environ.get('POSTGRES_PORT', '5432'), os.environ.get('POSTGRES_DB', ''),
        os.environ.get('POSTGRES_USER', ''), os.environ.get('POSTGRES_PASSWORD', ''))


if __name__ == '__main__':
    raise SystemExit(main())
