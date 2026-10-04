-- The original visual policy schema has its own explicit runtime contract (/v1/panel).
-- A locked state row serializes policy activation, budget admission and synthetic effects.
-- This is a bounded local demonstration architecture, not a scalable production event store.
CREATE TABLE IF NOT EXISTS control_panel_state (
    id text PRIMARY KEY,
    revision bigint NOT NULL,
    state jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
