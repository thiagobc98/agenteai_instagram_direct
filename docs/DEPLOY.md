# Deploy

Este guia cobre o deploy completo da **Fase 4**: fechamento operacional do
projeto — API, Worker, Postgres, Redis, Admin Panel (Next.js) e proxy
reverso com TLS, prontos para uma VPS via Docker Compose.

## Escopo desta fase

Incluído:
- tudo da Fase 2/3 (webhook do Instagram real, fila, worker, checkpointer, memória)
- Admin Panel (Next.js) com login e sessão
- rotas `/api/*` protegidas por autenticação (cookie de sessão)
- rate limit distribuído via Redis (substitui o rate limit em memória)
- proxy reverso (Caddy) com TLS automático via Let's Encrypt
- backup de banco via `pg_dump` + crontab
- containers non-root, healthchecks, restart policies, limites de recurso

## Topologia de produção

```text
Internet (443/80)
      |
      v
  [Caddy] --- TLS automático (Let's Encrypt)
   |     |
   |     +--> /api/*, /webhook/*, /health --> [API] (uvicorn)
   |
   +--> tudo mais --> [Frontend] (Next.js, admin panel)

[API] e [Worker] compartilham:
  - [PostgreSQL] (fila, conversas, checkpointer, store semântico)
  - [Redis] (rate limit distribuído)
```

Serviços: `db` (PostgreSQL + pgvector), `redis`, `api`, `worker`,
`frontend`, `proxy` (Caddy — só em produção, via `docker-compose.prod.yml`).

A API e o worker devem compartilhar:
- o mesmo banco e o mesmo Redis
- o mesmo conjunto de variáveis de ambiente
- a mesma versão de código

## Variáveis obrigatórias

- `DATABASE_URL`
- `REDIS_URL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_MODEL`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD` — sem isso, login no admin panel fica sempre bloqueado
- `SESSION_SECRET_KEY` — gere com
  `python -c "import secrets;print(secrets.token_hex(32))"`
- `FRONTEND_ORIGIN` — origem pública do admin panel (CORS)
- `DOMAIN` — domínio público (DNS A record apontando para a VPS), usado
  pelo Caddy para emitir o certificado TLS

Para a tela **Publicar** (Feed, Story, Reels):
- `PUBLIC_BASE_URL` — URL pública HTTPS da API (ex: `https://SEU-DOMINIO`).
  A Meta baixa a mídia de `<PUBLIC_BASE_URL>/media/<token>`, então essa rota
  precisa estar acessível da internet. O Caddy já roteia `/media/*` para a API.
- Volume persistente na **API** em `MEDIA_STORAGE_DIR` (`/app/data/media` no
  Docker). No docker-compose já existe o volume `media_data`. **No Railway,
  crie um Volume no serviço `api` montado em `/app/data/media`**: sem ele, a
  mídia some a cada deploy e publicações agendadas falham. O worker não
  precisa do volume, porque só passa a URL para a Meta.

