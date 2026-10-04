# MCP protocol and transport profile

Status: verified by the M00 spike against a locally built image (Python 3.13, `mcp==2.3.0`).
Every statement below is either **verified** (an executed check, with the command named) or
**chosen** (a deliberate demo restriction). Nothing here is a claim about the newest revision.

## 1. Compatibility target

| Item | Value | Source |
|---|---|---|
| Protocol revision negotiated in the spike | `2025-11-25` | verified, `app/tests/test_mcp_profile.py` |
| SDK | `mcp==2.3.0` | verified, `app/requirements-mcp.lock` |
| Transport | Streamable HTTP, JSON responses, no protocol sessions | chosen |
| Endpoint | `POST /mcp` only | chosen |
| Server API | `mcp.server.lowlevel.Server` with `on_list_tools` / `on_call_tool` callbacks | verified |
| Client API | `mcp.client.streamable_http.streamable_http_client` + `mcp.ClientSession` | verified |

The spike also established what changed in the SDK major version, because the plan was written
against the v1 documentation surface and a silent assumption would have broken the build:

* `mcp.server.fastmcp.FastMCP` was renamed to `mcp.server.mcpserver.MCPServer`. Importing
  `mcp.server.fastmcp` on 2.x raises `ModuleNotFoundError` with an explicit migration message.
* The low-level `Server` no longer exposes `@server.list_tools()` / `@server.call_tool()`
  decorators. Handlers are constructor arguments: `on_list_tools`, `on_call_tool`.
* Client transport entry point is `streamable_http_client` (not `streamablehttp_client`) and it
  yields **two** streams, not three.
* Protocol models are snake_case (`protocol_version`, `server_info`, `input_schema`,
  `structured_content`); the JSON wire form keeps `camelCase`.
* `ClientSession.call_tool` accepts `meta=` (the JSON-RPC `params._meta`), not `_meta=`.
* `mcp.shared.exceptions.McpError` is `MCPError(code, message, data)`.
* `httpx2` replaces `httpx` as the SDK HTTP client; use
  `mcp.client.streamable_http.create_mcp_http_client(headers=...)` to attach credentials.

## 2. Server surface

* `tools` capability only. No `listChanged` subscription; resources, prompts, sampling,
  elicitation, task execution and completion are not advertised.
* `tools/list` returns full JSON Schema objects verbatim, including `additionalProperties: false`.
  The SDK does not rewrite or validate them, so the runtime validates arguments itself
  (`jsonschema`) **and** keeps the raw schema for the operator UI.
* `tools/call` reads trusted call context from JSON-RPC `params._meta` (verified reachable as a
  plain `dict` on 2.3.0). Business arguments stay pure; control fields are never business
  arguments.
* A handler raising `MCPError` produces a JSON-RPC error, verified for the unified refusal of an
  unknown or unpublished tool. Business and policy refusals are deliberately **not** JSON-RPC
  errors: they return `isError: true` with a typed `structuredContent` payload.
* The SDK does not enforce `inputSchema` server-side: in the spike, `probe` accepted an extra
  argument. Strict validation is therefore an explicit runtime responsibility, not an SDK feature.
* `structuredContent` is echoed to the client only when the tool declares an `outputSchema`;
  both text content and `structuredContent` are emitted from the same cleaned object.

## 3. Transport restrictions in this profile

* `GET /mcp` opens no SSE stream. The SDK answers `406 Not Acceptable` to a GET without
  `Accept: text/event-stream`, and the ingress authenticates before the transport is reached, so an
  unauthenticated GET is answered `401`. The plan assumed `405`; the verified status codes are
  recorded here instead of the assumption.
* Requests are stateless (`stateless_http=True`) and answered as JSON (`json_response=True`),
  so no protocol session id is minted. JSON-RPC ids correlate messages only; they are never used
  as business idempotency keys.
* `max_request_body_size` bounds the request; the runtime additionally bounds the result it will
  accept from an upstream service.
* Transport identity is enforced by an ASGI wrapper **before** the MCP transport:

  | Header | Meaning |
  |---|---|
  | `X-Action-Gate-Principal` | transport principal id |
  | `X-Action-Gate-Token` | that principal's token |

  Missing or mismatched identity is `401` before any tool dispatch, so a refused caller cannot
  reach `tools/list` and cannot observe the catalog. Cookies, wildcard CORS and Origin-based trust
  are not used.
* DNS-rebinding protection is delegated to the Compose network boundary and Traefik routing; the
  service-level setting is explicit in code rather than silently defaulted.

## 4. Client surface

* The scenario client sends the same two identity headers through
  `create_mcp_http_client(headers=...)`.
* Every mutation sends a stable `client_operation_key` in
  `params._meta["actiongate.demo/operation_key"]`. This is **our extension**, not an MCP guarantee:
  a third-party host that does not send it can read, but a mutation without a key is refused with a
  typed error instead of being executed once per retry. This limit is documented, not smoothed
  over.
* The Gate→service hop uses a different `_meta` namespace
  (`actiongate.internal/operation_id`, `actiongate.internal/demo_run_id`,
  `actiongate.internal/actor`). It is never forwarded from, or to, the client.

## 5. Version drift policy

The negotiated revision is recorded per operation. If a future SDK or service negotiates a
revision outside the profile, the ingress fails closed and the incompatibility is reported rather
than downgraded silently.
