"""Outbox service: a local mailbox with no delivery path.

A stored row is the whole effect. The service never says "sent" or "delivered": the status is
``stored_locally`` and no SMTP, network client or retry queue exists in this container.

Two boundaries live here rather than in the Gate, because they are data boundaries:

* the address parser rejects display names, address lists, CRLF injection and malformed addresses;
* a principal can read and list only the messages it created.
"""
import re

from ..common.contracts import ServiceError
from ..common.service import Change, DummyService, ToolSpec, envelope_schema

SERVICE = 'outbox'
MESSAGE_ID = {'type': 'string', 'pattern': r'^MSG-[A-Za-z0-9]{4,32}$'}
SUBJECT = {'type': 'string', 'minLength': 1, 'maxLength': 200}
BODY = {'type': 'string', 'minLength': 1, 'maxLength': 64000}

# A deliberately strict single-address grammar: one local part, one dotted domain, no display
# name, no angle brackets, no list separator, no whitespace of any kind.
ADDRESS = re.compile(
    r'[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9])?@'
    r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}\Z')
FORBIDDEN = ('\r', '\n', '\t', ' ', ',', ';', '<', '>', '"', "'", '(', ')', '[', ']', '\\')

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    demo_run_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    creator_principal TEXT NOT NULL,
    recipient TEXT NOT NULL,
    recipient_domain TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    PRIMARY KEY (demo_run_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_creator ON messages (demo_run_id, creator_principal);
"""

SEED = ()


def parse_address(value: str) -> tuple:
    """Return ``(normalized_address, domain)`` or raise a typed business refusal."""
    if not isinstance(value, str) or not value:
        raise ServiceError('invalid_recipient', 'A single recipient address is required')
    if len(value) > 254 or any(character in value for character in FORBIDDEN):
        raise ServiceError('invalid_recipient',
                           'The recipient must be one plain address without display names, '
                           'lists or control characters')
    if value.count('@') != 1 or not ADDRESS.fullmatch(value):
        raise ServiceError('invalid_recipient', 'The recipient is not a valid single email address')
    local, domain = value.rsplit('@', 1)
    domain = domain.lower()
    if '..' in domain or domain.startswith('.') or domain.endswith('.'):
        raise ServiceError('invalid_recipient', 'The recipient domain is malformed')
    return f'{local}@{domain}', domain


class OutboxService(DummyService):
    name = SERVICE
    version = '0.1.0'
    extra_schema = SCHEMA

    def build_tools(self):
        return (
            ToolSpec(
                name='send_message',
                description='Store one message in the local synthetic mailbox. Nothing is sent '
                            'anywhere; the stored status is stored_locally.',
                input_schema={'type': 'object',
                              'properties': {'to': {'type': 'string', 'minLength': 3,
                                                    'maxLength': 254},
                                             'subject': SUBJECT,
                                             'body': BODY},
                              'required': ['to', 'subject', 'body'],
                              'additionalProperties': False},
                output_schema=envelope_schema(
                    {'message_id': MESSAGE_ID, 'to': {'type': 'string'},
                     'message_status': {'type': 'string', 'enum': ['stored_locally']},
                     'created_at': {'type': 'string'}},
                    required=('message_id', 'to', 'message_status', 'created_at')),
                handler=self._send_message,
                mutation=True,
                annotations={'readOnlyHint': False, 'destructiveHint': False,
                             'idempotentHint': True},
            ),
            ToolSpec(
                name='get_message',
                description='Read one stored message created by the calling principal.',
                input_schema={'type': 'object', 'properties': {'message_id': MESSAGE_ID},
                              'required': ['message_id'], 'additionalProperties': False},
                output_schema=envelope_schema(
                    {'message_id': MESSAGE_ID, 'to': {'type': 'string'},
                     'subject': {'type': 'string'}, 'body': {'type': 'string'},
                     'message_status': {'type': 'string'}, 'created_at': {'type': 'string'}},
                    required=('message_id', 'to', 'subject', 'body', 'message_status',
                              'created_at')),
                handler=self._get_message,
                annotations={'readOnlyHint': True},
            ),
            ToolSpec(
                name='list_messages',
                description='List message metadata created by the calling principal. Bodies are '
                            'never included in a listing.',
                input_schema={'type': 'object',
                              'properties': {'limit': {'type': 'integer', 'minimum': 1,
                                                       'maximum': 20}},
                              'required': [], 'additionalProperties': False},
                output_schema=envelope_schema(
                    {'messages': {'type': 'array', 'items': {
                        'type': 'object',
                        'properties': {'message_id': MESSAGE_ID, 'to': {'type': 'string'},
                                       'subject': {'type': 'string'},
                                       'message_status': {'type': 'string'},
                                       'created_at': {'type': 'string'}},
                        'required': ['message_id', 'to', 'subject', 'message_status',
                                     'created_at'],
                        'additionalProperties': False}},
                     'count': {'type': 'integer', 'minimum': 0}},
                    required=('messages', 'count')),
                handler=self._list_messages,
                annotations={'readOnlyHint': True},
            ),
        )

    def seed(self, connection, run_id):
        # The mailbox starts empty on purpose: every stored row in a demonstration is traceable to
        # one Gate operation.
        return None

    def inspect(self, connection, run_id):
        rows = connection.execute(
            'SELECT message_id, creator_principal, recipient, recipient_domain, subject, status, '
            'created_at FROM messages WHERE demo_run_id = ? ORDER BY created_at', (run_id,)).fetchall()
        return {'messages': rows, 'bodies': connection.execute(
            'SELECT COUNT(*) AS stored FROM messages WHERE demo_run_id = ?', (run_id,)).fetchone()}

    # -- tools -----------------------------------------------------------------------
    def _send_message(self, tx, context, args):
        address, domain = parse_address(args['to'])
        token = re.sub(r'[^A-Za-z0-9]', '', context.operation_id)[:24].upper()
        message_id = 'MSG-' + token
        now = self.store.clock()
        tx.execute('INSERT INTO messages (demo_run_id, message_id, creator_principal, recipient, '
                   'recipient_domain, subject, body, status, created_at, operation_id) '
                   'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (context.demo_run_id, message_id, context.actor, address, domain, args['subject'],
                    args['body'], 'stored_locally', now, context.operation_id))
        return Change(result={'message_id': message_id, 'to': address,
                              'message_status': 'stored_locally', 'created_at': now},
                      resource_id=message_id)

    def _get_message(self, tx, context, args):
        row = tx.execute('SELECT * FROM messages WHERE demo_run_id = ? AND message_id = ?',
                         (context.demo_run_id, args['message_id'])).fetchone()
        if row is None:
            raise ServiceError('message_not_found', 'No such stored message')
        if row['creator_principal'] != context.actor:
            # Ownership is a data boundary of this service; the Gate never has to be trusted for it.
            raise ServiceError('not_message_owner', 'This message was created by another principal')
        return Change(result={'message_id': row['message_id'], 'to': row['recipient'],
                              'subject': row['subject'], 'body': row['body'],
                              'message_status': row['status'], 'created_at': row['created_at']},
                      resource_id=row['message_id'])

    def _list_messages(self, tx, context, args):
        limit = int(args.get('limit', 10))
        rows = tx.execute(
            'SELECT message_id, recipient, subject, status, created_at FROM messages '
            'WHERE demo_run_id = ? AND creator_principal = ? ORDER BY created_at DESC LIMIT ?',
            (context.demo_run_id, context.actor, limit)).fetchall()
        return Change(result={'messages': [{'message_id': row['message_id'],
                                            'to': row['recipient'],
                                            'subject': row['subject'],
                                            'message_status': row['status'],
                                            'created_at': row['created_at']} for row in rows],
                              'count': len(rows)})
