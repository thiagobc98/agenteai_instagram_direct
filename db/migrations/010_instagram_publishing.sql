-- 010_instagram_publishing.sql
-- Publicações criadas pelo painel (Feed, Story, Reels) e publicadas pelo
-- Worker via Instagram Content Publishing API.
--
-- Ciclo de `ig_publications.status`:
--   draft       -> rascunho no painel (mídia, briefing, legenda editável)
--   scheduled   -> aprovado; o Worker publica quando `publish_at` chegar
--   processing  -> container criado na Meta (`container_id`), aguardando a
--                  Meta terminar de processar a mídia (vídeo demora)
--   publishing  -> chamando media_publish (estado curto; se o processo cair
--                  aqui, o Worker confere o container antes de tentar de novo,
--                  para não publicar em dobro)
--   published   -> no ar (`ig_media_id`, `permalink`)
--   failed      -> erro (ver `error`); o painel pode reagendar
--   canceled    -> descartado no painel
--
-- A mídia fica no disco da API (MEDIA_STORAGE_DIR) e é servida sem login em
-- /media/<token> (token aleatório), porque a Meta baixa a mídia por URL.
-- Ver `shared/publishing.py`, `worker/publisher.py` e `agents/captions/`.

CREATE TABLE IF NOT EXISTS ig_publications (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('feed', 'story', 'reels')),
    status          TEXT NOT NULL DEFAULT 'draft',
    brief           TEXT NOT NULL DEFAULT '',
    caption         TEXT NOT NULL DEFAULT '',
    -- Legenda como a IA entregou (para comparar com a versão final editada)
    ai_caption      TEXT,
    share_to_feed   BOOLEAN NOT NULL DEFAULT TRUE,
    publish_at      TIMESTAMPTZ,
    container_id    TEXT,
    container_created_at TIMESTAMPTZ,
    ig_media_id     TEXT,
    permalink       TEXT,
    error           TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    lease_until     TIMESTAMPTZ,
    created_by      TEXT,
    approved_by     TEXT,
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ig_publications_due
    ON ig_publications (status, publish_at);

CREATE TABLE IF NOT EXISTS ig_publication_media (
    id              BIGSERIAL PRIMARY KEY,
    publication_id  BIGINT NOT NULL REFERENCES ig_publications(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL DEFAULT 0,
    -- Nome público do arquivo (/media/<token>), aleatório e não adivinhável
    token           TEXT NOT NULL UNIQUE,
    media_kind      TEXT NOT NULL CHECK (media_kind IN ('image', 'video')),
    content_type    TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    width           INTEGER,
    height          INTEGER,
    duration_seconds REAL,
    original_name   TEXT,
    -- Descrição da imagem feita pelo modelo de visão (cache para a legenda)
    ai_description  TEXT,
    -- Container do item no carrossel (criado pelo Worker)
    container_id    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ig_publication_media_pub
    ON ig_publication_media (publication_id, position);
