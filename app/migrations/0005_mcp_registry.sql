-- Registry of published MCP connections and tool mappings.
--
-- A revision is an immutable snapshot: the allowlisted connection, the discovered upstream tools,
-- the full JSON Schemas and their hashes, and the operator-reviewed description of every published
-- tool. Publishing a revision is an explicit operator action; a drift blocks new calls to the
-- affected tool until it is reviewed, and it never rewrites a published revision in place.
CREATE TABLE IF NOT EXISTS mcp_registry_revisions (
    revision bigint PRIMARY KEY,
    document_hash text NOT NULL,
    document jsonb NOT NULL,
    source text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    active boolean NOT NULL DEFAULT false
);

-- Only one revision may be active. Partial unique index: no silent "latest wins" semantics.
CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_registry_single_active
    ON mcp_registry_revisions (active) WHERE active;

CREATE TABLE IF NOT EXISTS mcp_service_health (
    service_id text PRIMARY KEY,
    connection_ref text NOT NULL,
    status text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    checked_at timestamptz NOT NULL DEFAULT now()
);
