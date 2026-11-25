# Comentários da Página do Facebook

A tela **Facebook** do painel mostra os comentários dos posts da Página
*Patricia Berberich Calçados*. Funciona como a tela de comentários do Instagram:

1. Alguém comenta num post da Página.
2. A Meta avisa a API pelo webhook (`/webhook/facebook`, campo `feed`).
3. O Worker pede à IA um rascunho: resposta pública + mensagem privada no Messenger.
4. A equipe revisa e aprova no painel. **Nada é publicado sem aprovação.**

Valor, número, cores, estoque e frete seguem a mesma regra do Instagram: a
resposta pública avisa que chamou no Messenger e a mensagem privada pede o
WhatsApp da cliente e manda o link da Patrícia (com "Vim pelo Facebook da loja").

```text
Comentário ─▶ Meta ─webhook (assinado)─▶ API ─▶ ig_comments (channel=facebook)
                                                   │
                     Worker (IA) ─ rascunho ◀──────┘
                                                   │
        Painel ─ aprovar ─▶ API ─▶ Graph API: resposta pública + Messenger
```

## 1. Token da Página

O token do Instagram (login do Instagram) **não** serve para a Página. É preciso
um **Page Access Token** do mesmo app da Meta.

1. developers.facebook.com → **Meus apps** → o app → **Adicionar produto** →
   **Login do Facebook para Empresas** (ou **Messenger**).
2. Em **Análise do app → Permissões e recursos**, confira **Acesso padrão** em:
   - `pages_show_list`
   - `pages_read_engagement` (ler posts e comentários)
   - `pages_read_user_content` (nome de quem comentou)
   - `pages_manage_engagement` (responder comentários)
   - `pages_messaging` (mensagem privada no Messenger)
   - `pages_manage_metadata` (inscrever o app no webhook da Página)

   Para a Página da própria loja, o acesso padrão basta (sem App Review).
3. **Ferramentas → Explorador da Graph API**: escolha o app, clique em
   **Gerar token de acesso** com as permissões acima, e no campo
   **Usuário ou Página** escolha a **Página**. O token gerado é o da Página.
4. Troque por um token de **longa duração** (o do Explorador dura ~1h): use o
   **Depurador de token de acesso** → **Estender token de acesso**. Um Page
   Token obtido de um token de usuário de longa duração não expira enquanto a
   senha e as permissões não mudarem.

## 2. Variáveis no `.env`

```dotenv
FACEBOOK_PAGE_ID=1234567890            # ID da Página (o /me do token da Página)
FACEBOOK_PAGE_ACCESS_TOKEN=EAAG...     # Page Access Token de longa duração
FACEBOOK_APP_SECRET=...                # Configurações do app → Básico → Chave secreta do app
FACEBOOK_VERIFY_TOKEN=                 # vazio reaproveita o INSTAGRAM_VERIFY_TOKEN
```

- `FACEBOOK_APP_SECRET` é a chave do **app Meta**, diferente da "chave secreta do
  app do Instagram". Ela valida a assinatura dos webhooks e gera o
  `appsecret_proof` de cada chamada à Graph API.
- Depois de salvar, reinicie a API e o Worker. A tela **Facebook** mostra
  "Conectado à Página ..." quando o token confere com o `FACEBOOK_PAGE_ID`.

## 3. Webhook da Página

No app: **Webhooks** → objeto **Page** → **Assinar este objeto**:

- **URL de retorno**: `https://SEU-DOMINIO/webhook/facebook`
- **Verificar token**: o `FACEBOOK_VERIFY_TOKEN` (ou o `INSTAGRAM_VERIFY_TOKEN`)
- Assine o campo **`feed`**.

Depois, **inscreva o app na Página** (uma vez), com o token da Página:

```bash
curl -X POST "https://graph.facebook.com/v25.0/$FACEBOOK_PAGE_ID/subscribed_apps" \
     -d "subscribed_fields=feed" -H "Authorization: Bearer $FACEBOOK_PAGE_ACCESS_TOKEN"
```

Sem o webhook a tela ainda funciona pelo botão **Sincronizar** (busca os posts
recentes e os comentários dos últimos 7 dias).

## Segurança

- **Webhook**: só aceita POST com assinatura `X-Hub-Signature-256` válida
  (HMAC-SHA256 com o `FACEBOOK_APP_SECRET`, comparação em tempo constante). Sem
  o segredo configurado, recusa tudo (fail-closed). A chave do Instagram não abre
  o webhook do Facebook.
- **Só a Página da loja**: eventos de outras Páginas são descartados, e o status
  avisa se o token for de outra Página.
- **Token**: vai no header `Authorization` (nunca na URL), não aparece em log nem
  em mensagem de erro. Recomendado: em **Configurações do app → Avançado**, ligar
  **Exigir prova do segredo do app**. Assim um token vazado não funciona sozinho.
- **IA**: o comentário e o nome de quem comentou são dados de terceiros, entram
  entre marcações e nunca como instrução; tentativas de prompt injection viram
  sugestão de "ignorar". A IA só rascunha: publicar exige aprovação no painel,
  com o nome de quem aprovou registrado.
- **Painel**: as rotas exigem login de administrador.

## Limites da Meta

- Mensagem privada: **uma por comentário**, até **7 dias** depois dele; outras só
  depois que a pessoa responder no Messenger.
- As respostas da cliente no Messenger chegam na caixa de entrada da Página
  (Meta Business Suite). Atender o Messenger pela IA é um passo futuro.
