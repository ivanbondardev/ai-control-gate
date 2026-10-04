"""Validation, canonical JSON and trusted call metadata for the dummy services.

Two rules drive this module:

* a business argument is validated against the published JSON Schema with no coercion, so
  ``"2"`` is never silently accepted where ``2`` is required;
* control fields (operation id, run id, actor) never travel as business arguments. They arrive in
  JSON-RPC ``params._meta`` under the ``actiongate.internal/`` namespace, which a client of the
  Gate can neither see nor set.
"""
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

CONTROL_PREFIX = 'actiongate.internal/'
OPERATION_ID = CONTROL_PREFIX + 'operation_id'
DEMO_RUN_ID = CONTROL_PREFIX + 'demo_run_id'
ACTOR = CONTROL_PREFIX + 'actor'

MAX_ARGUMENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 512 * 1024
RUN_ID = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\Z')
OPERATION_ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z')
RESOURCE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z')


class ServiceError(RuntimeError):
    """A typed business refusal. It is reported as ``isError`` with a stable code."""

    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ProtocolError(RuntimeError):
    """A malformed or unauthorised protocol-level call. Reported as a JSON-RPC error."""

    def __init__(self, code, message, *, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def json_bytes(value) -> int:
    return len(canonical(value).encode('utf-8'))


def fingerprint(key: bytes, value) -> str:
    """Keyed fingerprint of the exact request identity.

    The key is the service's own local secret, so a stored fingerprint proves nothing to an
    attacker who reads the database and cannot be replayed across services.
    """
    return hmac.new(key, canonical(value).encode('utf-8'), sha256).hexdigest()


@dataclass(frozen=True)
class CallContext:
    operation_id: str
    demo_run_id: str
    actor: str

    @property
    def mutation(self) -> bool:
        return True


def call_context(meta, *, patterns=(OPERATION_ID_PATTERN,)) -> CallContext:
    """Extract trusted control metadata. A missing field is a protocol error, not a default."""
    if not isinstance(meta, dict):
        raise ProtocolError(-32602, 'Missing call metadata')
    values = {}
    for name, key in (('operation_id', OPERATION_ID), ('demo_run_id', DEMO_RUN_ID),
                      ('actor', ACTOR)):
        raw = meta.get(key)
        if not isinstance(raw, str) or not raw:
            raise ProtocolError(-32602, f'Missing required call metadata: {key}')
        values[name] = raw
    if not patterns[0].fullmatch(values['operation_id']):
        raise ProtocolError(-32602, 'Invalid operation id')
    if not RUN_ID.fullmatch(values['demo_run_id']):
        raise ProtocolError(-32602, 'Invalid demo run id')
    if not OPERATION_ID_PATTERN.fullmatch(values['actor']) or len(values['actor']) > 100:
        raise ProtocolError(-32602, 'Invalid actor identity')
    return CallContext(**values)


def validator(schema: dict, where: str) -> Draft202012Validator:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001 - a broken schema is a startup error
        raise ProtocolError(-32603, f'{where}: invalid JSON Schema ({exc})') from exc
    return Draft202012Validator(schema)


def validate_arguments(schema: dict, arguments, where: str) -> dict:
    """Validate without coercion and return a plain copy of the accepted arguments."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ProtocolError(-32602, f'{where}: arguments must be an object')
    if json_bytes(arguments) > MAX_ARGUMENT_BYTES:
        raise ProtocolError(-32602, f'{where}: arguments exceed {MAX_ARGUMENT_BYTES} bytes')
    check = validator(schema, where)
    errors = sorted(check.iter_errors(arguments), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        path = '.'.join(str(part) for part in first.absolute_path) or '(root)'
        raise ProtocolError(-32602, f'{where}: {path}: {first.message}')
    return json.loads(canonical(arguments))


def validate_result(schema: dict, result: dict, where: str) -> dict:
    try:
        validator(schema, where).validate(result)
    except ValidationError as exc:  # pragma: no cover - a programming error, not user input
        raise ServiceError('internal_result_invalid',
                           f'{where}: the service produced a result outside its schema: {exc.message}')
    return result


def require_string(value, name, *, limit=200, pattern=None):
    if not isinstance(value, str) or not value.strip():
        raise ServiceError('invalid_argument', f'{name} must be a non-empty string')
    value = value.strip()
    if len(value) > limit:
        raise ServiceError('invalid_argument', f'{name} must be at most {limit} characters')
    if pattern is not None and not pattern.fullmatch(value):
        raise ServiceError('invalid_argument', f'{name} has an invalid format')
    return value


def require_resource_id(value, name='resource_id'):
    return require_string(value, name, limit=64, pattern=RESOURCE_ID)
