"""Shared MCP runtime for a dummy service.

The service owns its data boundary:

* strict JSON Schema validation of arguments before any handler runs;
* one local transaction that commits the business change, the receipt and the journal together;
* replay of a repeated ``operation_id`` with the same request fingerprint, and a conflict when the
  same id arrives with different content;
* refusal of a late call for a closed run, and of any call the operator fenced;
* the business result and its text rendering are produced from one cleaned object.
"""
from dataclasses import dataclass, field
import json
import time
import uuid

from . import faults as fault_mod
from .contracts import (OPERATION_ID_PATTERN, ProtocolError, ServiceError, call_context, canonical,
                        fingerprint, validate_arguments)

MAX_RESULT_BYTES = 512 * 1024
DEFAULT_PORT = 8020

FAILURE_REASONS = {
    'stale_run': 'This run is closed; the request belongs to a previous demonstration run.',
    'operation_fenced': 'An operator fenced this operation as having no effect.',
    'idempotency_conflict': 'This operation id was already used with different content.',
    'business_rejected': 'The service refused the change before committing anything.',
    'result_too_large': 'The service result exceeds the accepted size.',
}

ENVELOPE_PROPERTIES = {
    'status': {'type': 'string', 'enum': ['succeeded', 'failed']},
    'service': {'type': 'string'},
    'tool': {'type': 'string'},
    'operation_id': {'type': ['string', 'null']},
    'receipt_id': {'type': ['string', 'null']},
    'replayed': {'type': 'boolean'},
}


def envelope_schema(properties: dict, required=()) -> dict:
    """Build a tool output schema: a fixed envelope plus the tool's own business fields.

    A business field never shadows an envelope field: the merge is checked so a name collision is a
    programming error at import time rather than a schema that contradicts the value it validates.
    """
    collision = sorted(set(properties) & set(ENVELOPE_PROPERTIES))
    if collision:
        raise ValueError(f'business fields collide with the result envelope: {collision}')
    required_fields = list(dict.fromkeys(['status', 'service', 'tool', 'operation_id', 'receipt_id',
                                          'replayed', *required]))
    return {
        'type': 'object',
        'properties': {**properties, **ENVELOPE_PROPERTIES},
        'required': required_fields,
        'additionalProperties': False,
    }


@dataclass(frozen=True)
class Change:
    """What a handler returns: the business payload plus version bookkeeping."""
    result: dict
    resource_id: str | None = None
    before_version: int | None = None
    after_version: int | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    handler: object
    mutation: bool = False
    annotations: dict = field(default_factory=dict)


