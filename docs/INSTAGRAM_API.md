# Instagram Direct — Setup e Integração (Instagram Messaging API)

Guia para conectar o projeto a uma conta profissional do Instagram e fazer o
agente responder os clientes no Direct, usando a API oficial da Meta
([Instagram Messaging API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api)).

> **Confira a documentação oficial antes de configurar.** A Meta muda versões,
> permissões e telas do painel com frequência. Este guia foi escrito com base
> na documentação consultada em setembro/2026 (Graph API **v25.0**); onde algo
> não pôde ser confirmado, isso está marcado com ⚠️.

## Visão geral

```
Cliente no Instagram Direct
       │
       ▼
Meta (Instagram Messaging API)
       │  POST /webhook/instagram?agent=secretaria
       │  header X-Hub-Signature-256: sha256=<HMAC do body com o App Secret>
       ▼
ngrok / cloudflared / domínio ──► API (localhost:8000)
                                      │  valida assinatura, rate limit
                                      ▼
                               PostgreSQL (fila)
                                      │
                                      ▼
                          Worker ──► InstagramClient.mark_seen() / send_typing()
                                      │
                                      ▼
                               graph.ainvoke()
                                      │
                                      ▼
            InstagramClient.send_message() ──► Graph API ──► Instagram Direct
```

Diferente de provedores com número/sandbox próprio, aqui a conversa acontece
na **sua conta profissional do Instagram**. O cliente é identificado pelo
**IGSID** (Instagram-scoped ID) — um ID numérico por cliente/app, que **não é
telefone**. O projeto o chama de `external_id`.

## 1. Pré-requisitos

