-- 012_attendant_notifications.sql
-- Avisos no WhatsApp do atendente a cada mensagem recebida no Direct, enviados
-- por um número conectado ao Wuzapi (tela "WhatsApp" do painel).
--
-- O webhook do Instagram grava um aviso por mensagem (fila "outbox"); o Worker
-- envia em segundo plano, com novas tentativas. Assim o aviso nunca atrasa nem
-- derruba a resposta à cliente, e nada se perde se o WhatsApp cair.
--
-- Fluxo de status de `attendant_notifications.status`:
--   pending  -> aguardando envio. `next_attempt_at` também faz o "debounce":
--               mensagens seguidas da mesma cliente saem juntas em um aviso
--   sending  -> Worker enviando (`next_attempt_at` vira o lease)
--   sent     -> entregue ao Wuzapi
--   failed   -> desistiu depois das tentativas (ver `error`)
--   skipped  -> não enviado: avisos desligados, sem destinatário ou antigo demais
--
-- Ver `shared/attendant_notify.py` e `worker/notifier.py`.

CREATE TABLE IF NOT EXISTS attendant_notify_settings (
    id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    -- Celulares que recebem os avisos (só dígitos, com 55)
    recipients  TEXT[] NOT NULL DEFAULT '{}',
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO attendant_notify_settings (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS attendant_notifications (
    id                BIGSERIAL PRIMARY KEY,
    external_id       TEXT NOT NULL,
    -- mid da mensagem do Instagram: a Meta reenvia webhooks, o aviso não
    source_message_id TEXT UNIQUE,
    body              TEXT NOT NULL DEFAULT '',
    media_type        TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',
    attempts          INTEGER NOT NULL DEFAULT 0,
    next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error             TEXT,
    sent_at           TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attendant_notifications_due
    ON attendant_notifications (next_attempt_at)
    WHERE status IN ('pending', 'sending');

CREATE INDEX IF NOT EXISTS idx_attendant_notifications_recent
    ON attendant_notifications (created_at DESC);
