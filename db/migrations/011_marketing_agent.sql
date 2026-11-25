-- 011_marketing_agent.sql
-- Agente de marketing (estrategista de conteúdo e crescimento) do painel.
--
-- 1. Conversas da equipe com o agente (`marketing_threads` e
--    `marketing_messages`). O histórico é guardado aqui, só em texto: a cada
--    pergunta o agente recebe as últimas mensagens, e os dados vêm sempre
--    atualizados pelas ferramentas (não do histórico).
-- 2. Rascunhos de publicação sugeridos pelo agente: `ig_publications` ganha
--    a origem, o horário sugerido e a justificativa da sugestão. A equipe
--    sobe a mídia e aprova na tela Publicar, como qualquer rascunho.

ALTER TABLE ig_publications
    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS planned_for TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rationale TEXT;

CREATE TABLE IF NOT EXISTS marketing_threads (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT 'Nova conversa',
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS marketing_messages (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   BIGINT NOT NULL REFERENCES marketing_threads(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    -- Ferramentas usadas e rascunhos criados nesta resposta (para o painel)
    actions     JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_marketing_messages_thread
    ON marketing_messages (thread_id, id);
