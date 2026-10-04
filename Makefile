COMPOSE = docker compose --env-file .env
DEMO_COMPOSE = $(COMPOSE) --profile demo-mcp

.PHONY: init config up down status logs test test-integration acceptance ui-check control-ui-check quality smoke \
	demo-mcp-secrets demo-mcp-up demo-mcp-down demo-mcp-bootstrap demo-mcp-publish demo-mcp-client \
	demo-mcp-inspect demo-mcp-test demo-mcp-reconcile demo-mcp-fence demo-mcp-reset demo-mcp-evidence \
	demo-mcp-scenario-update

init:
	@if [ -e .env ]; then \
		echo '.env already exists; kept unchanged.'; \
	else \
		(umask 077; cp .env.example .env); \
		echo 'Created .env with local development defaults.'; \
	fi

config:
	$(COMPOSE) config --quiet

up: config
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --tail=100 -f

# Unit and route tests; no Docker involved.
test:
	$(MAKE) -C app test

# Unit tests inside the image, including the MCP SDK smoke and the dummy transport tests.
test-mcp:
	$(DEMO_COMPOSE) exec -T gate-mcp python -m unittest discover -s tests -v

# Storage tests against the PostgreSQL inside the running stack.
test-integration:
	$(COMPOSE) exec -T api python -m unittest discover -s tests/integration -v

# End-to-end acceptance through Traefik, including the no-dispatch-after-block invariant.
acceptance:
	./scripts/acceptance.sh

# Optional: drive the console in a real browser over the DevTools Protocol. Needs a local Chrome
# started with --remote-debugging-port=9229; the command explains itself when it is missing.
ui-check:
	node scripts/ui-check.js "$(or $(ORIGIN),http://ai-control-proxy.localhost)" .ui-shots

# Requires a fresh isolated memory backend (see app/README.md), never the live demo database.
control-ui-check:
	node scripts/panel-ui-check.js "$(or $(ORIGIN),http://127.0.0.1:18082)" .ui-shots/control

quality: test ui-check
	@echo 'Offline suites passed. Run `make acceptance` against a running stack for the end-to-end path.'

smoke: test acceptance

# --- MCP demonstration slice -------------------------------------------------------------------
# The whole slice is behind the `demo-mcp` profile: the base stack stays exactly as it was, and an
# unavailable dummy never makes the Gate unready.

# Generate the local Gate to service credentials outside Git.
demo-mcp-secrets:
	./scripts/demo-mcp-secrets.sh

# Bring the profile up and bootstrap it: registry revision, transport principals, panel policy.
demo-mcp-up:
	./scripts/demo-mcp-up.sh

demo-mcp-down:
	$(DEMO_COMPOSE) down

# Registry and panel policy only, without touching the running containers.
demo-mcp-bootstrap:
	$(DEMO_COMPOSE) exec -T gate-mcp python -m action_gate.mcp_bootstrap --apply-panel-policy
	$(DEMO_COMPOSE) exec -T gate-mcp python -m action_gate.mcp_bootstrap --apply-principals

demo-mcp-publish:
	$(DEMO_COMPOSE) exec -T gate-mcp python -m action_gate.mcp_bootstrap --publish

# The single-point policy change used by the demonstration: allow exactly one document to be updated.
demo-mcp-scenario-update:
	$(DEMO_COMPOSE) exec -T gate-mcp python -m action_gate.mcp_bootstrap --scenario update-kb1042

# Scenario client. Examples:
#   make demo-mcp-client ARGS="--principal support-agent tools"
#   make demo-mcp-client ARGS="--principal support-agent scenario"
#   make demo-mcp-client ARGS="--principal support-agent --tool documents_read --args '{\"doc_id\":\"KB-1042\"}'"
demo-mcp-client:
	$(DEMO_COMPOSE) exec -T gate-mcp python -m demo_client $(ARGS)

# Independent evidence: Gate decisions next to the state and receipts of every service.
demo-mcp-inspect:
	./scripts/demo-mcp-inspect.sh

# The acceptance matrix against the running stack; writes an evidence directory per run.
demo-mcp-test:
	./scripts/demo-mcp-test.sh

# Read service receipts for operations with an unknown outcome. Never re-dispatches.
demo-mcp-reconcile:
	$(DEMO_COMPOSE) exec -T gate-mcp python -m action_gate.mcp_ops reconcile

# Operator fence for one operation without a receipt: first inside the service that owns the write
# lock, then recorded at the Gate.
#   make demo-mcp-fence SERVICE=outbox OPERATION_ID=op-...
demo-mcp-fence:
	@test -n "$(SERVICE)" || (echo 'SERVICE is required (documents, outbox or tickets)'; exit 2)
	@test -n "$(OPERATION_ID)" || (echo 'OPERATION_ID is required'; exit 2)
	SERVICE="$(SERVICE)" OPERATION_ID="$(OPERATION_ID)" ./scripts/demo-mcp-fence.sh

# Move Gate and services to a new demonstration run: make demo-mcp-reset DEMO_RUN_ID=run-0002
demo-mcp-reset:
	@test -n "$(DEMO_RUN_ID)" || (echo 'DEMO_RUN_ID is required, for example DEMO_RUN_ID=run-0002'; exit 2)
	./scripts/demo-mcp-reset.sh

demo-mcp-evidence:
	./scripts/demo-mcp-evidence.sh
