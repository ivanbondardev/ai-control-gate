# OpenAI Responses proxy

Implemented endpoint: `POST /v1/responses`. The client connects to `http://localhost` using
`X-Action-Gate-Principal` and `X-Action-Gate-Token`, the same identity registry as MCP. Every
registered authenticated caller can request a model permitted by the panel's global model list.
Per-principal model grants are not implemented. Provider credentials are never client credentials.

## Provider and request profile

The server sends permitted requests to **https://api.openai.com/v1/responses**, using server-side
`OPENAI_API_KEY`, falling back to the already configured `DETECTOR_PROVIDER_API_KEY`. Redirects,
retries, user-selected destinations and environment HTTP proxies are disabled on this hop.
The proxy never manufactures a model answer. `model` is required and forwarded unchanged.

Supported: text input, instructions, message history, client-executed function tools,
`function_call` / `function_call_output`, reasoning configuration, text configuration and buffered
SSE. Responses use the provider's actual response ID, model, output and usage.
Unsupported fields, hosted tools, media input, persistent Conversations, `previous_response_id`,
item references, background jobs and `store:true` are refused before dispatch. `store:false`
is enforced. This intentionally bounded profile is not a claim of full OpenAI API compatibility.
Only POST is implemented; no Chat Completions compatibility route is exposed.

Input reasoning items may carry provider-validated opaque encrypted reasoning for stateless
continuation. The proxy cannot inspect that ciphertext. It is omitted from disclosed output when
input or output was redacted, so it cannot serve as an alternate unredacted representation.
Text and function results are inspected. A provider may require a fresh conversation after such
redaction. Model-generated code is never executed by the proxy; the client runs its own tool loop.

## Policy and admission

Two existing configuration systems are composed, rather than silently bypassing either:

- The **active panel policy** supplies the model allowlist, PII/secret/pattern controls, its current
  labelled baseline semantic checks, and per-principal rate/loop/admission-token limits. These
  controls share the panel policy used by MCP. An enabled blocking model allowlist is mandatory.
- The **active configuration release** supplies the durable daily budget, content thresholds,
  signature feed, deadline and detector profile. Additional content checks can reject a request
  the panel admitted. These legacy controls are edited through `/v1/config`, not the panel builder.

Both versions are pinned for a call and recorded in audit and response headers. They are separate
snapshots, not an atomic combined release. A panel activation affects the next request. The model
allowlist is owned by the panel; legacy `allowed_models` is not an additional list on this route.
No policy is weakened merely because the upstream accepts a model.

Whole-content and per-field checks preserve JSON structure. Sensitive schema keys or structural
fields that cannot safely be rewritten cause refusal. IDs and encrypted reasoning are not run
through PII substitutions. Input is sanitized **before** any external semantic or target call.

Panel `modelProxyAdmissionUsage` counts conservative admission units per caller/day; it is distinct
from measured OpenAI usage. Counts are deliberately not refunded after refusal/failure. Attempts
are serialized using the existing panel transaction; no panel lock is held during network calls.
They are currently separate from the panel's synthetic invocation counters and MCP counters.

## Budget and time

The existing PostgreSQL ledger atomically reserves tokens, configured monetary allowance and wall
clock time before external work. Reservations include target completion and both semantic checks.
The byte-based token estimate is conservative but remains an estimate, not a tokenizer guarantee.
The configured `costMicroPerToken.provider-chat-v1` rate is a conservative internal allowance,
**not an OpenAI invoice or a measured USD charge**. Missing/nonpositive rate fails closed.

OpenAI `usage` is measured provider usage. Semantic usage is separately labelled as reported,
estimated (baseline), replayed or unknown. On a timeout, missing usage or unclassified transport
failure the full reservation is charged as unknown; it is not reported as free. A crash leaves
outstanding reservations in place. This route does not automatically reconcile them or retry.

`budgets.reserve.globalDeadlineMs`, `targetTimeMs`, `outputTimeMs`, and `minTargetWindowMs`
bound execution; output-check time is reserved before dispatch. Requests default to 1024 output
tokens; client caps above 4096 are refused. The existing global limits can further refuse any call.

## Output and buffered SSE

`stream:true` uses a real upstream **non-streaming** request, followed by complete output checks.
Only then does Gate emit Responses SSE events. `X-Action-Gate-Streaming: buffered` makes this
explicit. This adds time to the first visible token, but no uninspected upstream delta is exposed.
There is no raw-stream fallback. A blocked output returns an HTTP error before any SSE begins.

Checked text and function arguments appear consistently in all emitted events. Input echoes and
arbitrary provider metadata are withheld. Incomplete provider responses retain their actual status
and usage; they are not relabelled as completed. Wire handling covers messages and function calls;
this is not a full replay of every possible OpenAI event subtype.

## Audit and errors

`X-Action-Gate-Invocation-Id`, `X-Action-Gate-Policy-Release`, and
`X-Action-Gate-Panel-Policy` correlate the request. Existing `/v1/invocations/{id}` and audit export
show sanitized metadata, policy decisions, keyed payload hashes, provider request/response IDs,
usage and budget events. They never store the raw prompt, model answer or API key. An audit
checkpoint is committed before dispatch; failure to persist it prevents the provider call.
After dispatch, failure to settle the budget or persist final audit withholds the answer.

Errors use `{ "error": { "type": "action_gate_error", "code": "...", "message": "..." } }`.
401: identity; 400/422: invalid/unsupported body; 403: policy; 413: size; 429: admission/budget;
502: upstream error; 503: missing mandatory dependency; 504: deadline. Provider error text and
credentials are never reflected. An upstream 429 is `502 provider_rate_limited`, so it cannot be
mistaken for a local budget refusal. Provider timeout is an unknown outcome, not cancellation.

## Operator setup and verification

After supplying the server key, allow the configured model through the normal compare/activate
path (no direct edits to the active row):

```sh
docker compose --env-file .env exec -T api python -m action_gate.model_proxy_setup
OPENAI_MODEL=gpt-5-nano-2025-08-07 ./scripts/gate-scenarios/run.sh --case L01
```

Setup uses `MODEL_PROXY_MODEL` when supplied, otherwise `DETECTOR_PROVIDER_MODEL`. It preserves
all other panel rules and refuses newly introduced comparison failures. Existing known baseline
mismatches are reported explicitly. No actual provider call occurs during this setup comparison. Setup also compares and activates
a configuration draft raising target/output/global windows to at least 15000/4000/20000 ms,
while preserving daily caps and requiring unchanged decisions on its comparison cases.

`MODEL_PROXY_DETECTOR_PROFILE` optionally selects the existing detector profile. Empty follows
the active release default, currently `baseline-offline-v1`; real target generation does **not**
turn this baseline into an AI classifier. `provider-chat-v1` requires its own configured provider
and adequate deadlines. The two roles are independent even if they share the same server key.
