"""Sanitized audit records.

Audit is a durable PostgreSQL record of what the gate decided and why. It never stores raw
untrusted text: the writer keeps a denylist and a structural sanitizer, so a caller cannot leak
content by inventing a detail field. Hashes are keyed with a deployment salt so that a stored
digest of low-entropy input cannot be brute-forced offline.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import uuid

AUDIT_SCHEMA_VERSION = 1
MAX_STRING = 200
MAX_DEPTH = 3
MAX_DETAIL_BYTES = 4096
DENIED_KEYS = frozenset({
    'text', 'body', 'raw', 'prompt', 'content', 'message', 'messages', 'secret', 'token',
    'password', 'apikey', 'api_key', 'authorization', 'credential', 'credentials', 'key',
})
REDACTED = '[omitted]'

EVENT_KINDS = (
    'invocation_received',
    'identity_resolved',
    'release_pinned',
    'detector_resolved',
    'grant_evaluated',
    'input_controls',
    'budget_reserved',
    'budget_refused',
    'semantic_evaluation',
    'dispatch_started',
    'dispatch_finished',
    'output_controls',
    'budget_committed',
    'invocation_replayed',
    'invocation_completed',
    'invocation_blocked',
    'invocation_failed',
)


def new_invocation_id() -> str:
    return str(uuid.uuid4())


# Values shipped in .env.example. They are public, so they are not secrets: a digest keyed with
# one of them is brute-forceable by anyone who can read this repository.
PLACEHOLDER_SALTS = frozenset({'action-gate-local-development-salt',
                               'local-development-salt-change-me'})


def hash_salt(environ=None) -> tuple[str, bool]:
    """Return (salt, using_development_default).

    The shipped example value counts as *not configured*: the deployment is told, in ``/version``
    and in the startup log, that its digests are keyed with a public placeholder.
    """
    environ = os.environ if environ is None else environ
    configured = (environ.get('APP_HASH_SALT') or '').strip()
    if configured and configured not in PLACEHOLDER_SALTS:
        return configured, False
    return 'action-gate-local-development-salt', True


def keyed_hash(value: str, salt: str) -> str:
    return hmac.new(salt.encode('utf-8'), value.encode('utf-8', 'surrogatepass'), hashlib.sha256).hexdigest()


def projection_hash(text: str, salt: str) -> str:
    return keyed_hash(text, salt)[:32]


def _sanitize(value, depth=0):
    if depth > MAX_DEPTH:
        return '[depth]'
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float('inf') else None
    if isinstance(value, str):
        return value if len(value) <= MAX_STRING else value[:MAX_STRING] + '…'
    if isinstance(value, dict):
        clean = {}
        for key, item in list(value.items())[:40]:
            if not isinstance(key, str):
                continue
            clean[key] = REDACTED if key.casefold() in DENIED_KEYS else _sanitize(item, depth + 1)
        return clean
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth + 1) for item in list(value)[:40]]
    return str(type(value).__name__)


def sanitize_detail(detail) -> dict:
    clean = _sanitize(detail if isinstance(detail, dict) else {})
    encoded = json.dumps(clean, ensure_ascii=False, default=str)
    if len(encoded.encode('utf-8')) > MAX_DETAIL_BYTES:
        return {'truncated': True, 'bytes': len(encoded.encode('utf-8'))}
    return clean


@dataclass(frozen=True)
class AuditEvent:
    invocation_id: str
    seq: int
    kind: str
    decision: str | None
    reasons: tuple[str, ...]
    findings: tuple[str, ...]
    detail: dict

    def as_row(self) -> dict:
        return {
            'invocation_id': self.invocation_id,
            'seq': self.seq,
            'kind': self.kind,
            'decision': self.decision,
            'reasons': list(self.reasons),
            'findings': list(self.findings),
            'detail': sanitize_detail(self.detail),
        }

    def as_public_dict(self) -> dict:
        return {
            'invocationId': self.invocation_id,
            'seq': self.seq,
            'kind': self.kind,
            'decision': self.decision,
            'reasons': list(self.reasons),
            'findings': list(self.findings),
            'detail': sanitize_detail(self.detail),
        }


class AuditTrail:
    """Collects events for one invocation. Sequence numbers are assigned here, never by callers."""

    def __init__(self, invocation_id: str):
        self.invocation_id = invocation_id
        self._events = []

    def record(self, kind: str, decision: str | None = None, reasons=(), findings=(), **detail) -> AuditEvent:
        if kind not in EVENT_KINDS:
            raise ValueError(f'unknown audit kind {kind!r}')
        event = AuditEvent(self.invocation_id, len(self._events) + 1, kind, decision,
                           tuple(str(r) for r in reasons), tuple(str(f) for f in findings), detail)
        self._events.append(event)
        return event

    def rows(self) -> list[dict]:
        return [event.as_row() for event in self._events]

    def public(self) -> list[dict]:
        return [event.as_public_dict() for event in self._events]

    def __len__(self) -> int:
        return len(self._events)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')
