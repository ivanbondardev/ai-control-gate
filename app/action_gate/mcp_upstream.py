"""Gate-side MCP client for one dummy service.

Only the Gate holds these credentials. The client:

* sends the Gate's service identity on every request, never a client token;
* carries trusted call context in ``params._meta`` (operation id, run id, actor) so a business tool
  schema never has to contain a control field;
* bounds every hop with a connection timeout and an upstream deadline;
* distinguishes a *provable* no-effect failure (the connection was never established) from an
  unknown outcome (the request may have been executed), because that difference decides whether the
  Gate may report "not started" or must keep the operation visible as unknown.
"""
import asyncio
from contextlib import asynccontextmanager
import json

import anyio

from . import __version__

PRINCIPAL_HEADER = 'X-Action-Gate-Service'
TOKEN_HEADER = 'X-Action-Gate-Token'
GATE_SERVICE_ID = 'gate-mcp'
INTERNAL_PREFIX = 'actiongate.internal/'

CONNECT_TIMEOUT = 1.0
UPSTREAM_DEADLINE = 5.0
MAX_RESULT_BYTES = 512 * 1024
MAX_TOOLS = 100
MAX_TOOL_PAGES = 5


class UpstreamError(RuntimeError):
    """A failed upstream hop.

    ``dispatched`` is True whenever the request might have reached the service, which is exactly the
    case where the Gate must not claim that nothing happened.
    """

    def __init__(self, code, detail=None, *, dispatched=False):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.dispatched = dispatched


class UpstreamResult:
    def __init__(self, *, is_error, structured, text, bytes_out, protocol_version):
        self.is_error = is_error
        self.structured = structured
        self.text = text
        self.bytes_out = bytes_out
        self.protocol_version = protocol_version

    def as_dict(self):
        return {'isError': self.is_error, 'structured': self.structured, 'text': self.text,
                'bytes': self.bytes_out, 'protocolVersion': self.protocol_version}


def _headers(service_id, token):
    return {PRINCIPAL_HEADER: service_id, TOKEN_HEADER: token}


