# Client request format — 2026-10-04

**Source fact — owner clarification:** "important, the request format must match the format of real requests (we will take the OpenAI provider by default)".

Context: a discussion of simple Bash scenarios for simulating a client/agent through Gate. The requirement defines the provider format; it does not select the model or a specific OpenAI endpoint and does not assign external calls or costs.

**Official source fact:** OpenAI recommends Responses for new projects; endpoint `/v1/responses`, input `input`, output `output`, separate items `function_call` and `function_call_output`, linked via `call_id`. Chat Completions remains supported. [OpenAI Docs](https://developers.openai.com/api/docs/guides/migrate-to-responses).

**Proposal, high confidence:** take the Responses API as the initial model input profile, and Bash + curl + JSON fixtures as the client; also store the response in the provider format. At the first stage, a local provider stub with explicitly synthetic responses. Perform MCP calls as a separate step of the client cycle via `/mcp`.

**Code review fact:** searching for routes in `app/action_gate` finds its own `/v1/invocations` and `/v1/panel/invoke`, but not `/v1/responses` or `/v1/chat/completions`. OpenAI model input compatibility was not confirmed in this session and was not implemented.


## Subsequent owner clarification — real provider

**Direct assignment fact:** "the gate acts as a proxy, so it must forward requests to the real provider (also OpenAI by default); for this use the API key I provided. That is, we will not create dummy emulations of a real LLM provider."

This cancels the previous proposal of a local LLM stub. Model input must forward allowed requests to the real provider, OpenAI by default; the use of the provided API key for this is directly assigned. This clarification does not define the specific model and endpoint. Dummy MCP services are a separate part of the demo; the requirement concerns the LLM provider.

**Local check fact:** `.env` contains a non-empty `DETECTOR_PROVIDER_API_KEY` value; `OPENAI_API_KEY` is absent from the process environment. The key value was not printed. The current adapter in `app/action_gate/detectors.py` uses the key for the semantic detector; that by itself does not implement the client-side model proxy. Whether the key belongs to OpenAI, its validity, the available models and the balance were not checked. No model requests were made in this session.

**Proposal, high confidence:** Bash/curl sends an OpenAI Responses request to Gate; Gate validates it, adds the server-side provider key, forwards it to OpenAI and validates the response. The key stays in the server configuration, outside fixtures and logs. The semantic detector and the proxied client generation have separate configuration roles.
