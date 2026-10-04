-- Action Gate 0.1.0 — second migration: atomic idempotency claims and honest budget accounting.
--
-- 1. invocation_claim makes the idempotency key a claim taken BEFORE any paid or irreversible work.
--    The unique constraint is the lock: exactly one caller can insert the row.
-- 2. budget_ledger.overdraft_tokens keeps a charge that exceeded its reservation from silently
--    pushing `remaining` negative: the limit stays meaningful and the excess stays visible.
-- 3. invocation.budget_scope records which ledger actually paid for the call.

CREATE TABLE IF NOT EXISTS invocation_claim (
    idempotency_key text PRIMARY KEY,
    invocation_id   uuid NOT NULL,
    request_hash    text NOT NULL,
    state           text NOT NULL DEFAULT 'in_flight'
                    CHECK (state IN ('in_flight', 'completed', 'unknown')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS invocation_claim_state_idx ON invocation_claim (state, updated_at);

ALTER TABLE budget_ledger
    ADD COLUMN IF NOT EXISTS overdraft_tokens bigint NOT NULL DEFAULT 0;

ALTER TABLE invocation
    ADD COLUMN IF NOT EXISTS budget_scope text NOT NULL DEFAULT '';
