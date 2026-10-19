CREATE TABLE IF NOT EXISTS knowledge (
    id text PRIMARY KEY,
    title text NOT NULL,
    section text NOT NULL,
    access text[] NOT NULL,
    owner text NOT NULL,
    updated date NOT NULL,
    version text NOT NULL,
    content text NOT NULL,
    data jsonb NOT NULL,
    search_vector tsvector NOT NULL
);
CREATE INDEX IF NOT EXISTS knowledge_search_idx ON knowledge USING gin(search_vector);
CREATE INDEX IF NOT EXISTS knowledge_access_idx ON knowledge USING gin(access);

CREATE TABLE IF NOT EXISTS runs (
    id uuid PRIMARY KEY,
    agent text NOT NULL,
    person_id text NOT NULL,
    role text NOT NULL,
    status text NOT NULL CHECK (status IN ('running','needs_review','approved','error')),
    input jsonb NOT NULL,
    input_hash text NOT NULL,
    request_id text NOT NULL,
    manifest jsonb NOT NULL,
    steps jsonb NOT NULL DEFAULT '[]',
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    duration_ms integer,
    llm_mode text NOT NULL,
    cost_usd numeric,
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    current_version integer NOT NULL DEFAULT 0,
    UNIQUE(person_id, request_id)
);
CREATE INDEX IF NOT EXISTS runs_person_idx ON runs(person_id, created_at DESC);
CREATE TABLE IF NOT EXISTS run_tokens (
    token_hash text PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(id),
    expires_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS revisions (
    run_id uuid NOT NULL REFERENCES runs(id),
    version integer NOT NULL,
    output jsonb NOT NULL,
    author text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(run_id, version)
);
CREATE TABLE IF NOT EXISTS decisions (
    id bigserial PRIMARY KEY,
    run_id uuid NOT NULL,
    version integer NOT NULL,
    author text NOT NULL,
    note text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(run_id, version),
    FOREIGN KEY(run_id, version) REFERENCES revisions(run_id, version)
);
CREATE TABLE IF NOT EXISTS context_events (
    id bigserial PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(id),
    section text NOT NULL,
    query text NOT NULL,
    records jsonb NOT NULL,
    hidden_count integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS model_calls (
    id bigserial PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(id),
    purpose text NOT NULL,
    mode text NOT NULL,
    model text NOT NULL,
    input_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    cost_usd numeric,
    skill_refs jsonb NOT NULL DEFAULT '[]',
    usage jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'completed',
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE model_calls ADD COLUMN IF NOT EXISTS skill_refs jsonb NOT NULL DEFAULT '[]';
ALTER TABLE model_calls ADD COLUMN IF NOT EXISTS usage jsonb NOT NULL DEFAULT '{}';
ALTER TABLE model_calls ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'completed';
CREATE TABLE IF NOT EXISTS learnings (
    id bigserial PRIMARY KEY,
    run_id uuid NOT NULL,
    version integer NOT NULL,
    text text NOT NULL,
    author text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(run_id, version) REFERENCES revisions(run_id, version)
);
