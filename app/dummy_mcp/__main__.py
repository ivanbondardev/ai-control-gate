"""Entry point: ``python -m dummy_mcp documents|outbox|tickets``.

One process, one replica, one SQLite file per service. The MCP endpoint is the only business
surface; ``/operations/{id}`` is the read-only status the Gate reconciles against and
``/health/*`` is the container probe.
"""
import argparse

from .common.service import DEFAULT_PORT
from .registry import SERVICES, build_service, credentials_from_environment


def main(argv=None):
    parser = argparse.ArgumentParser(prog='dummy_mcp')
    parser.add_argument('service', choices=sorted(SERVICES))
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--db', default=None)
    arguments = parser.parse_args(argv)
    service = build_service(arguments.service, db_path=arguments.db)
    service.serve(credentials_from_environment(service=arguments.service),
                  host=arguments.host, port=arguments.port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
