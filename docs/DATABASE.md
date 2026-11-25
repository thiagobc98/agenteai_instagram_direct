# Banco de Dados

Este documento explica as tabelas do projeto e traz queries de inspeção
para validação operacional (fila, conversa e memória semântica via tools).

## Visão Geral

O PostgreSQL guarda três blocos de dados:

1. Tabelas de aplicação (`message_queue`, `conversations`, `appointment_reminders`, `_migrations`)
2. Tabelas de checkpointer do LangGraph (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`, `checkpoint_migrations`)
3. Tabelas de memória semântica (`store`, `store_vectors`, `store_migrations`, `vector_migrations`)

## Tabelas de Aplicação

### `_migrations`

Controle das migrações SQL locais (`db/migrations/*.sql`).

### `message_queue`

Fila operacional de mensagens.

Campos principais:
- `message_id`: id externo da mensagem (`mid` do Instagram)
- `external_id`: IGSID do contato no Instagram (antes `phone_number`, ver migration `006`)
- `to_id`: ID da conta destinatária (opcional; antes `to_number`)
- `channel`: `instagram` (novas linhas) ou `whatsapp` (histórico anterior à migração)
- `agent_id`, `thread_id` (`{external_id}:{agent_id}`)
- `incoming_message`: entrada original
- `media_url`, `media_type`: anexo do Instagram — `media_url` é a URL que o Worker baixa e `media_type` o tipo genérico (`image/*`, `audio/*`) ou `unsupported/<tipo>`
- `media_base64`: só em dados históricos (o Instagram não entrega base64)
- `normalized_input`: texto final enviado ao agente (quando houver)
- `media_processing_status`: `none | processed | disabled | failed | unsupported`
- `media_processing_error`: erro de pré-processamento de mídia
- `status`: `queued | processing | done | failed`
- `response`, `error`, `attempts`, `max_attempts`, `process_after`

### `conversations`

Resumo por conversa (`external_id + agent_id`) para o painel/admin. Tem também `channel`.

### `contacts`

Perfil público de cada cliente do Instagram (`external_id`, `username`, `name`,
`profile_pic_url`, `fetched_at`), criado pela migration `007`. O webhook só traz o
IGSID; o Worker consulta a User Profile API na primeira mensagem do contato (e renova
a cada 7 dias) para o painel mostrar o `@` em vez do número. Falha na consulta nunca
interrompe o atendimento (best-effort). O dashboard (`GET /api/dashboard`,
`shared/analytics.py`) lê `message_queue` + `contacts`.

### `appointment_reminders`

Lembretes de consulta já enviados (`event_id`, `external_id`, `appointment_start`). Sem uso desde a remoção dos lembretes automáticos; a tabela fica só por histórico de migrations.

## Tabelas do LangGraph

### `checkpoints`

Snapshots do estado por `thread_id`.

### `checkpoint_writes`

Eventos incrementais por canal (inclui canal `messages`).
O payload fica em `blob` (msgpack).

### `checkpoint_blobs`

Blobs auxiliares do checkpointer.

### `checkpoint_migrations`

Controle interno de schema do checkpointer.

## Tabelas de Memória Semântica

### `store`

Memórias em JSON por namespace/prefix.
Para este projeto, padrão:
- `prefix = "<user_id>.memories"`
- sem namespaces de tenant (`tenant_user`/`tenant_shared`)

### `store_vectors`

Embeddings vetoriais da `store` (HNSW + `vector`).

### `store_migrations` e `vector_migrations`

Controle interno de schema da store vetorial.

## Queries Prontas

### 1) Quais formatos de mídia chegaram

```sql
SELECT media_type, COUNT(*) AS total
FROM message_queue
WHERE media_type IS NOT NULL
GROUP BY media_type
ORDER BY total DESC;
```

### 2) Histórico completo de uma conversa (fila + resposta)

```sql
SELECT
  id,
  message_id,
  external_id,
  media_type,
  media_processing_status,
  status,
  incoming_message,
  normalized_input,
  response,
  media_processing_error,
  error,
  created_at,
  processed_at
FROM message_queue
WHERE external_id = '17841400000000001'
ORDER BY id DESC;
```

### 3) Memórias salvas de um usuário

```sql
SELECT
  prefix,
  key,
  value->>'memory' AS memory,
  created_at
FROM store
WHERE prefix = '17841400000000001.memories'
ORDER BY created_at DESC;
```

### 4) Evidência de save no store (memória durável por usuário)

```sql
SELECT
  prefix,
  key,
  value->>'memory' AS memory,
  updated_at
FROM store
WHERE prefix = '17841400000000001.memories'
ORDER BY updated_at DESC
LIMIT 20;
```

### 5) Evidência de recall no output (resposta final ao usuário)

```sql
SELECT
  id,
  message_id,
  external_id,
  status,
  left(response, 220) AS response_preview,
  created_at
FROM message_queue
WHERE external_id = '17841400000000001'
  AND status = 'done'
ORDER BY id DESC
LIMIT 20;
```

### 6) Inspeção técnica das mensagens persistidas no checkpoint

```sql
SELECT
  checkpoint_id,
  channel,
  type,
  octet_length(blob) AS bytes,
  left(encode(blob, 'escape'), 600) AS blob_preview
FROM checkpoint_writes
WHERE thread_id = '17841400000000001:secretaria'
  AND channel = 'messages'
ORDER BY checkpoint_id DESC
LIMIT 20;
```

### 7) Conversas mais recentes (visão painel)

```sql
SELECT
  external_id,
  agent_id,
  thread_id,
  last_message,
  last_message_at,
  message_count
FROM conversations
ORDER BY last_message_at DESC
LIMIT 50;
```

### 8) Última mensagem recebida de um contato (janela de 24h)

```sql
SELECT external_id, MAX(created_at) AS ultima_mensagem
FROM message_queue
WHERE external_id = '17841400000000001'
GROUP BY external_id;
```

O Instagram só permite enviar mensagem dentro de 24h dessa data
(ver [INSTAGRAM_API.md](INSTAGRAM_API.md)).

## Observações

- `conversations` mostra apenas resumo; não mostra detalhes de save/recall.
- Save de memória é observado em `store` (`prefix = "<user_id>.memories"`).
- Recall é observado no output final (`message_queue.response`) e nos logs do worker (`memory_read`).
- Linhas com `channel = 'whatsapp'` são histórico da versão anterior (WhatsApp); o `external_id`
  delas é um telefone E.164, não um IGSID.
- `message_queue.status='done'` significa ciclo encerrado com resposta ao usuário,
  inclusive respostas automáticas quando mídia está desabilitada ou falha.
