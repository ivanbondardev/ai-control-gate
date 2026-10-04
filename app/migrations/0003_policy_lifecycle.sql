-- Action Gate 0.2.0 — policy lifecycle, principal-scoped replay, budget provenance.
--
-- Applied by `python -m action_gate.migrate`; already-applied files are never edited.
-- Nothing here is derived from Redis: the active release, its history, the ledger and the claims
-- live only in PostgreSQL. Files remain a bootstrap and import format.

-- 1. An idempotency key belongs to one principal, not to the whole deployment. The old table
--    allowed a global key, so one caller could observe or block another caller's replay.
ALTER TABLE invocation_claim ADD COLUMN IF NOT EXISTS principal_id text;
-- Pre-existing claims keep a NULL owner: the owner of a completed claim can be recovered from the
-- invocation row, but a claim with no trustworthy owner must never be replayed automatically.
UPDATE invocation_claim c
   SET principal_id = i.principal_id
  FROM invocation i
 WHERE c.principal_id IS NULL AND i.idempotency_key = c.idempotency_key;
ALTER TABLE invocation_claim DROP CONSTRAINT IF EXISTS invocation_claim_pkey;
DROP INDEX IF EXISTS invocation_claim_idempotency_key_key;
ALTER TABLE invocation_claim ALTER COLUMN idempotency_key SET NOT NULL;
-- COALESCE keeps legacy unowned rows unique under the new key instead of colliding on NULL.
CREATE UNIQUE INDEX IF NOT EXISTS invocation_claim_principal_key_idx
    ON invocation_claim (COALESCE(principal_id, ''), idempotency_key);
CREATE INDEX IF NOT EXISTS invocation_claim_invocation_idx ON invocation_claim (invocation_id);

-- 2. A release is only reconstructible if the full document set is stored with it.
ALTER TABLE config_release ADD COLUMN IF NOT EXISTS snapshot jsonb;
ALTER TABLE config_release ADD COLUMN IF NOT EXISTS schema_version text;
ALTER TABLE config_release ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'files';
ALTER TABLE config_release ADD COLUMN IF NOT EXISTS created_by text;
ALTER TABLE config_release ADD COLUMN IF NOT EXISTS activation_generation integer;

-- 3. Drafts are editable documents plus a revision that an update must match.
CREATE TABLE IF NOT EXISTS config_draft (
    draft_id       uuid PRIMARY KEY,
    base_release   text NOT NULL,
    revision       integer NOT NULL DEFAULT 1,
    documents      jsonb NOT NULL,
    source         text NOT NULL DEFAULT 'api',
    created_by     text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- 4. Exactly one active release per environment, with a monotonic generation.
CREATE TABLE IF NOT EXISTS config_active (
    environment   text PRIMARY KEY,
    release_hash  text NOT NULL,
    generation    bigint NOT NULL DEFAULT 1,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS config_activation (
    activation_id  uuid PRIMARY KEY,
    environment    text NOT NULL,
    previous_hash  text,
    next_hash      text NOT NULL,
    generation     bigint NOT NULL,
    actor          text NOT NULL,
    reason         text,
    kind           text NOT NULL DEFAULT 'activation',
    operation_key  text,
    request_hash   text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS config_activation_created_idx ON config_activation (created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS config_activation_operation_idx
    ON config_activation (environment, operation_key) WHERE operation_key IS NOT NULL;

-- 5. A compare run is stored so an activation can prove which comparison it relied on. Only
--    cleared summaries are stored: no raw ad-hoc case text.
CREATE TABLE IF NOT EXISTS config_evaluation (
    evaluation_id     uuid PRIMARY KEY,
    environment       text NOT NULL,
    active_hash       text NOT NULL,
    active_generation bigint NOT NULL,
    candidate_hash    text NOT NULL,
    candidate_revision integer,
    dataset_hash      text,
    detector_profile  text NOT NULL,
    detector_identity jsonb NOT NULL DEFAULT '{}'::jsonb,
    instruction_version integer,
    mode              text NOT NULL DEFAULT 'full',
    status            text NOT NULL,
    passed            boolean NOT NULL DEFAULT false,
    model_calls       integer NOT NULL DEFAULT 0,
    case_count        integer NOT NULL DEFAULT 0,
    summary           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by        text,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS config_evaluation_candidate_idx
    ON config_evaluation (environment, candidate_hash, created_at DESC);

-- 6. Budget provenance: a charge must be attributable to the release and generation that
--    admitted it, and to the pricing identity that priced it.
ALTER TABLE budget_reservation ADD COLUMN IF NOT EXISTS release_hash text;
ALTER TABLE budget_reservation ADD COLUMN IF NOT EXISTS activation_generation bigint;
ALTER TABLE budget_reservation ADD COLUMN IF NOT EXISTS pricing_identity text;
ALTER TABLE budget_reservation ADD COLUMN IF NOT EXISTS principal_id text;
ALTER TABLE budget_reservation ADD COLUMN IF NOT EXISTS invocation_id uuid;
ALTER TABLE budget_ledger ADD COLUMN IF NOT EXISTS generation bigint;

-- 7. Reporting: one stable, filterable listing with a cursor over (created_at, id).
CREATE INDEX IF NOT EXISTS invocation_principal_idx ON invocation (principal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS invocation_outcome_idx ON invocation (action_outcome);
