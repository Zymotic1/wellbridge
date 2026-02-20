-- ==============================================================================
-- 0004: Chat sessions and messages
-- Stores conversation history. jargon_map is stored alongside each assistant
-- message for replay (so the hover feature works on historical messages).
-- ==============================================================================

CREATE TABLE IF NOT EXISTS chat_sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id      TEXT NOT NULL,
    title        TEXT,                     -- Auto-generated from first message
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sessions_tenant_user ON chat_sessions(tenant_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content      TEXT NOT NULL,
    -- Agent metadata (not shown to user, used for audit and replay)
    intent       TEXT,                     -- Classified intent for this exchange
    jargon_map   JSONB NOT NULL DEFAULT '[]',  -- Stored for history replay
    guardrail_triggered BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON chat_messages(session_id, created_at ASC);

-- Audit log for guardrail violations
CREATE TABLE IF NOT EXISTS guardrail_violations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id),
    user_id      TEXT NOT NULL,
    session_id   UUID REFERENCES chat_sessions(id),
    raw_response TEXT NOT NULL,            -- The flagged LLM output (for review)
    pattern_matched TEXT NOT NULL,         -- Which regex pattern fired
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE chat_sessions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages  ENABLE ROW LEVEL SECURITY;
ALTER TABLE guardrail_violations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "sessions_isolation" ON chat_sessions
    FOR ALL
    USING (
        tenant_id = current_tenant_id()
        AND user_id = current_user_id()
    );

CREATE POLICY "messages_isolation" ON chat_messages
    FOR ALL
    USING (
        tenant_id = current_tenant_id()
        AND session_id IN (
            SELECT id FROM chat_sessions
            WHERE user_id = current_user_id()
              AND tenant_id = current_tenant_id()
        )
    );

-- Only backend service role can insert violations; users can read their own
CREATE POLICY "violations_user_read" ON guardrail_violations
    FOR SELECT
    USING (
        tenant_id = current_tenant_id()
        AND user_id = current_user_id()
    );
