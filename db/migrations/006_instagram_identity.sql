-- 006_instagram_identity.sql
-- Generaliza a identidade do contato: o telefone (E.164) do WhatsApp dá lugar
-- a um identificador neutro (`external_id`), que passa a guardar o IGSID do
-- Instagram (ID da conta do cliente no escopo do app).
--
-- - Renomeia as colunas em vez de recriar, preservando os dados existentes.
-- - Adiciona `channel` para distinguir a origem: linhas já existentes são
--   marcadas como 'whatsapp' (histórico); novas linhas nascem 'instagram'.
-- - thread_id continua "{external_id}:{agent_id}". Os checkpoints e memórias
--   antigos (thread_id/namespace com o telefone) ficam intactos e não colidem
--   com IGSIDs (numéricos, sem "+"); os contatos do Instagram começam com
--   histórico novo.

-- Fila de mensagens
ALTER TABLE message_queue RENAME COLUMN phone_number TO external_id;
ALTER TABLE message_queue RENAME COLUMN to_number TO to_id;

ALTER TABLE message_queue
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp';
ALTER TABLE message_queue ALTER COLUMN channel SET DEFAULT 'instagram';

ALTER INDEX idx_queue_phone_agent RENAME TO idx_queue_external_agent;

-- Janela de 24h do Instagram: busca a última mensagem recebida de um contato.
CREATE INDEX IF NOT EXISTS idx_queue_external_created
    ON message_queue (external_id, created_at DESC);

-- Conversas
ALTER TABLE conversations RENAME COLUMN phone_number TO external_id;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'whatsapp';
ALTER TABLE conversations ALTER COLUMN channel SET DEFAULT 'instagram';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'conversations_phone_number_agent_id_key'
    ) THEN
        ALTER TABLE conversations
            RENAME CONSTRAINT conversations_phone_number_agent_id_key
            TO conversations_external_id_agent_id_key;
    END IF;
END $$;

-- Lembretes de consulta
ALTER TABLE appointment_reminders RENAME COLUMN phone_number TO external_id;
