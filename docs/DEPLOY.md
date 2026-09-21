# Deploy

Este guia cobre o deploy completo da **Fase 4**: fechamento operacional do
projeto — API, Worker, Postgres, Redis, Admin Panel (Next.js) e proxy
reverso com TLS, prontos para uma VPS via Docker Compose.

## Escopo desta fase

Incluído:
- tudo da Fase 2/3 (webhook Evolution API real, fila, worker, checkpointer, memória)
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

## Ordem de subida

1. Registrar o DNS (`DOMAIN` → IP da VPS) antes do primeiro start —
   o Caddy precisa disso para emitir o certificado.
2. Preparar `.env` com todas as variáveis obrigatórias.
3. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
4. Verificar `curl -I https://$DOMAIN/health` (API) e
   `curl -I https://$DOMAIN/` (frontend).
5. Acessar `https://$DOMAIN/login` e autenticar com `ADMIN_USERNAME`/`ADMIN_PASSWORD`.
6. Enviar mensagem de teste real via WhatsApp/Evolution API.
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

## Firewall

As portas `5432` (db), `6379` (redis), `8000` (api) e `3000` (frontend)
continuam publicadas no host pelo `docker-compose.yml` (útil para debug
local). Em produção, feche-as externamente e deixe só `22` (SSH), `80` e
`443` acessíveis:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

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
- memória semântica persiste em `store` com prefixo `<phone_number>.memories`
- retries acontecem quando há erro transitório
- login no admin panel funciona; `/api/*` retorna 401 sem sessão
- rate limit (429) aparece sob carga alta de um mesmo telefone (ver stress test)
- certificado TLS válido emitido pelo Caddy
- portas internas fechadas no firewall (só 22/80/443 externas)
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
