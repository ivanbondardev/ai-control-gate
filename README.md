# Action Gate — AI Control Layer

Standalone source snapshot prepared on 2026-10-04 for the HackYeah project.
Start with this file and [AGENTS.md](AGENTS.md).

## Scope and evidence

Source facts: the implementation includes a policy editor, protected invocation APIs,
a unified MCP gateway with synthetic Documents/Outbox/Tickets services, reporting,
and an OpenAI Responses proxy. Read the preserved reports for their exact limits:
[panel](sources/original-panel-integration-2026-10-03.md),
[MCP](sources/mcp-fixes-2026-10-04.md),
[model proxy](sources/model-proxy-implementation-2026-10-04.md),
[operator fixes](sources/operator-fixes-2026-10-04.md).
Historical test results in those reports are not new verification of this snapshot.
See [transfer notes](docs/transfer.md) for this copy's checks and exclusions.

## Start after moving this entire directory

Use Python 3.13 (the container version) or a compatible newer Python for offline tests,
Docker with Compose and Make for the stack. The macOS system Python 3.9 is too old.
On this Mac, `PATH=/opt/homebrew/bin:$PATH make test` selects the installed Python 3.14.
Run from this directory:

```sh
make test
make init
make demo-mcp-up
```

The template uses a distinct Compose project, `action-gate-standalone`, with fresh
volumes. Port 80 is unchanged to preserve the existing client defaults. Stop the
old stack before starting this one, or set `TRAEFIK_HTTP_PORT=8080` in the new `.env`.
With port 8080, use `http://ai-control-proxy.localhost:8080/control/` and explicitly
set client origins as shown below. Do not reuse the old Compose project name.

Default panel: <http://ai-control-proxy.localhost/control/>.
Operator identity: `operator-local` / `local-operator-token` (synthetic local defaults).
`make demo-mcp-up` generates local service credentials and bootstraps the MCP demo.
Use `make up` for the base stack without bootstrapping the dummy services.

```sh
# After starting the stack; these checks create synthetic test activity.
make test-integration
make acceptance
make demo-mcp-test
# If you selected port 8080:
BASE_URL=http://ai-control-proxy.localhost:8080 make acceptance
GATE_BASE_URL=http://localhost:8080 ./scripts/gate-scenarios/preflight.sh
```

No provider keys are included. Real model calls require separate server-side
configuration; see [the model proxy contract](app/contracts/model-proxy.md).
Existing policies, audit history and service state from the old database are not
included. Files provide bootstrap defaults, not a dump of the previous live demo.

## Staging deployment

Target: `https://ai-control-gate.ivbon.dev`. See [the staging runbook](docs/staging.md).
`python3 scripts/deploy-staging.py --check` verifies a clean checkout matching GitHub
default-branch HEAD. The deploy script uses SSH and never packages uncommitted work.

## Project map

- [Complete documentation map](docs/00-documentation-map.md) and [cleanup record](docs/09-documentation-cleanup.md).

- [Application guide](app/README.md), [contracts](app/contracts/README.md), code and tests: `app/`.
- Infrastructure: `infra/`, `compose.yaml`; checks and clients: `scripts/`.
- [Original task documents](sources/goldman-task/README.md).
- [Judging analysis](docs/05-judging.md), [open questions](docs/07-open-questions.md).
- [Scenario matrix](docs/23-bash-scenario-matrix.md), [operator scenarios](docs/25-gate-operator-scenarios.md).
- [Pitch materials](pitch/README.md): historical drafts are in `pitch/archive/2026-10-03/`; no current submission copy is approved.
- [Current context and transfer notes](docs/transfer.md), [session log](docs/08-session-log.md).

Some retained documents describe earlier stages. Current code and dated evidence
take precedence over historical plans. References to omitted archive material are
plain text and indexed in `docs/archive-references.json`.
