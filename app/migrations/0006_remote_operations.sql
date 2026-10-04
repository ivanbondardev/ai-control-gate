-- Durable remote execution: one row per logical client operation.
--
-- The Gate keeps the identity of the request, the decision, the effect outcome, the downstream
-- operation id and the sanitized result. It deliberately does NOT keep the raw request payload:
-- after a restart nothing is re-sent, and reconciliation uses the receipt at the service, not a
-- stored copy of the arguments.
CREATE TABLE IF NOT EXISTS mcp_operations (
    id uuid PRIMARY KEY,
    demo_run_id text NOT NULL,
    principal_id text NOT NULL,
    client_operation_key text NOT NULL,
    request_fingerprint text NOT NULL,
    request_id text,
    published_tool text NOT NULL,
    upstream_tool text NOT NULL,
    service_id text NOT NULL,
    panel_service text NOT NULL,
    panel_action text NOT NULL,
    registry_revision bigint NOT NULL,
    policy_version integer NOT NULL,
    policy_hash text NOT NULL,
    status text NOT NULL,
    decision text NOT NULL,
    reason text,
    disclosure text NOT NULL DEFAULT 'none',
    attempts integer NOT NULL DEFAULT 0,
    upstream_operation_id text,
    receipt_id text,
    resource_id text,
    before_version integer,
    after_version integer,
    result_document jsonb,
    error_code text,
    bytes_in integer NOT NULL DEFAULT 0,
    bytes_out integer NOT NULL DEFAULT 0,
    admission_ms numeric(12,3),
    upstream_ms numeric(12,3),
    output_ms numeric(12,3),
    total_ms numeric(12,3),
    owner_lease text,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    dispatch_started_at timestamptz,
    finished_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT mcp_operations_client_key UNIQUE (demo_run_id, principal_id, client_operation_key)
);

CREATE INDEX IF NOT EXISTS idx_mcp_operations_status ON mcp_operations (status);
CREATE INDEX IF NOT EXISTS idx_mcp_operations_run ON mcp_operations (demo_run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_operations_principal
    ON mcp_operations (principal_id, created_at DESC);

-- Rate accounting counts every attempt, including refused ones. A replay of a completed claim never
-- inserts a new attempt and therefore never charges the upstream a second time.
CREATE TABLE IF NOT EXISTS mcp_attempts (
    id bigserial PRIMARY KEY,
    operation_id uuid,
    demo_run_id text NOT NULL,
    principal_id text NOT NULL,
    service_id text NOT NULL,
    published_tool text NOT NULL,
    outcome text NOT NULL,
    admitted boolean NOT NULL DEFAULT false,
    at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mcp_attempts_principal_at ON mcp_attempts (principal_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_attempts_run ON mcp_attempts (demo_run_id, at DESC);

-- Sanitized audit trail. Content is never stored here: only decisions, typed reasons, identifiers
-- and durations.
CREATE TABLE IF NOT EXISTS mcp_audit_events (
    id bigserial PRIMARY KEY,
    at timestamptz NOT NULL DEFAULT now(),
    operation_id uuid,
    demo_run_id text NOT NULL,
    principal_id text NOT NULL,
    published_tool text NOT NULL,
    upstream_tool text NOT NULL,
    service_id text NOT NULL,
    policy_version integer NOT NULL,
    policy_hash text NOT NULL,
    registry_revision bigint NOT NULL,
    decision text NOT NULL,
    reason text,
    effect_outcome text NOT NULL,
    disclosure text NOT NULL,
    receipt_id text,
    request_id text,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_mcp_audit_run ON mcp_audit_events (demo_run_id, at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_audit_operation ON mcp_audit_events (operation_id);

-- Concurrency reservation. Held from admission until a confirmed terminal outcome; an unknown
-- outcome keeps its reservation until reconciliation or an operator fence releases it.
CREATE TABLE IF NOT EXISTS mcp_limit_reservations (
    operation_id uuid PRIMARY KEY,
    service_id text NOT NULL,
    demo_run_id text NOT NULL,
    principal_id text NOT NULL,
    acquired_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,
    release_reason text
);

CREATE INDEX IF NOT EXISTS idx_mcp_reservations_open
    ON mcp_limit_reservations (service_id) WHERE released_at IS NULL;

-- The Gate and every dummy service must agree on one demonstration run id. A reset closes
-- admission first, reconciles unfinished operations, then moves Gate and services to the same new
-- run. Closing admission is an explicit operator state, never a side effect of a restart.
CREATE TABLE IF NOT EXISTS demo_run_state (
    id text PRIMARY KEY,
    run_id text NOT NULL,
    admission_open boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now(),
    note text
);

INSERT INTO demo_run_state (id, run_id, admission_open, note)
VALUES ('default', 'run-0001', true, 'initial bootstrap')
ON CONFLICT (id) DO NOTHING;

