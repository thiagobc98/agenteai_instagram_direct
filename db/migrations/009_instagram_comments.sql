-- 009_instagram_comments.sql
-- Comentários das postagens do Instagram, com rascunho de resposta da IA
-- aguardando aprovação no painel.
--
-- Fluxo de status de `ig_comments.status`:
--   new       -> comentário recebido (webhook `comments` ou sincronização),
--                aguardando o Worker gerar o rascunho. Aqui `lease_until` é o
--                "não tentar antes de" do backoff entre tentativas.
--   drafting  -> Worker gerando o rascunho (lease em `lease_until`)
--   pending   -> rascunho pronto, aguardando aprovação no painel
--   sending   -> aprovado, publicando a resposta (evita publicar em dobro)
--   sent      -> resposta publicada (pública e, se houver, privada no Direct)
--   ignored   -> descartado no painel (ou comentário da própria conta)
--   failed    -> falha ao gerar o rascunho ou ao publicar (ver `error`)
--   archived  -> comentário antigo importado na sincronização (sem rascunho)
--
-- Ver `shared/comments.py` (acesso ao banco) e `agents/comments/` (rascunho).

CREATE TABLE IF NOT EXISTS ig_posts (
    media_id        TEXT PRIMARY KEY,
    caption         TEXT,
    media_type      TEXT,
    media_url       TEXT,
    thumbnail_url   TEXT,
    permalink       TEXT,
    posted_at       TIMESTAMPTZ,
    comments_count  INTEGER,
    synced_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ig_comments (
    comment_id          TEXT PRIMARY KEY,
    media_id            TEXT NOT NULL,
    parent_id           TEXT,
    from_id             TEXT,
    from_username       TEXT,
    text                TEXT NOT NULL DEFAULT '',
    commented_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status              TEXT NOT NULL DEFAULT 'new',
    draft_public        TEXT,
    draft_private       TEXT,
    ai_suggests_ignore  BOOLEAN NOT NULL DEFAULT FALSE,
    ai_reason           TEXT,
    reply_public_id     TEXT,
    reply_public_text   TEXT,
    reply_private_id    TEXT,
    reply_private_text  TEXT,
    private_error       TEXT,
    error               TEXT,
    attempts            INTEGER NOT NULL DEFAULT 0,
    lease_until         TIMESTAMPTZ,
    sent_at             TIMESTAMPTZ,
    -- Usuário do painel que aprovou a resposta (auditoria: é público, em nome da marca)
    approved_by         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ig_comments_media
    ON ig_comments (media_id, commented_at DESC);
CREATE INDEX IF NOT EXISTS idx_ig_comments_status
    ON ig_comments (status, commented_at);
