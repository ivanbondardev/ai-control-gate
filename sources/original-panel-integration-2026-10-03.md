# Original frontend and server-side scenarios — October 3, 2026

## Assignment and scope correction

**Source fact — direct assignment from the owner in this session:** "yes. take the original frontend as the basis and implement the missing server-side capabilities for its scenarios."

This confirms the replacement of the previous narrowed variant described in the previous report (archive reference: `frontend-integration-2026-10-03.md`). The previous 68 browser checks were not proof of parity. The current result is described below.

## What was implemented

**Facts from the source code and executed checks:**

| Original UI scenario | Server-side implementation |
|---|---|
| Check library, adding, editing, disabling, pipeline order | Original checks schema; shared evaluator for compare and runtime |
| YAML↔forms, import/export | Local js-yaml, file → shared server draft; activation separate |
| Rules by agent, service, action and parameter conditions | Conditions, specificity, block on equal specificity, default reaction |
| Visual test cases and fault injection | Stored corpus, server-side live/candidate results; test-only faults do not allow activation |
| Impact, activation, history, rollback | Linked to candidate/tests/registry/version evidence, CAS, new version on rollback |
| External policy change during editing | Polling of the actual server state, rebase or acceptance of the new active |
| Service import and validation | Typed schema in PostgreSQL, local validation, endpoint metadata only |
| Request execution and details | Server admission → local action → outbound checks → sanitized log |
| False-positive review, exception, save-as-test, replay | Stored review, versioned exception via compare, sanitized replay without dispatch |
| Training review and JSONL | Examples of actual baseline evaluations, human confirmation/correction, export of reviewed |

Code: [frontend](../app/static/control/panel.js), [HTML/CSS](../app/static/control/index.html), [evaluator](../app/action_gate/panel_engine.py), [lifecycle/runtime](../app/action_gate/panel_service.py), [migration](../app/migrations/0004_control_panel.sql). The English-language [API contract](../app/contracts/control-panel.md).

**Fact of preserving the original:** the nested Git clone `ai-control-layer/` at `fbf4c03` has no local changes. The integrated copy of the components is located in `app/static/control/`. The styles were also adapted to the in-app browser width so that the library does not push the whole pipeline below the first screen.

## Semantics and boundaries

**Implementation fact:** `/v1/panel/*` runs in the same HTTP application and PostgreSQL, but has a separate original policy schema. It is executed by `/v1/panel/invoke`. The old `/v1/invocations` and `/v1/config/*` keep the previous policy and developer workbench. Activation in the new builder does not switch the old gateway; old records are not mixed with the new panel.

**Implementation fact:** one transactional state row ensures atomicity of activation, admission, local effect, log and idempotency claim. State is limited to 32 MB and separate collection limits; exceeding them returns 413 and rolls back the mutation. There is no automatic cleanup/archival. The PostgreSQL bootstrap adds initial 11 checks, 10 rules, 6 services, 12 tests; events/training are empty.

**Boundary fact:** all adapters are synthetic. Documents supports local read/search/update/delete; other actions have an explicit synthetic result and effect record. No real third-party systems were called. Throttle is admission rejection with retry-after, without hidden sleep/queue. Tokens are a signed estimate, not provider usage.

**Boundary fact:** semantic checks are a deterministic baseline. The model/instruction fields are stored, instruction_version is controlled by the server, but arbitrary instructions are not executed by a model. Cache, model tokens and external signature feed are not simulated. Secrets/PII are sanitized before baseline regardless of pipeline order. Regex is limited to a safe subset and a maximum of 64 patterns; the local evaluation budget of 1000 ms ends in rejection, and an incomplete compare does not allow activation.

**Fact of checking the standard examples on PostgreSQL:** 11/12 match the specified expectations. `Security training question` is a known baseline false positive: allow is expected, actually block. This was left visible; the browser scenario checks its review/exception. These fixtures are not a holdout set and do not prove protection quality.

**Boundary fact:** replay works with sanitized stored content, without service effects and without reproducing old rate counters. YAML import does not create a watcher on the server file system. Training export does not train a model. Unverified: load, production authentication/TLS, real model/service adapters, the full mobile browser matrix and PostgreSQL crash injection.

## Checks and launch

**Facts of the final runs:**

| Check | Result | Evidence |
|---|---|---|
| Python 3.11 unit/HTTP | 211 found, 191 passed, 20 DB integration skipped | unit.log (archive reference: `original-panel-checks-2026-10-03/unit.log`) |
| PostgreSQL scratch DB | 20 passed; persistence, draft CAS, 6 concurrent invoke → one effect, 2 activation → one winner | postgres.log (archive reference: `original-panel-checks-2026-10-03/postgres.log`) |
| Chrome, isolated memory backend | 50 passed checks of the original scenarios; no JS exceptions | browser.log (archive reference: `original-panel-checks-2026-10-03/browser.log`) |
| Docker build/migration/readiness | API healthy, PostgreSQL durable, Redis ready | deploy.log (archive reference: `original-panel-checks-2026-10-03/deploy.log`), ready.json (archive reference: `original-panel-checks-2026-10-03/ready.json`) |
| In-app browser → Traefik → PostgreSQL | Operator connection, original builder, server-side run of 12 fixtures | screenshot (archive reference: `original-panel-checks-2026-10-03/08-live-postgres.png`) |
| JS syntax, git diff --check, clone cleanliness | Passed | local session commands |

**Methodology fact:** the lifecycle/rule changes/invocations of the browser run were isolated on `127.0.0.1:18082`; the DB tests use and delete the scratch `action_gate_integration`, not the main DB. In the main panel a compare of the initial corpus was run without activation or service dispatch. The old gateway stayed at generation 26. There were no paid model calls in this session.

Reproduction: fresh memory backend without `.env`, dedicated Chrome with debugging port 9229, `make control-ui-check`. The scenario [panel-ui-check.js](../scripts/panel-ui-check.js) refuses to work with a durable/provider-backed or non-empty server.

Local result: [open the builder](http://ai-control-proxy.localhost/control/#/builder/checks). The containers were left running; the temporary memory server and headless Chrome were stopped after the checks.
