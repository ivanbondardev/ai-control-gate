"""Transport identity for the dummy services.

A dummy has exactly one client: the Gate. It resolves that client from two headers and compares the
token in constant time. There is no anonymous path, no cookie and no fallback identity.

Credentials live outside Git in a generated file. Each service has its own scope, so the token the
Gate presents to the outbox is not the token it presents to the documents service: one compromised
service cannot impersonate the Gate anywhere else.
"""
import hmac
import json
from pathlib import Path

PRINCIPAL_HEADER = 'x-action-gate-service'
TOKEN_HEADER = 'x-action-gate-token'

MIN_TOKEN_LENGTH = 16


def load_credentials(path, scope=None) -> dict:
    """Read the generated local credential file.

    Layout::

        {"version": 1, "scopes": {"documents": {"gate-mcp": "<token>"}, ...}}

    With ``scope`` the caller's map for that scope is returned; without it the whole scope map is
    returned, which is what the Gate needs to talk to every service.
    """
    document = json.loads(Path(path).read_text())
    if not isinstance(document, dict) or document.get('version') != 1:
        raise ValueError('credential file has an unsupported version')
    scopes = document.get('scopes')
    if not isinstance(scopes, dict) or not scopes:
        raise ValueError('credential file has no scopes')
    normalized = {}
    for name, entries in scopes.items():
        if not isinstance(entries, dict) or not entries:
            raise ValueError(f'credential scope {name!r} is empty')
        normalized[name] = {}
        for caller, token in entries.items():
            if not isinstance(caller, str) or not isinstance(token, str) \
                    or len(token) < MIN_TOKEN_LENGTH:
                raise ValueError(f'credential scope {name!r} has an invalid entry')
            normalized[name][caller] = token
    if scope is None:
        return normalized
    if scope not in normalized:
        raise ValueError(f'credential scope {scope!r} is not present')
    return normalized[scope]


def header_map(scope) -> dict:
    return {key.decode('latin-1').lower(): value.decode('latin-1')
            for key, value in scope.get('headers', [])}


class ServiceGate:
    """ASGI wrapper: authenticate before any MCP or inspection route runs."""

    def __init__(self, app, credentials, *, public_prefixes=('/health/',)):
        self.app = app
        self.credentials = credentials
        self.public_prefixes = tuple(public_prefixes)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        if path.startswith(self.public_prefixes):
            return await self.app(scope, receive, send)
        headers = header_map(scope)
        service_id = headers.get(PRINCIPAL_HEADER, '')
        token = headers.get(TOKEN_HEADER, '')
        expected = self.credentials.get(service_id)
        if not expected or not hmac.compare_digest(expected, token):
            body = b'{"error":"identity_required"}'
            await send({'type': 'http.response.start', 'status': 401,
                        'headers': [(b'content-type', b'application/json'),
                                    (b'content-length', str(len(body)).encode()),
                                    (b'www-authenticate', b'ActionGate-Service')]})
            await send({'type': 'http.response.body', 'body': body})
            return
        scope.setdefault('state', {})['service_id'] = service_id
        return await self.app(scope, receive, send)
