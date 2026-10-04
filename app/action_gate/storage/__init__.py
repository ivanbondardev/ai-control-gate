"""Storage factory.

``APP_STORAGE=postgres`` is the deployment default and fails closed when PostgreSQL is not
reachable. ``APP_STORAGE=memory`` exists for tests and for running the gate without Docker; it is
explicitly not durable and is reported as such by ``/version``.
"""
from .base import Repository, RepositoryError, utc_now_iso
from .memory import MemoryRepository
from .postgres import PostgresRepository
from .runtime import NullRuntime, RedisRuntime

__all__ = ['Repository', 'RepositoryError', 'MemoryRepository', 'PostgresRepository',
           'NullRuntime', 'RedisRuntime', 'build_repository', 'build_runtime',
           'utc_now_iso', 'database_dsn']


def database_dsn(environ) -> str | None:
    explicit = (environ.get('APP_DATABASE_DSN') or '').strip()
    if explicit:
        return explicit
    host = (environ.get('POSTGRES_HOST') or '').strip()
    if not host:
        return None
    return 'host={} port={} dbname={} user={} password={} connect_timeout=3'.format(
        host, environ.get('POSTGRES_PORT', '5432'), environ.get('POSTGRES_DB', ''),
        environ.get('POSTGRES_USER', ''), environ.get('POSTGRES_PASSWORD', ''))


def build_repository(environ) -> Repository:
    backend = (environ.get('APP_STORAGE') or 'postgres').strip().lower()
    if backend == 'memory':
        return MemoryRepository()
    if backend != 'postgres':
        raise RepositoryError('unsupported_storage_backend')
    dsn = database_dsn(environ)
    if not dsn:
        raise RepositoryError('storage_not_configured')
    return PostgresRepository(dsn, max_connections=int(environ.get('APP_DB_POOL_SIZE', '8') or 8))


def build_runtime(environ):
    if (environ.get('APP_RUNTIME_CACHE') or 'redis').strip().lower() in ('0', 'off', 'none', 'disabled'):
        return NullRuntime()
    try:
        return RedisRuntime.from_environment(environ)
    except Exception:
        return NullRuntime()
