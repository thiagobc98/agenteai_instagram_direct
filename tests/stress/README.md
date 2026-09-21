# Stress Test (Locust)

Simula carga concorrente em `/webhook/instagram` para validar o pipeline
completo sob pressão: assinatura, rate limit (Redis), debounce/fila
(PostgreSQL) e worker.

## Pré-requisitos

1. Stack local rodando: `make up`
2. `LOCUST_APP_SECRET` (ou `INSTAGRAM_APP_SECRET`) definido no ambiente com
   o mesmo valor configurado no `.env` da stack — sem a assinatura correta,
   todas as requisições são rejeitadas com 403.
3. Rode a stack com um `INSTAGRAM_ACCESS_TOKEN` **falso** (ou
   `INSTAGRAM_GRAPH_BASE_URL` apontando para um stub local): o Worker tenta
   responder cada mensagem pela Graph API e você não quer gerar chamadas
   reais à Meta. Com token falso os envios falham (erro 190) e nada é
   entregue.
4. **Nunca rode contra produção.**

## Rodando

Modo UI (abre em http://localhost:8089, permite ajustar usuários/spawn
rate ao vivo):

```bash
make stress
```

Modo headless (ex: 50 usuários, spawn de 5/s, por 2 minutos):

```bash
make stress-headless
```

Parâmetros customizados direto com uv:

```bash
uv run --extra stress locust -f tests/stress/locustfile.py \
    --host http://localhost:8000 \
    --headless -u 100 -r 10 -t 5m
```

## O que observar

Durante e após o teste, acompanhe:

```bash
curl http://localhost:8000/api/metrics
docker compose logs -f worker
```

Critérios de saúde:

- `queue_size` não cresce indefinidamente — o worker consegue drenar a
  fila no ritmo da carga gerada.
- `failures_today`: com token falso, os envios falham por definição (cresce
  junto com as tentativas) — avalie a fila, não esse número. Alguns `429`
  são **esperados** quando um contato excede `RATE_LIMIT_PER_HOUR` — isso é o rate limit
  distribuído (Redis) funcionando sob concorrência, não uma falha.
- `avg_processing_time_seconds` se mantém estável, sem degradar ao
  longo do teste.
- Sem erros de esgotamento do pool de conexões (`AsyncConnectionPool`)
  nos logs da API/worker — se aparecerem, considere aumentar
  `max_size` em `shared/db.py` antes de escalar mais a carga.
- `queue_size` volta a 0 pouco depois do teste terminar.
