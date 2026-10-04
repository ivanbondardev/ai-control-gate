"""Client-facing MCP ingress.

One endpoint, one catalog, one dispatch owner. This process holds no second policy copy: it reads
the same panel policy row the operator edits, publishes only reviewed registry mappings, and every
call goes through the ExecutionCoordinator.

Transport identity is resolved before the MCP transport runs, so an unauthenticated caller cannot
even list tools. `tools/list` is filtered per principal and policy version; a call is checked again
against the full policy, and a guessed name of a hidden tool gets the same answer as an unknown one.
"""
import contextvars
import json
import os
import threading
import time

from . import __version__
from .execution import ExecutionCoordinator, ToolCallRejected
from .identity import resolve_mcp
from .mcp_upstream import McpUpstream
from .policy_reader import PanelPolicyReader, PolicyUnavailable
from .service_registry import ServiceRegistry, visible_bindings
from .storage.operations import STATUS_UNKNOWN, build_operations

OPERATION_KEY = 'actiongate.demo/operation_key'
DEFAULT_MCP_PORT = 8010
REGISTRY_CACHE_SECONDS = 2.0
MAX_REQUEST_BYTES = 512 * 1024

CURRENT_PRINCIPAL = contextvars.ContextVar('action_gate_mcp_principal', default=None)

GATE_FIELDS_ANNOTATIONS = {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True}


