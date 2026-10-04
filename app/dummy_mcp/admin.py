"""Local operator CLI for one dummy service.

This is the technical evidence and recovery channel, not a business path:

* ``inspect`` reads the local state, call counts and receipts over a read-only connection;
* ``fence`` records a terminal no-effect decision for one operation id (plan section 7.3);
* ``fault`` installs a fault rule for a run, a tool and the next call, with an optional TTL;
* ``reset`` starts a new demonstration run without deleting the previous run's evidence.

It is reachable only through ``docker compose exec`` inside the service container; it is not an
MCP tool and it is not routed through Traefik.
"""
import argparse
import json
import os
import sys

from .common.faults import MODES
from .registry import SERVICES, build_service, database_path


def _parser():
    parser = argparse.ArgumentParser(prog='dummy_mcp.admin', description=__doc__)
    parser.add_argument('--service', default=os.environ.get('DEMO_SERVICE'),
                        choices=sorted(SERVICES), help='service to administer')
    parser.add_argument('--db', default=None, help='explicit SQLite path (defaults to the volume)')
    subparsers = parser.add_subparsers(dest='command', required=True)

    inspect = subparsers.add_parser('inspect', help='read-only state, counters and receipts')
    inspect.add_argument('--run', default=None)

    fence = subparsers.add_parser('fence', help='record a terminal no-effect decision')
    fence.add_argument('--operation-id', required=True)
    fence.add_argument('--run', default=None)
    fence.add_argument('--actor', default='operator')
    fence.add_argument('--note', default=None)

    fault = subparsers.add_parser('fault', help='install one fault rule')
    fault.add_argument('--mode', required=True, choices=MODES)
    fault.add_argument('--tool', default=None)
    fault.add_argument('--delay-ms', type=int, default=0)
    fault.add_argument('--remaining', type=int, default=1)
    fault.add_argument('--ttl', type=int, default=None, help='seconds until the rule expires')
    fault.add_argument('--run', default=None)
    fault.add_argument('--note', default=None)

    subparsers.add_parser('clear-faults', help='remove every fault rule')
    subparsers.add_parser('run', help='show the active demonstration run')
    subparsers.add_parser('tools', help='print the published tool schemas')

    reset = subparsers.add_parser('reset', help='start a new demonstration run and re-seed')
    reset.add_argument('--run', required=True)
    reset.add_argument('--note', default=None)
    return parser


def main(argv=None):
    arguments = _parser().parse_args(argv)
    if not arguments.service:
        raise SystemExit('--service or DEMO_SERVICE is required')
    service = build_service(arguments.service, db_path=arguments.db)
    service.bootstrap()

    if arguments.command == 'inspect':
        payload = service.snapshot(run_id=arguments.run)
    elif arguments.command == 'run':
        payload = {'service': service.name, 'runId': service.current_run(),
                   'database': database_path(service.name, arguments.db)}
    elif arguments.command == 'tools':
        payload = {'service': service.name,
                   'tools': [{'name': spec.name, 'mutation': spec.mutation,
                              'description': spec.description,
                              'inputSchema': spec.input_schema,
                              'outputSchema': spec.output_schema}
                             for spec in service.tool_specs]}
    elif arguments.command == 'fence':
        run_id = arguments.run or service.current_run()
        payload = service.store.fence_operation(operation_id=arguments.operation_id,
                                                demo_run_id=run_id, actor=arguments.actor,
                                                note=arguments.note)
    elif arguments.command == 'fault':
        payload = service.store.add_fault(mode=arguments.mode, tool=arguments.tool,
                                          delay_ms=arguments.delay_ms,
                                          demo_run_id=arguments.run,
                                          remaining=arguments.remaining,
                                          ttl_seconds=arguments.ttl, note=arguments.note)
    elif arguments.command == 'clear-faults':
        payload = {'removed': service.store.clear_faults()}
    elif arguments.command == 'reset':
        payload = service.store.reset_run(arguments.run, service.seed, note=arguments.note)
    else:  # pragma: no cover - argparse rejects unknown commands first
        raise SystemExit(f'unknown command {arguments.command}')
    json.dump(payload, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
