# Evolution API — Setup e Integração WhatsApp

Guia para conectar o projeto a uma instância do
[Evolution API](https://github.com/EvolutionAPI/evolution-api) auto-hospedada
(sua VPS), substituindo o Twilio como provedor de WhatsApp.

## Visão geral

```
Usuário WhatsApp
       │
       ▼
Evolution API (sua VPS)
       │  POST /webhook/evolution/{token}?agent=secretaria
       │  (sem assinatura — token secreto no path)
       ▼
cloudflared tunnel ──► API (localhost:8000)
                              │
                              ▼
                       PostgreSQL (fila)
                              │
                              ▼
                       Worker ──► EvolutionClient.send_typing()
                              │
                              ▼
                       graph.ainvoke()
                              │
                              ▼
                       EvolutionClient.send_message() ──► Evolution API ──► WhatsApp
```

Diferente do Twilio, o Evolution API roda na **sua própria infraestrutura** —
não há sandbox, número compartilhado, nem necessidade de conta em serviço de
terceiros. O worker fala diretamente com a API REST da sua instância.

## 1. Pré-requisitos

- Instância Evolution API v2.x rodando na sua VPS, com uma instância
  WhatsApp já conectada (QR Code escaneado, status `open`)
- `cloudflared` instalado ([download](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)) — para expor a API local publicamente
- Stack local rodando (`make up` ou `make db` + `make api` + `make worker`)

### 1.1 Obter as credenciais da instância

No Evolution Manager (painel web da sua instância):

1. Confirme o nome da instância conectada — é o valor de `EVOLUTION_INSTANCE`.
2. Copie a `apikey` da instância (Settings → API Key, ou a mesma usada na
   criação via `/instance/create`) — é o valor de `EVOLUTION_API_KEY`.
3. `EVOLUTION_BASE_URL` é a URL pública da sua instância (ex:
   `https://evo.seudominio.com`), sem barra final.

## 2. Variáveis de ambiente

```bash
# === Evolution API ===
EVOLUTION_BASE_URL=https://evo.seudominio.com
EVOLUTION_API_KEY=sua-apikey-aqui
EVOLUTION_INSTANCE=minha-instancia

# Token secreto PRÓPRIO (você inventa, não vem do Evolution) — protege o
# endpoint de webhook, já que o Evolution não assina os requests.
# Gere com: python -c "import secrets;print(secrets.token_hex(24))"
EVOLUTION_WEBHOOK_TOKEN=um-token-aleatorio-so-seu
```

## 3. Túnel local com cloudflared

Igual ao fluxo usado com qualquer webhook externo: sua API local precisa
estar publicamente acessível para a VPS do Evolution conseguir chamá-la.

```bash
cloudflared tunnel --url http://localhost:8000
```

Saída esperada:
```
INF +----------------------------+
INF |  Your quick Tunnel has been created! Visit it at:
INF |  https://random-name.trycloudflare.com
INF +----------------------------+
```

> A URL muda a cada reinício do cloudflared. Se reiniciar, atualize o
> webhook configurado no Evolution Manager (próximo passo).

## 4. Configurar o webhook na instância

No Evolution Manager, na sua instância → **Webhook**:

- **URL**: `https://random-name.trycloudflare.com/webhook/evolution/SEU_EVOLUTION_WEBHOOK_TOKEN?agent=secretaria`
- **Eventos**: habilite pelo menos `MESSAGES_UPSERT`
- **Webhook Base64**: **habilite** (`webhookBase64=true`) — o worker espera
  receber imagem/áudio já em base64 dentro do próprio webhook, sem precisar
  baixar de uma URL separada

Ou via API REST, se preferir configurar por código:

```bash
curl -X POST "https://evo.seudominio.com/webhook/set/minha-instancia" \
  -H "apikey: SUA_APIKEY" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "url": "https://random-name.trycloudflare.com/webhook/evolution/SEU_EVOLUTION_WEBHOOK_TOKEN?agent=secretaria",
      "enabled": true,
      "webhookBase64": true,
      "events": ["MESSAGES_UPSERT"]
    }
  }'
```

> Os nomes exatos dos campos podem variar ligeiramente entre versões
> menores do Evolution API. Se o webhook não chegar, confira a
> documentação/Postman da sua versão específica e ajuste conforme
> necessário — a extração do payload é feita inteiramente em
> [`shared/evolution_payload.py`](../src/whatsapp_langchain/shared/evolution_payload.py),
> então é o único lugar do código que precisaria de ajuste.

## 5. Teste ponta a ponta

### 5.1 Fluxo simulado (sem Evolution real)

```bash
curl -X POST "http://localhost:8000/webhook/evolution/SEU_EVOLUTION_WEBHOOK_TOKEN?agent=secretaria" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "messages.upsert",
    "instance": "minha-instancia",
    "data": {
      "key": {"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": false, "id": "MSGTEST001"},
      "message": {"conversation": "Olá, teste local"},
      "messageType": "conversation"
    }
  }'
```

Verifique:
```bash
curl http://localhost:8000/api/chats/+5511999999999
```

### 5.2 Fluxo real (Evolution + WhatsApp)

1. Confirme que todos os serviços estão rodando:
   ```bash
   make logs
   # api, worker e db devem estar healthy
   ```

2. Confirme o túnel:
   ```bash
   curl https://random-name.trycloudflare.com/health
   ```

3. Envie uma mensagem do WhatsApp para o número conectado na instância

4. Verifique nos logs:
   ```bash
   make logs
   # Procure por: webhook_evolution_received, message_claimed,
   # evolution_typing_sent, message_processed, evolution_message_sent
   ```

5. A resposta do agente deve chegar no WhatsApp

## 6. Debounce e mídia

Regras de debounce (mesmas da integração anterior):

- **Texto**: mensagens rápidas do mesmo phone+agent são agrupadas
  (concatenadas) dentro da janela de `MESSAGE_BUFFER_SECONDS` (padrão: 2s)
- **Mídia**: entra imediatamente (sem debounce). Antes de inserir mídia,
  textos pendentes do mesmo phone+agent são "flushed" (processados
  imediatamente)
- **Ordem**: o worker processa por `created_at ASC`, então texto flushed
  sai antes da mídia
- **Concorrência**: `pg_advisory_xact_lock(hash(phone+agent))` serializa
  operações do mesmo remetente/agente

### Mídia via base64

Diferente do Twilio (que exigia baixar a mídia de uma URL autenticada), o
Evolution entrega o conteúdo já em base64 dentro do próprio payload de
webhook (com `webhookBase64=true`). O worker decodifica diretamente — ver
`worker/media.py::decode_media_base64`. Isso elimina uma chamada de rede a
mais e a necessidade de credenciais de download.

Tipos suportados hoje: `imageMessage` e `audioMessage`. Outros tipos
(`videoMessage`, `documentMessage`, `stickerMessage`, etc.) são
reconhecidos mas tratados como mídia não suportada — o worker responde
automaticamente pedindo texto, sem invocar o agente.

## 7. Variáveis por serviço

| Variável | API | Worker | Obrigatória |
|---|---|---|---|
| `DATABASE_URL` | sim | sim | sim |
| `OPENROUTER_API_KEY` | não | sim | sim (para agente) |
| `EVOLUTION_BASE_URL` | não | sim | **sim** |
| `EVOLUTION_API_KEY` | não | sim | **sim** |
| `EVOLUTION_INSTANCE` | não | sim | **sim** |
| `EVOLUTION_WEBHOOK_TOKEN` | sim | não | **sim** |

> O Worker faz fail-fast na inicialização se `EVOLUTION_BASE_URL`,
> `EVOLUTION_API_KEY` ou `EVOLUTION_INSTANCE` estiverem vazios. Nenhum
> `mark_done` ocorre sem envio confirmado pela Evolution API.

## 8. Troubleshooting

### Mensagem não chega no WhatsApp

1. Verifique `EVOLUTION_BASE_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE`
   no `.env`
2. Confirme que a instância está com status `open` no Evolution Manager
   (não `close`/`connecting`)
3. Verifique logs do worker: `make logs | grep evolution`

### 403 no webhook

- O `token` no path da URL configurada no Evolution não confere com
  `EVOLUTION_WEBHOOK_TOKEN` do `.env` — copie de novo, com cuidado com
  espaços/quebras de linha.

### 500 no webhook

- `EVOLUTION_WEBHOOK_TOKEN` está vazio no `.env` da API.

### Webhook nunca chega (nada nos logs)

- Confirme que o túnel cloudflared está ativo e que a URL configurada no
  Evolution Manager bate exatamente com a URL atual do túnel (ela muda a
  cada reinício)
- Confirme que o evento `MESSAGES_UPSERT` está habilitado na configuração
  de webhook da instância

### cloudflared desconecta

O tunnel efêmero do cloudflared pode cair. Reinicie e atualize:
1. `cloudflared tunnel --url http://localhost:8000`
2. Atualize a URL do webhook no Evolution Manager com a nova URL do túnel

### Worker não inicia (fail-fast)

O worker faz fail-fast se credenciais outbound estiverem faltando. Verifique:
```bash
grep -E '^EVOLUTION_(BASE_URL|API_KEY|INSTANCE)' .env
```

### Depois de qualquer alteração em `src/` ou no `.env`

`docker compose restart worker` **não é suficiente** — o worker roda a
partir de uma imagem Docker com o código já copiado para dentro dela no
build. É preciso reconstruir:

```bash
docker compose up -d --build worker
```

### Identidade inbound

O webhook usa `data.key.remoteJid` (formato `<dígitos>@s.whatsapp.net`)
como identidade primária, normalizado para `+E.164`. Mensagens de grupo
(`@g.us`) e mensagens com `fromMe: true` (eco do próprio bot) são
ignoradas silenciosamente — ver `shared/evolution_payload.py`.
