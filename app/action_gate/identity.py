"""One transport identity resolver for both ingress surfaces.

The API and the MCP ingress authenticate against the same principal registry, so an identity that
can call a tool is also an identity the panel knows about, and there is exactly one place where a
token is compared. A role, an actor name or a tenant is never read from a request body.
"""
from dataclasses import dataclass
import hmac

PRINCIPAL_HEADER = 'X-Action-Gate-Principal'
TOKEN_HEADER = 'X-Action-Gate-Token'

MCP_CLIENT_ROLES = ('agent', 'operator')


@dataclass(frozen=True)
class Principal:
    id: str
    role: str
    token: str
    description: str = ''


def _lookup(headers, name):
    """Case-insensitive header lookup.

    HTTP header names are case-insensitive and the two ingress surfaces hand over different objects:
    the API passes an ``email.message.Message``, the MCP ASGI wrapper passes a plain dict built from
    lower-case ASGI keys. Normalizing here keeps one resolver for both.
    """
    try:
        items = headers.items()
    except AttributeError:
        return ''
    lowered = name.lower()
    for key, value in items:
        if str(key).lower() == lowered and value is not None:
            return value
    return ''


def resolve(snapshot, headers):
    """Return ``(principal, failure_code)``. Failure codes carry no distinguishing detail."""
    if snapshot is None:
        return None, 'configuration_invalid'
    principals = getattr(snapshot, 'principals', None)
    if not principals:
        return None, 'configuration_invalid'
    principal_id = (_lookup(headers, PRINCIPAL_HEADER) or '').strip()
    token = (_lookup(headers, TOKEN_HEADER) or '').strip()
    if not principal_id or not token:
        return None, 'missing_identity'
    principal = principals.get(principal_id)
    if principal is None or not hmac.compare_digest(principal.token, token):
        return None, 'unknown_identity'
    return principal, None


def resolve_mcp(snapshot, headers):
    """Same registry, with the MCP-surface role restriction applied after authentication."""
    principal, failure = resolve(snapshot, headers)
    if principal is None:
        return None, failure
    if getattr(principal, 'role', None) not in MCP_CLIENT_ROLES:
        return None, 'insufficient_role'
    return principal, None