class McpApplication:
    """Owns the long-lived objects of the MCP ingress."""

    def __init__(self, environ=None, *, core=None):
        self.environ = dict(os.environ if environ is None else environ)
        if core is None:
            from .http_server import GateApplication
            core = GateApplication(self.environ)
        self.core = core
        self.startup_error = None
        self.repository = core.repository
        self.operations = None
        self.coordinator = None
        self.registry_service = None
        self._registry_cache = (0.0, None)
        self._catalog_cache = {}
        self._lock = threading.RLock()
        if self.repository is None:
            self.startup_error = core.startup_error or 'storage_unavailable'
            return
        try:
            self.operations = build_operations(self.repository)
            self.policy_reader = PanelPolicyReader(self.repository)
            credentials = self._service_credentials()
            allowlist = ServiceRegistry.load_allowlist(
                self._allowlist_path(), allowed_hosts=self._allowed_hosts())
            self.upstream = McpUpstream(credentials)
            self.registry_service = ServiceRegistry(
                allowlist, credentials, self.operations, self.upstream,
                allowed_hosts=self._allowed_hosts())
            salt = core.salt or self.environ.get('APP_HASH_SALT', 'local-development-salt')
            self.coordinator = ExecutionCoordinator(
                operations=self.operations, policy_reader=self.policy_reader,
                registry_provider=self.registry, upstream=self.upstream, salt=salt)
            self.reconcile_on_start()
        except Exception as exc:  # noqa: BLE001 - reported through readiness
            self.startup_error = f'{type(exc).__name__}: {exc}'

    # -- configuration -----------------------------------------------------------------
    def _allowlist_path(self):
        return self.environ.get('APP_MCP_ALLOWLIST') or str(
            self.core.policy_dir + '/mcp_services.json')

    def _credentials_path(self):
        return self.environ.get('DEMO_CREDENTIALS_FILE') or '/run/demo/credentials.json'

    def _allowed_hosts(self):
        raw = self.environ.get('APP_MCP_ALLOWED_HOSTS')
        if raw is None:
            return {'documents-mcp', 'outbox-mcp', 'tickets-mcp'}
        return {host.strip() for host in raw.split(',') if host.strip()}

    def _service_credentials(self):
        """``{service_scope: {caller_identity: token}}`` — the Gate holds every service token."""
        from dummy_mcp.common.auth import load_credentials
        try:
            return load_credentials(self._credentials_path())
        except OSError as exc:
            raise RuntimeError(f'service credentials are required at '
                               f'{self._credentials_path()}: {exc}') from exc

    # -- registry and catalog ------------------------------------------------------------
    def registry(self):
        """Active registry revision, cached for a bounded moment to keep the hot path cheap."""
        with self._lock:
            cached_at, cached = self._registry_cache
            if cached is not None and (time.monotonic() - cached_at) < REGISTRY_CACHE_SECONDS:
                return cached
        active = self.registry_service.active() if self.registry_service else None
        with self._lock:
            self._registry_cache = (time.monotonic(), active)
        return active

    def catalog(self, principal, policy):
        key = (principal.id, policy['policyVersion'], policy['policyHash'],
               self.registry().revision if self.registry() else 0)
        with self._lock:
            if key in self._catalog_cache:
                return self._catalog_cache[key]
        registry = self.registry()
        visible = visible_bindings(registry, policy['policy'], principal.id) if registry else []
        with self._lock:
            self._catalog_cache = {key: visible}
        return visible

    # -- identity ------------------------------------------------------------------------
    def principal(self, headers):
        snapshot = self.core.config_source.load() if self.core.config_source else None
        return resolve_mcp(snapshot, headers)

    def _principal_from_context(self, context):
        principal = CURRENT_PRINCIPAL.get()
        if principal is not None:
            return principal
        request = getattr(context, 'request', None)
        headers = getattr(request, 'headers', None)
        if headers is not None:
            principal, _ = self.principal(dict(headers))
            return principal
        return None

    # -- lifecycle -------------------------------------------------------------------------
    def reconcile_on_start(self):
        """Close pre-dispatch claims; leave dispatched ones visible as unknown."""
        if self.operations is None:
            return {'closed': 0}
        state = self.operations.run_state()
        closed = self.operations.close_interrupted(state['run_id'])
        return {'runId': state['run_id'], 'closed': len(closed)}

    def counters(self):
        state = self.operations.run_state()
        return {'runState': state, 'counters': self.operations.counters(state['run_id'])}

    # -- MCP surface ------------------------------------------------------------------------
    def build_app(self):
        import mcp.types as types
        from mcp.server.lowlevel import Server
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.shared.exceptions import MCPError
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        application = self

        if self.coordinator is None:
            raise RuntimeError(f'MCP ingress is not ready: {self.startup_error}')

        async def on_list_tools(context, params):
            principal = application._principal_from_context(context)
            if principal is None:
                raise MCPError(types.INVALID_PARAMS, 'Unknown or unavailable tool')
            try:
                policy = await _thread(application.policy_reader.read)
            except PolicyUnavailable as exc:
                raise MCPError(-32603, f'Policy is unavailable: {exc.code}') from exc
            tools = []
            for binding in application.catalog(principal, policy):
                schema = binding.published_output_schema
                tools.append(types.Tool(
                    name=binding.published_name, description=binding.description,
                    inputSchema=binding.input_schema, outputSchema=schema,
                    annotations=types.ToolAnnotations(
                        readOnlyHint=not binding.mutation,
                        destructiveHint=False,
                        idempotentHint=True)))
            return types.ListToolsResult(tools=tools)

        async def on_call_tool(context, params):
            principal = application._principal_from_context(context)
            if principal is None:
                raise MCPError(types.INVALID_PARAMS, 'Unknown or unavailable tool')
            registry = application.registry()
            binding = registry.binding(params.name) if registry else None
            if binding is None:
                # Identical answer for an unknown name and a hidden one: no catalog oracle.
                raise MCPError(types.INVALID_PARAMS, 'Unknown or unavailable tool')
            meta = params.meta if isinstance(params.meta, dict) else {}
            key = meta.get(OPERATION_KEY)
            if key is not None and (not isinstance(key, str) or not 1 <= len(key) <= 200):
                raise MCPError(types.INVALID_PARAMS,
                               f'{OPERATION_KEY} must be a string of at most 200 characters')
            try:
                result = await application.coordinator.execute(
                    principal=principal, binding=binding, arguments=params.arguments or {},
                    client_operation_key=key, request_id=str(context.request_id))
            except ToolCallRejected as exc:
                raise MCPError(exc.code if isinstance(exc.code, int) else types.INVALID_PARAMS,
                               exc.message, exc.data) from exc
            except PolicyUnavailable as exc:
                raise MCPError(-32603, f'Policy is unavailable: {exc.code}') from exc
            text = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            return types.CallToolResult(
                content=[types.TextContent(type='text', text=text)], structuredContent=result,
                isError=result.get('status') != 'succeeded')

        server = Server(name='action-gate', version=__version__, on_list_tools=on_list_tools,
                        on_call_tool=on_call_tool)
        app = server.streamable_http_app(
            streamable_http_path='/mcp', json_response=True, stateless_http=True,
            max_request_body_size=MAX_REQUEST_BYTES,
            transport_security=TransportSecuritySettings(
                allowed_hosts=['*'], allowed_origins=['*'], enable_dns_rebinding_protection=False))

        async def health(request):
            return JSONResponse({'status': 'ok', 'service': 'gate-mcp',
                                 'version': __version__, 'ready': application.coordinator is not None})

        async def ready(request):
            if application.startup_error or application.coordinator is None:
                return JSONResponse({'status': 'unavailable',
                                     'detail': application.startup_error}, status_code=503)
            registry = application.registry()
            return JSONResponse({'status': 'ready',
                                 'registryRevision': registry.revision if registry else None,
                                 'services': [entry.service_id
                                              for entry in registry.services.values()]
                                 if registry else []})

        app.router.routes.append(Route('/health/live', health, methods=['GET']))
        app.router.routes.append(Route('/health/ready', ready, methods=['GET']))
        return IdentityGate(app, application)

    def serve(self, *, host='0.0.0.0', port=None):
        import uvicorn
        port = port or int(self.environ.get('APP_MCP_PORT', DEFAULT_MCP_PORT))
        print(json.dumps({'service': 'gate-mcp', 'port': port,
                          'ready': self.coordinator is not None,
                          'startupError': self.startup_error}), flush=True)
        uvicorn.run(self.build_app(), host=host, port=port, log_level='info', access_log=False)


class IdentityGate:
    """Authenticate before the transport; publish the principal to the tool handlers."""

    def __init__(self, app, application):
        self.app = app
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        if path.startswith('/health/'):
            return await self.app(scope, receive, send)
        headers = {key.decode('latin-1'): value.decode('latin-1')
                   for key, value in scope.get('headers', [])}
        principal, failure = self.application.principal(headers)
        if principal is None:
            body = json.dumps({'error': failure}).encode()
            await send({'type': 'http.response.start', 'status': 401,
                        'headers': [(b'content-type', b'application/json'),
                                    (b'content-length', str(len(body)).encode())]})
            await send({'type': 'http.response.body', 'body': body})
            return
        CURRENT_PRINCIPAL.set(principal)
        return await self.app(scope, receive, send)


async def _thread(function, *args):
    import anyio
    return await anyio.to_thread.run_sync(lambda: function(*args))


def main() -> int:
    application = McpApplication()
    if application.startup_error:
        print(json.dumps({'service': 'gate-mcp', 'error': application.startup_error}), flush=True)
    application.serve()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
