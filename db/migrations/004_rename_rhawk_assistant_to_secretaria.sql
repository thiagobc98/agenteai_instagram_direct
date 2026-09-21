-- 004_rename_rhawk_assistant_to_secretaria.sql
-- Renomeia o agente rhawk_assistant para secretaria.
--
-- O diretório do agente (agents/catalog/rhawk_assistant) foi renomeado
-- para agents/catalog/secretaria. Esta migração atualiza os registros
-- existentes que ainda referenciam o agent_id antigo: nas tabelas de
-- aplicação (message_queue, conversations) e nas tabelas do checkpointer
-- do LangGraph, cujo thread_id segue o formato "{phone_number}:{agent_id}".
--
-- As tabelas do checkpointer (checkpoints, checkpoint_writes,
-- checkpoint_blobs) só existem depois que a API/Worker sobe pelo menos
-- uma vez (checkpointer.setup()); por isso os UPDATEs nelas são
-- condicionais, para não quebrar em bancos novos onde ainda não existem.

UPDATE message_queue
SET agent_id = 'secretaria',
    thread_id = regexp_replace(thread_id, ':rhawk_assistant$', ':secretaria')
WHERE agent_id = 'rhawk_assistant';

UPDATE conversations
SET agent_id = 'secretaria',
    thread_id = regexp_replace(thread_id, ':rhawk_assistant$', ':secretaria')
WHERE agent_id = 'rhawk_assistant';

DO $$
BEGIN
    IF to_regclass('public.checkpoints') IS NOT NULL THEN
        UPDATE checkpoints
        SET thread_id = regexp_replace(thread_id, ':rhawk_assistant$', ':secretaria')
        WHERE thread_id LIKE '%:rhawk_assistant';
    END IF;

    IF to_regclass('public.checkpoint_writes') IS NOT NULL THEN
        UPDATE checkpoint_writes
        SET thread_id = regexp_replace(thread_id, ':rhawk_assistant$', ':secretaria')
        WHERE thread_id LIKE '%:rhawk_assistant';
    END IF;

    IF to_regclass('public.checkpoint_blobs') IS NOT NULL THEN
        UPDATE checkpoint_blobs
        SET thread_id = regexp_replace(thread_id, ':rhawk_assistant$', ':secretaria')
        WHERE thread_id LIKE '%:rhawk_assistant';
    END IF;
END $$;