Recomendadas para operação:
- `LOG_JSON=true`
- `SESSION_COOKIE_SECURE=true` (produção — cookie só via HTTPS)
- `CONTEXT_STRATEGY`
- `MESSAGE_BUFFER_SECONDS`
- `POLL_INTERVAL_SECONDS`
- `LEASE_SECONDS`
- `MAX_ATTEMPTS`
- `MEMORY_ENABLED`
- `EMBEDDING_MODEL`
- `EMBEDDING_DIMS`
- `ACME_EMAIL` (avisos do Let's Encrypt)

Veja `.env.example` para a lista completa.

### Comentários da Página do Facebook

Opcional. `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_ACCESS_TOKEN` e
`FACEBOOK_APP_SECRET` na api e no worker, e o webhook do objeto **Page**
(campo `feed`) em `https://$DOMAIN/webhook/facebook`. Passo a passo e notas de
segurança em [FACEBOOK.md](FACEBOOK.md).

### Avisos no WhatsApp do atendente (Wuzapi)

A cada mensagem nova no Direct, um número de WhatsApp conectado pelo QR Code
(tela **WhatsApp** do painel) manda um aviso ao celular do atendente. Opcional:
sem as variáveis abaixo, os avisos ficam desligados e o resto funciona normal.

- Serviço `wuzapi` (imagem `asternic/wuzapi:1.1.0`, já no `docker-compose.yml`),
  com volume persistente em `/data`. **No Railway**: crie um serviço a partir da
  imagem, com Volume em `/data`, e aponte `WUZAPI_API_URL` da api e do worker
  para o endereço interno dele (`http://<serviço>.railway.internal:8080`).
- `WUZAPI_TOKEN`, `WUZAPI_ADMIN_TOKEN` (api e worker) e
  `WUZAPI_GLOBAL_ENCRYPTION_KEY` (no serviço do Wuzapi). Guarde a chave de
  criptografia fora do servidor: sem ela, a sessão se perde e pede QR Code de novo.
- O Wuzapi não precisa de porta pública: só a api e o worker falam com ele.
- Depois do deploy: painel → **WhatsApp** → Conectar → ler o QR Code com o
  celular que vai **enviar** os avisos (não o do atendente) → cadastrar o
  celular do atendente → **Enviar teste**.

## Ordem de subida

1. Registrar o DNS (`DOMAIN` → IP da VPS) antes do primeiro start —
   o Caddy precisa disso para emitir o certificado.
2. Preparar `.env` com todas as variáveis obrigatórias.
3. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
4. Verificar `curl -I https://$DOMAIN/health` (API) e
   `curl -I https://$DOMAIN/` (frontend).
5. Acessar `https://$DOMAIN/login` e autenticar com `ADMIN_USERNAME`/`ADMIN_PASSWORD`.
6. Cadastrar `https://$DOMAIN/webhook/instagram?agent=secretaria` como callback no painel da Meta (veja [INSTAGRAM_API.md](INSTAGRAM_API.md)) e enviar uma mensagem de teste real pelo Instagram Direct.
7. Acompanhar `/api/metrics` (autenticado) e logs.

## Deploy com Docker

Local (stack de desenvolvimento, sem proxy/TLS):

```bash
docker compose up -d --build
docker compose logs -f api worker db
```

Produção (com proxy reverso, TLS, restart policies e limites de recurso):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

## Firewall e portas

No `docker-compose.yml` (desenvolvimento) as portas `5432` (db), `6379` (redis),
`8000` (api) e `3000` (frontend) ficam publicadas no host, para facilitar o debug.
**O `docker-compose.prod.yml` despublica todas elas**: em produção só o proxy
expõe `80` e `443`, e os serviços conversam pela rede interna do compose.

> ⚠️ Não confie só no `ufw` para proteger portas de containers: o Docker escreve
> direto no iptables e **ignora** as regras do ufw. Por isso a proteção real é
> não publicar a porta (o que o override de produção já faz). Sempre suba com
> os dois arquivos (`-f docker-compose.yml -f docker-compose.prod.yml`).

Use o `ufw` só para o resto do servidor:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Confira de fora, depois do deploy, que só 80/443 respondem
(`nmap -p 22,80,443,3000,5432,6379,8000 <IP>`).

## Backup do banco

```bash
make backup
# equivalente a: ./scripts/backup_db.sh
```

Gera `backups/whatsapp_langchain_<timestamp>.sql.gz` e remove backups com
mais de `BACKUP_RETENTION_DAYS` dias (padrão: 14).

Agendamento recomendado (crontab do host, diariamente às 3h):

```cron
0 3 * * * cd /caminho/do/projeto && ./scripts/backup_db.sh >> backups/backup.log 2>&1
```

Restauração:

```bash
gunzip -c backups/whatsapp_langchain_<timestamp>.sql.gz | \
    docker compose exec -T db psql -U postgres whatsapp_langchain
```

## Stress test

Ver [tests/stress/README.md](../tests/stress/README.md) — só rode contra
a stack local, nunca contra produção.

## Checklist operacional

- health check responde 200 (`/health`, sem autenticação)
- `message_queue` recebe mensagens
- worker faz transição `queued -> processing -> done|failed`
- memória semântica persiste em `store` com prefixo `<external_id>.memories`
- retries acontecem quando há erro transitório
- login no admin panel funciona; `/api/*` retorna 401 sem sessão
- rate limit (429) aparece sob carga alta de um mesmo contato (ver stress test)
- certificado TLS válido emitido pelo Caddy
- portas internas NÃO publicadas (só 80/443 respondem; confira com `nmap` de fora)
- `INSTAGRAM_ACCESS_TOKEN` de longa duração com renovação planejada (expira; envio falha com `instagram_token_invalid`)
- app da Meta em modo Live (App Review aprovado) para atender clientes reais
- token com `instagram_business_manage_comments` (respostas a comentários),
  `instagram_business_content_publish` (tela Publicar) e
  `instagram_business_manage_insights` (métricas para o agente de marketing)
- `curl -I https://SEU-DOMINIO/media/inexistente.jpg` responde 404 (rota
  pública no ar). Uma publicação de teste em Story chega ao perfil
- backup agendado no crontab e testado (restore manual)
- logs estruturados habilitados (`LOG_JSON=true`)

## Hardening — status

Itens que estavam em aberto nas fases anteriores, resolvidos na Fase 4:

- ~~mover rate limit HTTP para backend distribuído~~ → Redis (sorted set,
  sliding window), ver `shared/redis_client.py` e `server/dependencies.py`
- ~~proteger rotas admin (authn/authz)~~ → login + cookie de sessão
  (`server/routes/auth.py`), `/api/*` exige sessão válida
- ~~publicar frontend/admin panel~~ → `frontend/` (Next.js, App Router)

Hardening adicional já incluído:
- containers `api`/`worker`/`frontend` rodam como usuário não-root
- `HEALTHCHECK` em `api`, `frontend`, `db`, `redis`
- `restart: unless-stopped` e limites de recurso em `docker-compose.prod.yml`
- TLS automático via Caddy (Let's Encrypt)
- backup de banco agendável

## Próxima evolução (fora do escopo desta fase)

- múltiplas réplicas de `api`/`worker` atrás do proxy (o rate limit
  distribuído e o pool de conexões já suportam isso, mas não foi testado
  em escala)
- rotação de `SESSION_SECRET_KEY` sem invalidar sessões ativas
- alertas automáticos (ex: webhook para Slack) quando `queue_size` ou
  `failures_today` crescem além de um limiar