- Conta do Instagram do tipo **Profissional** (Comercial ou Criador)
- Conta em [developers.facebook.com](https://developers.facebook.com)
- Um endereço público HTTPS para o webhook (ngrok, cloudflared ou seu domínio)
- Stack local rodando (`make up` ou `make db` + `make api` + `make worker`)

Há dois "sabores" da API. **O projeto usa por padrão o Instagram Login**:

| | Instagram Login (padrão) | Facebook Login |
|---|---|---|
| Host | `graph.instagram.com` | `graph.facebook.com` |
| Página do Facebook vinculada | não exigida | exigida |
| Token | Instagram User access token | Page Access Token |
| Permissões | `instagram_business_basic`, `instagram_business_manage_messages` | `instagram_basic`, `instagram_manage_messages` (e as de Página) |

Para usar o Facebook Login, defina `INSTAGRAM_GRAPH_BASE_URL=https://graph.facebook.com`
e use o Page Access Token em `INSTAGRAM_ACCESS_TOKEN`. O restante do projeto
não muda (ambos usam `POST /me/messages`).

## 2. Criar o app no Meta for Developers

1. Em **My Apps → Create App**, escolha o caso de uso de Instagram
   (mensagens / API do Instagram) e tipo **Business**.
2. No painel do app, adicione o produto **Instagram** e abra **API setup with
   Instagram login**.
3. Anote:
   - **App Secret** (App settings → Basic) → `INSTAGRAM_APP_SECRET`
   - **ID da conta profissional** (mostrado na configuração da API) →
     `INSTAGRAM_BUSINESS_ACCOUNT_ID` (opcional, evita eventos da própria conta)

### Modo de desenvolvimento vs. modo Live

- **Modo de desenvolvimento (padrão):** só funciona com contas que têm papel no
  app (administradores, desenvolvedores e testadores). Serve para testar o
  fluxo inteiro com a sua conta e a de colegas.
- **Modo Live:** necessário para atender clientes reais. ⚠️ Em geral exige
  **App Review** das permissões (acesso avançado), política de privacidade e,
  dependendo da conta, verificação do negócio. Prepare um vídeo mostrando o
  fluxo de mensagens e confira os requisitos atuais no painel.
- **Webhooks só chegam com o app em Live.** A doc de webhooks da Meta afirma que
  o app "must be set to **Live** in the App Dashboard for Meta to send webhook
  notifications". Ou seja: mesmo para testar, se as mensagens não chegarem ao
  seu webhook, o primeiro suspeito é o app ainda estar em modo de
  desenvolvimento. Colocar em Live exige, no mínimo, **URL da política de
  privacidade** e **categoria** em App settings → Basic.
- **Acesso Standard vs. Avançado:** o Standard (padrão) serve para apps usados
  só por quem tem papel no app, ou que atendem **a sua própria conta
  profissional** — provavelmente suficiente para a sua loja, sem App Review.
  O Avançado (App Review + verificação do negócio) é para atender contas que
  você não administra.

## 3. Permissões (escopos)

Para receber e responder mensagens:

- `instagram_business_basic`
- `instagram_business_manage_messages`

(No Facebook Login: `instagram_basic` e `instagram_manage_messages`, além das
permissões de Página exigidas pela doc.)

O **App Review** é a etapa em que a Meta aprova o uso dessas permissões para
contas fora do seu app. Ela exige ação manual sua — o código não resolve isso.

## 4. Gerar o token de acesso

No painel, em **API setup with Instagram login**, adicione a conta profissional
e clique em **Generate token**. Cole o valor em `INSTAGRAM_ACCESS_TOKEN`.

⚠️ Tokens do Instagram Login são de curta duração até serem trocados por um de
**longa duração** (~60 dias) e precisam ser renovados antes de expirar. Confira
na doc oficial os endpoints atuais de troca (`access_token`) e de renovação
(`refresh_access_token`). Quando o token expira, o envio falha com erro Graph
`190` e o worker registra `instagram_token_invalid` no log — é o sinal de que
falta renovar.

## 5. Variáveis de ambiente

```bash
# === Instagram Direct ===
INSTAGRAM_ACCESS_TOKEN=token-de-longa-duracao
INSTAGRAM_APP_SECRET=app-secret-do-painel-basic
# Token que VOCÊ inventa; o mesmo valor vai no painel ao cadastrar o webhook.
# Gere com: python -c "import secrets;print(secrets.token_hex(24))"
INSTAGRAM_VERIFY_TOKEN=um-token-aleatorio-so-seu
INSTAGRAM_BUSINESS_ACCOUNT_ID=17841400000000000
INSTAGRAM_GRAPH_API_VERSION=v25.0
INSTAGRAM_GRAPH_BASE_URL=https://graph.instagram.com
```

- O **Worker** exige `INSTAGRAM_ACCESS_TOKEN` (falha ao subir sem ele).
- A **API** exige `INSTAGRAM_APP_SECRET` (assinatura) e `INSTAGRAM_VERIFY_TOKEN`
  (handshake); sem eles o webhook responde `500`.

## 6. Túnel local

A Meta precisa alcançar sua API local por HTTPS:

```bash
# ngrok
ngrok http 8000
# ou cloudflared
cloudflared tunnel --url http://localhost:8000
```

> A URL muda a cada reinício do túnel. Se reiniciar, atualize a URL de callback
> no painel da Meta (próximo passo).

## 7. Configurar o webhook

No painel do app, em **Instagram → Webhooks** (ou **Configure webhooks** na
API setup):

- **Callback URL:** `https://seu-tunel.ngrok.app/webhook/instagram?agent=secretaria`
- **Verify token:** o valor de `INSTAGRAM_VERIFY_TOKEN`

Ao salvar, a Meta faz um `GET` na URL com `hub.mode=subscribe`,
`hub.verify_token` e `hub.challenge`. O projeto devolve o `hub.challenge` em
texto puro se o token confere (senão `403`) — só então o painel aceita a URL.

Depois, **assine o campo `messages`** (os campos `messaging_seen`,
`message_reactions` e `messaging_postbacks` não são necessários; se assinados,
são ignorados).

A Meta assina cada `POST` com o **App Secret**: header
`X-Hub-Signature-256: sha256=<HMAC-SHA256 do body bruto>`. O projeto recalcula
e compara em tempo constante; assinatura ausente ou inválida → `403`.

O parser do payload está inteiro em
[`shared/instagram_payload.py`](../src/whatsapp_langchain/shared/instagram_payload.py)
— se a Meta mudar o formato, é o único lugar que precisa de ajuste.

## 8. Teste ponta a ponta

### 8.1 Verificação do webhook (simulando a Meta)

```bash
curl "http://localhost:8000/webhook/instagram?hub.mode=subscribe&hub.verify_token=SEU_VERIFY_TOKEN&hub.challenge=12345"
# → 12345
```

### 8.2 Mensagem simulada (com assinatura)

O jeito mais simples é o script, que monta o payload, assina com o
`INSTAGRAM_APP_SECRET` do `.env` e envia (aceita `--external-id`,
`--image-url`, `--audio-url` e `--url` para apontar para o túnel):

```bash
python scripts/simulate_instagram_webhook.py "Olá, teste local"
# → 200 {"received":true,"enqueued":1}
```

Ou, na mão, com `openssl` (o Swagger não serve aqui: a assinatura precisa ser
calculada sobre o body exato):

```bash
BODY='{"object":"instagram","entry":[{"id":"17841400000000000","time":1700000000000,"messaging":[{"sender":{"id":"17841400000000001"},"recipient":{"id":"17841400000000000"},"timestamp":1700000000000,"message":{"mid":"MIDTEST001","text":"Olá, teste local"}}]}]}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "SEU_APP_SECRET" | sed 's/^.* //')

curl -X POST "http://localhost:8000/webhook/instagram?agent=secretaria" \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=$SIG" \
  -d "$BODY"
# → {"received":true,"enqueued":1}
```

> Nesse teste o Worker vai tentar **responder de verdade** para o IGSID
> `17841400000000001`, que não existe — o envio falha e a mensagem entra no
> fluxo de retry. Para ver a resposta chegar, use um IGSID real (veja 8.3), ou
> use `/webhook/sync` para testar só o agente, sem envio.

```bash
curl -X POST "http://localhost:8000/webhook/sync?agent=secretaria" \
  -H "Content-Type: application/json" \
  -d '{"external_id":"17841400000000001","message":"Olá!"}'
```

### 8.3 Fluxo real

1. Com o app em modo de desenvolvimento, envie uma mensagem de outra conta
   Instagram (que tenha papel no app) para a conta profissional.
2. Acompanhe os logs do Worker: `message_claimed` → `instagram_message_sent`.
3. Confira no Admin Panel (`http://localhost:3000`) ou por SQL:

```sql
SELECT external_id, agent_id, message_count, last_message, channel
FROM conversations ORDER BY last_message_at DESC LIMIT 5;
```

## 9. Regras do canal que o projeto já trata

### Janela de 24h

Só é possível enviar mensagem a quem escreveu para a conta nas **últimas 24
horas**. Como respondemos logo após receber, o fluxo normal está sempre dentro
da janela. A regra pesa nas **notificações proativas** (`worker/notifications.py`):

- **Lembrete de consulta ao paciente** e **agenda do dia à médica** só são
  enviados se o destinatário escreveu para a conta nas últimas 24h. A checagem
  usa a última mensagem recebida (`message_queue.created_at`).
- Fora da janela a mensagem **não é enviada** e o motivo vai para o log:
  `patient_reminder_skipped_outside_window` /
  `doctor_notification_skipped_outside_window`. O lembrete não é marcado como
  enviado; uma nova execução no mesmo dia tenta de novo.
- Na prática, com o Worker rodando o lembrete uma vez por dia, ele só chega a
  quem falou com a conta nas 24h anteriores. Um lembrete "frio" (paciente que
  agendou dias antes e não escreveu desde então) **não é entregue**.

Se o Instagram recusar o envio por janela expirada, o cliente lança
`InstagramSendError` com `is_window_closed=True` (log `instagram_window_closed`).

⚠️ A doc menciona que respostas de um **atendente humano** podem usar uma tag
para ultrapassar as 24h, mas não detalha nome da tag nem prazo na página que
consultei. **O projeto não envia tags**: usar esse recurso para automação
proativa provavelmente viola a política da Meta. Se precisar de lembretes
frios, considere outro canal (SMS/e-mail/WhatsApp) para essa etapa.

### Limite de tamanho

Texto **UTF-8 de no máximo 1000 bytes** por mensagem. O `InstagramClient`
divide respostas maiores em várias mensagens (por parágrafo, depois linha,
depois palavra) e as envia em sequência.

### Sem markdown

O Instagram exibe `**negrito**`, `#` e crases literalmente. O prompt do agente
pede texto simples e o cliente remove essas marcações como rede de segurança.

### Mídia

Anexos chegam como **URL** em `message.attachments[].payload.url` (não em
base64). O Worker baixa a URL (somente `https`, timeout de 20s, máx. 16MB) e
processa:

| Tipo | Tratamento |
|---|---|
| `image` | descrição via modelo multimodal |
| `audio` | transcrição via modelo multimodal |
| `video`, `file`, `share`, `ig_reel`, `story_mention`… | resposta automática "tipo de mídia não suportado" |
| `like_heart` (coração) | ignorado, sem resposta |

Se a URL expirou (403/404/410) ou o download falha, o cliente recebe a resposta
automática de falha de mídia e o motivo é gravado em
`message_queue.media_processing_error`. Só o primeiro anexo de cada mensagem é
processado.

⚠️ O formato de áudio dos anexos (geralmente `audio/mp4`/AAC) é enviado ao
modelo com `format=m4a`/`aac`; se o seu modelo do OpenRouter não aceitar,
ajuste `_audio_format_from_media_type` em `worker/media.py`.

### Sender actions

Antes de gerar a resposta o Worker chama `mark_seen` e `typing_on`
(best-effort: falha não interrompe o atendimento). O indicador de digitação
some sozinho quando a mensagem é enviada.

### Erros da Graph API tratados no cliente

| Situação | Detecção | Log |
|---|---|---|
| Token expirado/inválido | erro Graph `190` | `instagram_token_invalid` |
| Fora da janela de 24h | subcódigo `2534022` ou mensagem "outside of allowed window" ⚠️ | `instagram_window_closed` |
| Rate limit | HTTP `429` ou códigos `4`, `17`, `32`, `613`, `80002` ⚠️ | `instagram_rate_limited` |
| Outros | qualquer 4xx/5xx | `instagram_send_failed` |

⚠️ Os códigos/subcódigos acima vêm de convenção da Graph API e não foram
confirmados na página de referência que consultei; se a Meta usar outros
valores, ajuste as constantes no topo de `worker/instagram_client.py`.

Todo erro de envio levanta `InstagramSendError` e cai no retry padrão da fila
(`mark_failed`, backoff progressivo até `MAX_ATTEMPTS`).

## 10. Identidade e histórico

- O `external_id` (IGSID) é a chave em `message_queue`, `conversations`,
  `appointment_reminders`, no `thread_id` (`{external_id}:{agent_id}`) e no
  namespace da memória semântica.
- A migration `006_instagram_identity.sql` renomeia as colunas e marca o
  histórico do WhatsApp com `channel = 'whatsapp'`. Os contatos do Instagram
  começam com **histórico e memória novos** — IGSID e telefone não se
  relacionam.
- Consultas dos pacientes na agenda passam a usar
  `extendedProperties.private.external_id`. Eventos criados antes da migração
  (com `phone`) continuam aparecendo no painel, mas **não** são encontrados
  pelas tools do agente nem recebem lembrete.

## 11. Solução de problemas

| Sintoma | Causa provável |
|---|---|
| Painel recusa a URL de callback | `INSTAGRAM_VERIFY_TOKEN` diferente do digitado, API fora do ar ou túnel com URL antiga |
| Webhook responde `403` | `INSTAGRAM_APP_SECRET` errado, ou algo (proxy) alterou o body antes da API |
| Webhook responde `500` | `INSTAGRAM_APP_SECRET`/`INSTAGRAM_VERIFY_TOKEN` não configurados na API |
| Mensagem chega mas nada é respondido | Worker parado, token expirado (`instagram_token_invalid`) ou app em modo de desenvolvimento e remetente sem papel no app |
| `instagram_window_closed` | resposta tentada mais de 24h após a última mensagem do cliente |
| Worker não sobe | `INSTAGRAM_ACCESS_TOKEN` ausente |
