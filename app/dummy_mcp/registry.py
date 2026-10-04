"""Service table for the dummy MCP containers.

One image, three commands: ``python -m dummy_mcp documents|outbox|tickets``. Each container gets
its own volume and its own SQLite file, and none of them can reach another service's data.
"""
import os
import sys

from .common.auth import load_credentials
from .common.storage import Store
from .documents.service import DocumentsService
from .outbox.service import OutboxService
from .tickets.service import TicketsService

SERVICES = {
    'documents': DocumentsService,
    'outbox': OutboxService,
    'tickets': TicketsService,
}

DEFAULT_DB_DIR = '/data'
DEFAULT_CREDENTIALS_FILE = '/run/demo/credentials.json'


def database_path(name: str, override: str | None = None) -> str:
    if override:
        return override
    explicit = os.environ.get('DEMO_DB_PATH')
    if explicit:
        return explicit
    return os.path.join(os.environ.get('DEMO_DB_DIR', DEFAULT_DB_DIR), f'{name}.sqlite3')


def build_service(name: str, *, db_path: str | None = None, **kwargs):
    service_class = SERVICES.get(name)
    if service_class is None:
        raise SystemExit(f'unknown service {name!r}; expected one of {sorted(SERVICES)}')
    return service_class(Store(name, database_path(name, db_path)), **kwargs)


def service_from_environment(environ=None):
    environ = environ or os.environ
    name = environ.get('DEMO_SERVICE')
    if not name:
        if len(sys.argv) > 1 and sys.argv[1] in SERVICES:
            name = sys.argv[1]
        else:
            raise SystemExit('DEMO_SERVICE or a service argument is required')
    return name, build_service(name, db_path=environ.get('DEMO_DB_PATH'))


def credentials_from_environment(environ=None, service=None) -> dict:
    """The caller map for this service's own credential scope."""
    environ = environ or os.environ
    path = environ.get('DEMO_CREDENTIALS_FILE', DEFAULT_CREDENTIALS_FILE)
    scope = service or environ.get('DEMO_SERVICE')
    try:
        return load_credentials(path, scope=scope)
    except OSError as exc:
        raise SystemExit(f'service credentials are required at {path}: {exc}') from exc
    except ValueError as exc:
        raise SystemExit(f'service credentials at {path} are invalid for scope {scope!r}: {exc}')
