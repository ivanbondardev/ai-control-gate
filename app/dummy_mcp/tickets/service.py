"""Tickets service: a small state machine with a real business invariant.

The service independently rejects transitions outside ``open -> in_progress -> resolved``, even
when the Gate admits the call. That is what makes "policy refusal" and "business refusal" two
visibly different outcomes in the same report.
"""
import re

from ..common.contracts import ServiceError
from ..common.service import Change, DummyService, ToolSpec, envelope_schema

SERVICE = 'tickets'
TICKET_ID = {'type': 'string', 'pattern': r'^T-[0-9]{4,10}$'}
TITLE = {'type': 'string', 'minLength': 1, 'maxLength': 200}
DESCRIPTION = {'type': 'string', 'minLength': 1, 'maxLength': 64000}
STATUS = {'type': 'string', 'enum': ['open', 'in_progress', 'resolved']}
VERSION = {'type': 'integer', 'minimum': 1, 'maximum': 1000000}

TRANSITIONS = {'open': ('in_progress',), 'in_progress': ('resolved',), 'resolved': ()}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    demo_run_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (demo_run_id, ticket_id)
);
CREATE TABLE IF NOT EXISTS ticket_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demo_run_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    at TEXT NOT NULL
);
"""

FIXTURES = (
    ('T-1001', 'Access recovery for a locked account',
     'The customer cannot complete two-factor authentication after a device replacement.', 'open',
     'seed'),
    ('T-9000', 'Protected: compliance review',
     'Protected ticket. Transitions are restricted by policy.', 'open', 'seed'),
)


class TicketsService(DummyService):
    name = SERVICE
    version = '0.1.0'
    extra_schema = SCHEMA

    def build_tools(self):
        return (
            ToolSpec(
                name='create_ticket',
                description='Create a synthetic support ticket in the open state.',
                input_schema={'type': 'object',
                              'properties': {'title': TITLE, 'description': DESCRIPTION},
                              'required': ['title', 'description'],
                              'additionalProperties': False},
                output_schema=envelope_schema(
                    {'ticket_id': TICKET_ID, 'ticket_status': STATUS, 'version': VERSION},
                    required=('ticket_id', 'ticket_status', 'version')),
                handler=self._create_ticket,
                mutation=True,
                annotations={'readOnlyHint': False, 'destructiveHint': False,
                             'idempotentHint': True},
            ),
            ToolSpec(
                name='read_ticket',
                description='Read one synthetic ticket, including its status and version.',
                input_schema={'type': 'object', 'properties': {'ticket_id': TICKET_ID},
                              'required': ['ticket_id'], 'additionalProperties': False},
                output_schema=envelope_schema(
                    {'ticket_id': TICKET_ID, 'title': {'type': 'string'},
                     'description': {'type': 'string'}, 'ticket_status': STATUS,
                     'version': VERSION, 'created_by': {'type': 'string'}},
                    required=('ticket_id', 'title', 'description', 'ticket_status', 'version')),
                handler=self._read_ticket,
                annotations={'readOnlyHint': True},
            ),
            ToolSpec(
                name='transition_ticket',
                description='Move a ticket to the next supported status. Only '
                            'open -> in_progress -> resolved is accepted.',
                input_schema={'type': 'object',
                              'properties': {'ticket_id': TICKET_ID, 'target_status': STATUS,
                                             'expected_version': VERSION},
                              'required': ['ticket_id', 'target_status', 'expected_version'],
                              'additionalProperties': False},
                output_schema=envelope_schema(
                    {'ticket_id': TICKET_ID, 'ticket_status': STATUS, 'version': VERSION,
                     'previous_status': STATUS},
                    required=('ticket_id', 'ticket_status', 'version', 'previous_status')),
                handler=self._transition_ticket,
                mutation=True,
                annotations={'readOnlyHint': False, 'destructiveHint': False,
                             'idempotentHint': True},
            ),
        )

    def seed(self, connection, run_id):
        for ticket_id, title, description, status, creator in FIXTURES:
            now = self.store.clock()
            connection.execute(
                'INSERT INTO tickets (demo_run_id, ticket_id, title, description, status, version, '
                'created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)',
                (run_id, ticket_id, title, description, status, creator, now, now))

    def inspect(self, connection, run_id):
        rows = connection.execute(
            'SELECT ticket_id, title, status, version, created_by, updated_at FROM tickets '
            'WHERE demo_run_id = ? ORDER BY ticket_id', (run_id,)).fetchall()
        transitions = connection.execute(
            'SELECT ticket_id, from_status, to_status, operation_id, at FROM ticket_transitions '
            'WHERE demo_run_id = ? ORDER BY id', (run_id,)).fetchall()
        return {'tickets': rows, 'transitions': transitions}

    # -- tools -----------------------------------------------------------------------
    def _create_ticket(self, tx, context, args):
        row = tx.execute('SELECT MAX(CAST(substr(ticket_id, 3) AS INTEGER)) AS highest '
                         'FROM tickets WHERE demo_run_id = ?', (context.demo_run_id,)).fetchone()
        next_number = max(2000, (row['highest'] or 0) + 1)
        ticket_id = f'T-{next_number}'
        now = self.store.clock()
        tx.execute('INSERT INTO tickets (demo_run_id, ticket_id, title, description, status, '
                   'version, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)',
                   (context.demo_run_id, ticket_id, args['title'], args['description'], 'open',
                    context.actor, now, now))
        return Change(result={'ticket_id': ticket_id, 'ticket_status': 'open', 'version': 1},
                      resource_id=ticket_id, before_version=None, after_version=1)

    def _read_ticket(self, tx, context, args):
        row = tx.execute('SELECT * FROM tickets WHERE demo_run_id = ? AND ticket_id = ?',
                         (context.demo_run_id, args['ticket_id'])).fetchone()
        if row is None:
            raise ServiceError('ticket_not_found', 'No such ticket in this run')
        return Change(result={'ticket_id': row['ticket_id'], 'title': row['title'],
                              'description': row['description'],
                              'ticket_status': row['status'],
                              'version': row['version'], 'created_by': row['created_by']},
                      resource_id=row['ticket_id'], before_version=row['version'],
                      after_version=row['version'])

    def _transition_ticket(self, tx, context, args):
        row = tx.execute('SELECT * FROM tickets WHERE demo_run_id = ? AND ticket_id = ?',
                         (context.demo_run_id, args['ticket_id'])).fetchone()
        if row is None:
            raise ServiceError('ticket_not_found', 'No such ticket in this run')
        expected = args['expected_version']
        if expected != row['version']:
            raise ServiceError(
                'version_conflict',
                f'expected_version {expected} does not match the stored version {row["version"]}',
                details={'currentVersion': row['version']})
        target = args['target_status']
        if target not in TRANSITIONS.get(row['status'], ()):
            # The invariant is the service's own; the Gate cannot widen it.
            raise ServiceError(
                'business_transition_invalid',
                f'{row["status"]} -> {target} is not a supported transition',
                details={'from': row['status'], 'supported': list(TRANSITIONS.get(row['status'], ()))})
        version = row['version'] + 1
        now = self.store.clock()
        tx.execute('UPDATE tickets SET status = ?, version = ?, updated_at = ? '
                   'WHERE demo_run_id = ? AND ticket_id = ?',
                   (target, version, now, context.demo_run_id, row['ticket_id']))
        tx.execute('INSERT INTO ticket_transitions (demo_run_id, ticket_id, from_status, to_status, '
                   'operation_id, at) VALUES (?, ?, ?, ?, ?, ?)',
                   (context.demo_run_id, row['ticket_id'], row['status'], target,
                    context.operation_id, now))
        return Change(result={'ticket_id': row['ticket_id'], 'ticket_status': target,
                              'version': version, 'previous_status': row['status']},
                      resource_id=row['ticket_id'], before_version=row['version'],
                      after_version=version)