class DummyService:
    """One service: a tool table, its store and the MCP surface over it."""

    name = 'dummy'
    version = '0.1.0'
    extra_schema = ''

    def __init__(self, store, *, hold_seconds=fault_mod.HOLD_SECONDS):
        self.store = store
        self.hold_seconds = hold_seconds
        self.tool_specs = tuple(self.build_tools())
        self.tools = {spec.name: spec for spec in self.tool_specs}
        if len(self.tools) != len(self.tool_specs):
            raise ValueError('duplicate tool names in the service table')
        self._key = None

    def build_tools(self):
        """Bound tool table. Each handler is called as ``handler(tx, context, args)``."""
        return ()

    # -- lifecycle ------------------------------------------------------------------
    def bootstrap(self, run_id=None):
        self.store.migrate(self.extra_schema)
        with self.store.write() as connection:
            self._key = self.store.secret(connection, 'request_fingerprint_key')
        return self.store.ensure_run(self.seed, run_id=run_id)

    def seed(self, connection, run_id):  # pragma: no cover - each service overrides this
        raise NotImplementedError

    def inspect(self, connection, run_id):
        return {}

    def snapshot(self, run_id=None):
        """Evidence view: local state, counters and receipts, over a read-only connection."""
        return self.store.snapshot(run_id=run_id, inspect=self.inspect)

    def current_run(self):
        with self.store.read(readonly=False) as connection:
            return self.store.active_run(connection)

    def key(self) -> bytes:
        if self._key is None:
            with self.store.write() as connection:
                self._key = self.store.secret(connection, 'request_fingerprint_key')
        return self._key

    # -- dispatch --------------------------------------------------------------------
    def dispatch(self, tool_name: str, arguments, meta):
        """Validate, check, mutate. Returns the public result dictionary or raises."""
        context = call_context(meta)
        spec = self.tools.get(tool_name)
        if spec is None:
            raise ProtocolError(-32602, f'Unknown tool: {tool_name}')
        args = validate_arguments(spec.input_schema, arguments, tool_name)
        request_fingerprint = fingerprint(self.key(), {'service': self.name, 'tool': tool_name,
                                                       'arguments': args})
        mode, delay_ms, refusal = None, 0, None
        try:
            with self.store.write() as connection:
                active = self.store.active_run(connection)
                if active != context.demo_run_id:
                    raise ServiceError('stale_run', FAILURE_REASONS['stale_run'],
                                       details={'activeRunId': active})
                receipt = self.store.receipt(connection, context.demo_run_id, context.operation_id)
                if receipt:
                    if receipt['request_fingerprint'] != request_fingerprint:
                        raise ServiceError('idempotency_conflict',
                                           FAILURE_REASONS['idempotency_conflict'])
                    self.store.record_call(connection, demo_run_id=context.demo_run_id,
                                           tool=tool_name, operation_id=context.operation_id,
                                           outcome='replayed')
                    return self._replay(receipt)
                fence = self.store.fence(connection, context.demo_run_id, context.operation_id)
                if fence:
                    raise ServiceError('operation_fenced', FAILURE_REASONS['operation_fenced'],
                                       details={'fencedAt': fence['at'], 'kind': fence['kind']})
                rule = self.store.take_fault(connection, tool_name, context.demo_run_id)
                if rule:
                    mode, delay_ms = rule['mode'], rule['delay_ms']
                    self.store.record_event(connection, demo_run_id=context.demo_run_id,
                                            kind='fault_applied', tool=tool_name,
                                            operation_id=context.operation_id,
                                            detail={'mode': mode, 'delayMs': delay_ms})
                if mode == 'business_error_before_commit':
                    # Committing here keeps the one-shot fault consumed and the attempt recorded;
                    # the refusal itself is raised after the transaction so that no effect exists.
                    self.store.record_call(connection, demo_run_id=context.demo_run_id,
                                           tool=tool_name, operation_id=context.operation_id,
                                           outcome='business_rejected')
                    refusal = ServiceError('business_rejected',
                                           FAILURE_REASONS['business_rejected'])
                    result = None
                else:
                    if mode == 'delay_before_commit' and delay_ms > 0:
                        # Held inside the transaction, before the commit, on purpose.
                        time.sleep(delay_ms / 1000.0)
                    change = spec.handler(connection, context, args)
                    receipt_id = 'rcpt-' + uuid.uuid4().hex[:20]
                    result = self._envelope(spec, context, change, receipt_id)
                    self.store.record_receipt(
                        connection, demo_run_id=context.demo_run_id,
                        operation_id=context.operation_id, tool=tool_name,
                        fingerprint=request_fingerprint, receipt_id=receipt_id,
                        outcome='succeeded', result=result, resource_id=change.resource_id,
                        before_version=change.before_version, after_version=change.after_version)
                    self.store.record_event(
                        connection, demo_run_id=context.demo_run_id, kind='committed',
                        tool=tool_name, operation_id=context.operation_id,
                        detail={'receiptId': receipt_id, 'resourceId': change.resource_id,
                                'beforeVersion': change.before_version,
                                'afterVersion': change.after_version,
                                'resultBytes': len(canonical(result).encode())})
                    self.store.record_call(connection, demo_run_id=context.demo_run_id,
                                           tool=tool_name, operation_id=context.operation_id,
                                           outcome='committed', committed=True)
        except ServiceError as exc:
            self._record_refusal(context, tool_name, exc.code)
            raise
        if refusal is not None:
            raise refusal
        if mode == 'commit_then_drop_response':
            # The local commit is durable. The caller is left without an answer until its deadline.
            time.sleep(self.hold_seconds)
        if mode == 'malformed_result':
            return {'status': 'succeeded', 'service': self.name, 'tool': tool_name,
                    'operation_id': context.operation_id, 'receipt_id': None, 'replayed': False,
                    'unexpected_field': True}
        if mode == 'oversized_result':
            return dict(result, padding='x' * fault_mod.OVERSIZED_PADDING)
        return result

    def _record_refusal(self, context, tool_name, code):
        """Refusals are evidence too, and a rollback must not erase them."""
        with self.store.write() as connection:
            self.store.record_call(connection, demo_run_id=context.demo_run_id, tool=tool_name,
                                   operation_id=context.operation_id, outcome=code)
            self.store.record_event(connection, demo_run_id=context.demo_run_id, kind='refused',
                                    tool=tool_name, operation_id=context.operation_id,
                                    detail={'code': code})

    def _envelope(self, spec, context, change, receipt_id) -> dict:
        return {'status': 'succeeded', 'service': self.name, 'tool': spec.name,
                'operation_id': context.operation_id, 'receipt_id': receipt_id, 'replayed': False,
                **change.result}

    @staticmethod
    def _replay(receipt) -> dict:
        result = json.loads(receipt['result_json'])
        result['replayed'] = True
        return result

    # -- MCP surface -------------------------------------------------------------------
    def _tool_list(self):
        import mcp.types as types
        listing = []
        for spec in self.tool_specs:
            annotations = types.ToolAnnotations(**spec.annotations) if spec.annotations else None
            listing.append(types.Tool(name=spec.name, description=spec.description,
                                      inputSchema=spec.input_schema,
                                      outputSchema=spec.output_schema, annotations=annotations))
        return listing

    def _error_result(self, params, exc: ServiceError):
        import mcp.types as types
        meta = params.meta if isinstance(params.meta, dict) else {}
        candidate = meta.get('actiongate.internal/operation_id')
        operation_id = candidate if isinstance(candidate, str) and \
            OPERATION_ID_PATTERN.fullmatch(candidate) else None
        payload = {'status': 'failed', 'service': self.name, 'tool': params.name,
                   'operation_id': operation_id, 'receipt_id': None, 'replayed': False,
                   'error': {'code': exc.code, 'message': exc.message, **exc.details}}
        return types.CallToolResult(content=[types.TextContent(type='text', text=canonical(payload))],
                                    structuredContent=payload, isError=True)

    def build_mcp_app(self, *, transport_security=None):
        import anyio
        import mcp.types as types
        from mcp.server.lowlevel import Server
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.shared.exceptions import MCPError

        service = self

        async def on_list_tools(context, params):
            return types.ListToolsResult(tools=service._tool_list())

        async def on_call_tool(context, params):
            def work():
                try:
                    return service.dispatch(params.name, params.arguments or {}, params.meta)
                except ProtocolError as exc:
                    raise MCPError(exc.code, exc.message, exc.data) from exc

            try:
                result = await anyio.to_thread.run_sync(work)
            except ServiceError as exc:
                return service._error_result(params, exc)
            text = canonical(result)
            if len(text.encode('utf-8')) > MAX_RESULT_BYTES:
                # A service that cannot render a bounded result refuses instead of letting the
                # transport decide. The oversized-result fault deliberately bypasses this so the
                # Gate's own bound is exercised.
                return service._error_result(params, ServiceError(
                    'result_too_large', FAILURE_REASONS['result_too_large']))
            return types.CallToolResult(content=[types.TextContent(type='text', text=text)],
                                        structuredContent=result)

        server = Server(name=f'{self.name}-mcp', version=self.version,
                        on_list_tools=on_list_tools, on_call_tool=on_call_tool)
        return server.streamable_http_app(
            streamable_http_path='/mcp', json_response=True, stateless_http=True,
            max_request_body_size=512 * 1024,
            transport_security=transport_security or TransportSecuritySettings(
                allowed_hosts=['*'], allowed_origins=['*'], enable_dns_rebinding_protection=False))

    def build_app(self, credentials, *, transport_security=None):
        """MCP endpoint plus the read-only operation status the Gate reconciles against."""
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        from .auth import ServiceGate

        mcp_app = self.build_mcp_app(transport_security=transport_security)

        async def operations(request):
            operation_id = request.path_params['operation_id']
            if not OPERATION_ID_PATTERN.fullmatch(operation_id):
                return JSONResponse({'error': 'invalid_operation_id'}, status_code=400)
            return JSONResponse(self.store.operation_status(operation_id))

        async def health(request):
            return JSONResponse({'status': 'ok', 'service': self.name,
                                 'runId': self.current_run()})

        async def ready(request):
            try:
                self.store.snapshot()
            except Exception as exc:  # noqa: BLE001 - readiness fails closed
                return JSONResponse({'status': 'unavailable', 'detail': type(exc).__name__},
                                    status_code=503)
            return JSONResponse({'status': 'ready', 'service': self.name})

        mcp_app.router.routes.append(Route('/operations/{operation_id}', operations, methods=['GET']))
        mcp_app.router.routes.append(Route('/health/live', health, methods=['GET']))
        mcp_app.router.routes.append(Route('/health/ready', ready, methods=['GET']))
        return ServiceGate(mcp_app, credentials)

    def serve(self, credentials, *, host='0.0.0.0', port=DEFAULT_PORT):
        import uvicorn
        run_id = self.bootstrap()
        print(json.dumps({'service': self.name, 'runId': run_id, 'port': port}), flush=True)
        uvicorn.run(self.build_app(credentials), host=host, port=port, log_level='info',
                    access_log=False)