class McpUpstream:
    """One short-lived MCP session per call, in the stateless JSON profile."""

    def __init__(self, credentials, *, connect_timeout=CONNECT_TIMEOUT,
                 deadline=UPSTREAM_DEADLINE, max_result_bytes=MAX_RESULT_BYTES, client_factory=None):
        self.credentials = credentials
        self.connect_timeout = connect_timeout
        self.deadline = deadline
        self.max_result_bytes = max_result_bytes
        self._client_factory = client_factory

    def _token(self, service_id, credential_id=None):
        """Each service has its own scope, so a token is valid for exactly one service."""
        scope = self.credentials.get(service_id)
        token = (scope or {}).get(credential_id or GATE_SERVICE_ID) \
            or self.credentials.get(credential_id or GATE_SERVICE_ID)
        if not token:
            raise UpstreamError('service_credential_missing',
                                f'no local credential for {service_id}')
        return token

    def _http_client(self, service_id, credential_id=None):
        import httpx2
        from mcp.client.streamable_http import create_mcp_http_client
        if self._client_factory is not None:
            return self._client_factory(service_id)
        return create_mcp_http_client(
            headers=_headers(GATE_SERVICE_ID, self._token(service_id, credential_id)),
            timeout=httpx2.Timeout(connect=self.connect_timeout, read=self.deadline,
                                   write=self.deadline, pool=self.connect_timeout))

    @staticmethod
    @asynccontextmanager
    async def _session(endpoint, http_client):
        """One MCP session per call, in the stateless JSON profile.

        Timeouts are enforced by the HTTP client and by the SDK's own request timeout instead of an
        outer ``wait_for``: cancelling the SDK's internal task group from the outside trips an anyio
        cancel-scope error, and cancelling mid-call would also hide whether the request was sent.
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(endpoint, http_client=http_client) as streams:
            read, write = streams
            async with ClientSession(read, write) as session:
                yield session

    async def list_tools(self, endpoint, service_id, *, credential_id=None):
        """Read every page of ``tools/list``, bounded in pages and tool count."""
        import mcp.types as types

        http_client = self._http_client(service_id, credential_id)
        tools, cursor, pages = [], None, 0
        try:
            async with self._session(endpoint, http_client) as session:
                await session.initialize()
                while True:
                    pages += 1
                    if pages > MAX_TOOL_PAGES:
                        raise UpstreamError('discovery_page_limit',
                                            'the service returned too many tool pages')
                    listing = await session.list_tools(
                        params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
                    for tool in listing.tools:
                        # Normalized internal shape. The SDK model dumps snake_case field names
                        # (``input_schema``), and the registry must not depend on which spelling a
                        # particular SDK release emits.
                        tools.append({'name': tool.name,
                                      'description': tool.description,
                                      'inputSchema': tool.input_schema,
                                      'outputSchema': tool.output_schema,
                                      'annotations': (tool.annotations.model_dump(mode='json')
                                                      if tool.annotations else None)})
                        if len(tools) > MAX_TOOLS:
                            raise UpstreamError('discovery_tool_limit',
                                                f'the service publishes more than {MAX_TOOLS} tools')
                    cursor = getattr(listing, 'next_cursor', None)
                    if not cursor:
                        break
        except UpstreamError:
            raise
        except asyncio.TimeoutError as exc:
            raise UpstreamError('discovery_timeout', 'the service did not answer in time') from exc
        except Exception as exc:  # noqa: BLE001 - any transport failure is a discovery failure
            raise UpstreamError('discovery_failed', f'{type(exc).__name__}: {exc}') from exc
        finally:
            await _close(http_client)
        return tools

    async def call_tool(self, endpoint, service_id, tool, arguments, context, *,
                        credential_id=None, deadline=None):
        """One ``tools/call`` with trusted internal metadata."""
        budget = deadline or self.deadline
        meta = {INTERNAL_PREFIX + 'operation_id': context['operation_id'],
                INTERNAL_PREFIX + 'demo_run_id': context['demo_run_id'],
                INTERNAL_PREFIX + 'actor': context['actor']}
        http_client = self._http_client(service_id, credential_id)
        try:
            async with self._session(endpoint, http_client) as session:
                # The deadline is enforced with anyio's own cancel scope, in the same task that runs
                # the session. An asyncio ``wait_for`` around the SDK cancels its internal task group
                # from outside and trips an anyio cancel-scope error; an anyio scope cancels the
                # children it owns and stays clean.
                with anyio.move_on_after(budget) as scope:
                    await session.initialize()
                    # Preserve the typed wire result for Gate's pinned-schema validation.
                    # ClientSession.call_tool validates business output first and throws away
                    # malformed results, incorrectly conflating them with lost responses.
                    from mcp import types
                    result = await session.send_request(
                        types.CallToolRequest(params=types.CallToolRequestParams(
                            name=tool, arguments=arguments, _meta=meta)),
                        types.CallToolResult)
            if scope.cancelled_caught:
                raise UpstreamError('upstream_timeout',
                                    'the service did not answer before the upstream deadline',
                                    dispatched=True)
        except UpstreamError:
            raise
        except asyncio.TimeoutError as exc:
            raise UpstreamError('upstream_timeout',
                                'the service did not answer before the upstream deadline',
                                dispatched=True) from exc
        except Exception as exc:  # noqa: BLE001 - classified below
            code, dispatched = _classify(exc)
            raise UpstreamError(code, f'{type(exc).__name__}: {exc}', dispatched=dispatched) from exc
        finally:
            await _close(http_client)
        structured = getattr(result, 'structured_content', None)
        text = '\n'.join(block.text for block in result.content
                         if getattr(block, 'type', None) == 'text')
        size = len(text.encode('utf-8'))
        if structured is not None:
            size = max(size, len(json.dumps(structured, ensure_ascii=False).encode('utf-8')))
        return UpstreamResult(is_error=bool(getattr(result, 'is_error', False)),
                              structured=structured, text=text, bytes_out=size,
                              protocol_version='2025-11-25')

    async def operation_status(self, status_endpoint, service_id, operation_id, *,
                               credential_id=None):
        """Read-only receipt probe used by reconciliation. Never mutates anything."""
        import httpx2
        url = f'{status_endpoint.rstrip("/")}/{operation_id}'
        try:
            async with httpx2.AsyncClient(
                    headers=_headers(GATE_SERVICE_ID, self._token(service_id, credential_id)),
                    timeout=httpx2.Timeout(connect=self.connect_timeout, read=self.deadline,
                                           write=self.deadline, pool=self.connect_timeout)) as client:
                response = await asyncio.wait_for(client.get(url), self.deadline)
                if response.status_code != 200:
                    raise UpstreamError('status_probe_failed',
                                        f'the service answered {response.status_code}')
                return response.json()
        except UpstreamError:
            raise
        except asyncio.TimeoutError as exc:
            raise UpstreamError('status_probe_timeout', 'the status probe timed out') from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError('status_probe_failed', f'{type(exc).__name__}: {exc}') from exc


async def _close(http_client):
    try:
        await http_client.aclose()
    except Exception:  # noqa: BLE001 - closing must never mask the original result
        pass


def _classify(exc) -> tuple:
    """Map a transport exception to a typed code and whether an effect is possible."""
    import httpx2
    for error_type in (httpx2.ConnectError, httpx2.ConnectTimeout):
        if isinstance(exc, error_type):
            # The connection was never established, so nothing could have been executed.
            return 'upstream_unavailable', False
    name = type(exc).__name__
    if name in ('MCPError', 'McpError'):
        code = getattr(exc, 'code', None)
        if code == -32602:
            return 'upstream_rejected', False
        return 'upstream_error', True
    if isinstance(exc, (httpx2.TimeoutException, httpx2.TransportError, httpx2.HTTPError)):
        return 'upstream_transport_error', True
    return 'upstream_error', True
