-- 003_evolution_media.sql
-- Suporte a mídia via Evolution API: o webhook entrega o conteúdo já em
-- base64 (webhookBase64=true na instância), em vez de uma URL para
-- download posterior (modelo usado pelo Twilio).
--
-- media_url é mantido por compatibilidade com dados históricos; novas
-- mensagens com mídia preenchem media_base64.

ALTER TABLE message_queue
    ADD COLUMN IF NOT EXISTS media_base64 TEXT;
