# Guia: Testando e Debugando o Sistema Manualmente

Este guia ensina como simular mensagens do Instagram Direct (com o script
`scripts/simulate_instagram_webhook.py`) e depois verificar o resultado
diretamente no banco de dados. O Swagger (`/docs`) continua útil para as rotas
`/api/*`, mas não para o webhook — ele exige assinatura HMAC.

## Passo 0: Subir a Stack

```bash
make up
```

Aguarde todos os serviços ficarem saudáveis:

```bash
curl http://localhost:8000/health
# {"status":"ok","database":"connected","version":"0.1.0"}
```

---

## Passo 1: Abrir o Swagger UI

Acesse no navegador:

```
http://localhost:8000/docs
```

Você verá os endpoints documentados. Para enviar mensagens ao webhook, use o script do próximo passo.

---

## Passo 2: Enviar uma Mensagem via Webhook

O webhook `POST /webhook/instagram` só aceita requisições assinadas com o
`INSTAGRAM_APP_SECRET` (header `X-Hub-Signature-256`). O script monta o
payload como a Meta faz, assina e envia:

```bash
python scripts/simulate_instagram_webhook.py "Olá! O que vocês fazem?" \
  --external-id 17841400000000101
```

A resposta deve ser **200**:

```json
{"received": true, "enqueued": 1}
```

> O 200 significa apenas que a mensagem foi **enfileirada**. O processamento
> acontece no Worker em background. Como o `external_id` é fictício, o envio da
> resposta ao Instagram falha e a mensagem entra em retry (`attempts`,
> `error`) — o que já permite ver o fluxo. Para ver a resposta chegar de
> verdade, use o IGSID de uma conta real de teste.

Para descobrir o `message_id` (`mid`) gerado, consulte pelo `external_id`:

```sql
SELECT id, message_id, status FROM message_queue
WHERE external_id = '17841400000000101' ORDER BY id DESC;
```

---

## Passo 3: Verificar no Banco de Dados

Conecte ao PostgreSQL:

```bash
docker compose exec db psql -U postgres -d whatsapp_langchain
```

### 3.1 — Ver a mensagem na fila

```sql
SELECT id, external_id, agent_id, status, incoming_message, response, error
FROM message_queue
WHERE external_id = '17841400000000101'
ORDER BY id DESC;
```

**O que observar:**

| `status` | Significado |
|---|---|
| `queued` | Na fila, aguardando o Worker |
| `processing` | Worker pegou, está processando |
| `done` | Processado com sucesso — `response` tem a resposta da IA |
| `failed` | Erro — `error` tem o motivo |

> Rode a query mais de uma vez para acompanhar a transição de status em tempo real.

### 3.2 — Ver a resposta da IA

```sql
SELECT incoming_message, response, processed_at
FROM message_queue
WHERE external_id = '17841400000000101' AND status = 'done';
```

### 3.3 — Ver a conversa criada

```sql
SELECT external_id, agent_id, message_count, last_message, last_message_at
FROM conversations
WHERE external_id = '17841400000000101';
```

`message_count` incrementa a cada mensagem processada.

---

## Passo 4: Enviar Follow-up (Conversa Multi-turno)

Envie outra mensagem do **mesmo contato** (mesmo `--external-id`):

```bash
python scripts/simulate_instagram_webhook.py "Como posso aprender mais sobre agentes?" \
  --external-id 17841400000000101
```

Depois verifique:

```sql
-- A resposta deve considerar o contexto da conversa anterior
SELECT incoming_message, response
FROM message_queue
WHERE external_id = '17841400000000101' AND status = 'done'
ORDER BY created_at;

-- message_count deve ter incrementado para 2
SELECT message_count FROM conversations WHERE external_id = '17841400000000101';
```

---

## Passo 5: Testar o Debounce

Envie **3 mensagens rápidas** (uma atrás da outra, sem esperar) do mesmo
contato (`17841400000000102`):

```bash
for t in "Oi" "Tudo bem?" "Quero saber sobre LangGraph"; do
  python scripts/simulate_instagram_webhook.py "$t" --external-id 17841400000000102
done
```

Depois verifique:

```sql
-- Quantas entradas na fila? Se o debounce funcionou, deve ser 1 (não 3)
SELECT COUNT(*) FROM message_queue
WHERE external_id = '17841400000000102' AND agent_id = 'secretaria';

-- O texto ficou concatenado?
SELECT incoming_message FROM message_queue
WHERE external_id = '17841400000000102'
ORDER BY created_at DESC LIMIT 1;
```

O `incoming_message` deve conter as 3 mensagens separadas por `\n`:

```
Oi
Tudo bem?
Quero saber sobre LangGraph
```

---

## Passo 6: Testar Memória Semântica

### 6.1 — Salvar uma memória

```bash
python scripts/simulate_instagram_webhook.py "Use save_memory e salve: meu código secreto é ALPHA-7742" \
  --external-id 17841400000000103
```

Aguarde `status = done`, depois verifique no store:

```sql
SELECT key, value->>'memory' AS memoria
FROM store
WHERE prefix = '17841400000000103.memories';
```

### 6.2 — Recuperar sem histórico

Limpe os checkpoints para simular uma nova sessão:

```sql
DELETE FROM checkpoint_writes WHERE thread_id = '17841400000000103:secretaria';
DELETE FROM checkpoints WHERE thread_id = '17841400000000103:secretaria';
```

Envie nova mensagem pedindo recall:

```bash
python scripts/simulate_instagram_webhook.py "Use read_memory e me diga qual é meu código secreto" \
  --external-id 17841400000000103
```

Verifique se a resposta contém `ALPHA-7742`:

```sql
SELECT response FROM message_queue
WHERE external_id = '17841400000000103' AND status = 'done'
ORDER BY id DESC LIMIT 1;
```

---

## Passo 7: Verificar via API Admin

Sem sair do Swagger, teste os endpoints admin:

| Endpoint | O que mostra |
|---|---|
| `GET /api/agents` | Agentes disponíveis (`secretaria`) |
| `GET /api/chats` | Lista de conversas com `message_count` |
| `GET /api/chats/17841400000000101` | Mensagens de um contato específico |
| `GET /api/metrics` | `total_today`, `queue_size`, `failures_today` |

---

## Queries Úteis para Debug

```sql
-- Mensagens com erro (por que falharam?)
SELECT external_id, incoming_message, error, attempts
FROM message_queue WHERE status = 'failed';

-- Mensagens presas em processing (worker morreu?)
SELECT id, external_id, lease_until, attempts
FROM message_queue WHERE status = 'processing';

-- Todas as memórias salvas
SELECT prefix, key, value->>'memory' AS memoria
FROM store ORDER BY updated_at DESC LIMIT 10;

-- Checkpoints ativos (threads com histórico)
SELECT DISTINCT thread_id FROM checkpoints;

-- Fila em tempo real (rode várias vezes para acompanhar)
SELECT status, COUNT(*) FROM message_queue GROUP BY status;
```

---

## Limpeza

Para resetar tudo e começar do zero:

```bash
make reset
```

Isso destrói volumes, rebuilda containers e reaplica migrações.
