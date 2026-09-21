# agenteai_instagram_direct

Agente de IA que **atende os clientes diretamente no Instagram Direct** — do
primeiro contato ao agendamento — usando a API oficial da Meta (Instagram
Messaging API). Construído com Python, LangChain, LangGraph e FastAPI.

O agente conversa com o cliente no Direct, lembra do que já foi dito
(contexto por conversa + memória semântica), entende imagens e áudios e, na
versão atual (uma secretária virtual), consulta e marca horários no Google
Calendar. Não há mais encaminhamento do lead para o WhatsApp: a conversa
inteira acontece no Instagram.

> Este projeto nasceu como um atendente de WhatsApp (Evolution API). Foi
> migrado por completo para o Instagram Direct; só a "borda" de transporte
> mudou — agente, fila, debounce, retry, memória e Admin Panel são os mesmos.

## Como funciona

```text
Cliente (Instagram Direct)
   │
   ▼
Meta ──POST /webhook/instagram (assinado com X-Hub-Signature-256)──► API FastAPI
                                                                      │ valida, rate limit,
                                                                      │ debounce
                                                                      ▼
                                                             PostgreSQL (message_queue)
                                                                      │
                                                                      ▼
                                                     Worker ──► agente LangGraph
                                                                      │
                                                                      ▼
                        Instagram Messaging API (Graph API) ◄── resposta (texto puro, ≤1000 bytes/msg)
```

- **API** (`server/`): responde ao handshake da Meta, valida a assinatura,
  aplica rate limit por contato e enfileira. Nunca executa o agente inline.
- **Worker** (`worker/`): consome a fila, baixa mídia (URL), roda o agente e
  envia a resposta pelo Instagram. Também dispara os lembretes diários.
- **Admin Panel** (`frontend/`, Next.js): dashboard, conversas e agenda.

O contato é identificado pelo **IGSID** (ID do usuário no escopo do app), que
o código chama de `external_id`.

## Limitações do canal (leia antes de usar)

- **Janela de 24h:** o Instagram só permite enviar mensagem a quem escreveu
  para a conta nas últimas 24h. As respostas do agente ficam sempre dentro da
  janela, mas **lembretes proativos** (consulta amanhã, resumo da médica) só
  chegam a quem falou com a conta nas 24h anteriores — fora disso são pulados e
  registrados em log. Detalhes em [docs/INSTAGRAM_API.md](docs/INSTAGRAM_API.md).
- **Só texto simples**, até 1000 bytes por mensagem (o cliente divide
  respostas longas e remove markdown).
- **App Review da Meta:** para atender clientes reais, o app precisa sair do
  modo de desenvolvimento (revisão de permissões). É um passo manual.

## Quick Start

### 1. Setup

```bash
git clone <repo-url>
cd agenteai_instagram_direct
make setup
cp .env.example .env
```

Edite o `.env` e configure pelo menos `OPENROUTER_API_KEY` e as variáveis
`INSTAGRAM_*` (passo a passo em [docs/INSTAGRAM_API.md](docs/INSTAGRAM_API.md)).

### 2. Suba o stack local

```bash
make up
# sobe: db + redis + api + worker + frontend
```

Valide a API: `curl http://localhost:8000/health`. O Admin Panel fica em
`http://localhost:3000` (login com `ADMIN_USERNAME`/`ADMIN_PASSWORD`).

### 3. Teste rápido sem Instagram (endpoint síncrono)

```bash
curl -X POST "http://localhost:8000/webhook/sync?agent=secretaria" \
  -H "Content-Type: application/json" \
  -d '{"external_id":"17841400000000001","message":"Olá!"}'
```

### 4. Conecte o Instagram

Crie o app no Meta for Developers, gere o token, configure o webhook
(`https://SEU-DOMINIO/webhook/instagram?agent=secretaria`) e assine o campo
`messages`. Guia completo, com testes de verificação e de mensagem assinada:
[docs/INSTAGRAM_API.md](docs/INSTAGRAM_API.md).

## Estrutura do Projeto

```text
├── src/whatsapp_langchain/   # (nome do pacote mantido — ver "Pendências")
│   ├── agents/        # Catálogo de agentes, middleware e tools
│   ├── server/        # API FastAPI (webhook Instagram + auth + admin APIs)
│   ├── worker/        # Consumidor da fila, cliente Instagram, mídia, notificações
│   └── shared/        # Config, DB, Redis, fila, modelos, parser do payload
├── frontend/          # Admin Panel (Next.js)
├── db/migrations/     # Schema SQL (fila, conversas, identidade Instagram)
├── docs/              # Documentação técnica
├── tests/             # unit/, integration/ e stress/
└── docker-compose*.yml, Caddyfile   # Execução local e produção
```

## Documentação

- [Integração Instagram Direct](docs/INSTAGRAM_API.md)
- [Arquitetura](docs/ARCHITECTURE.md)
- [Primeiros Passos](docs/GETTING_STARTED.md)
- [Criando Agentes](docs/ADDING_AGENTS.md)
- [Banco de Dados](docs/DATABASE.md)
- [Google Calendar (agendamento)](docs/GOOGLE_CALENDAR.md)
- [Deploy](docs/DEPLOY.md)
- [Guia de debug manual](docs/guia-debug-manual.md)

## Comandos úteis

```bash
make help      # lista tudo
make test      # testes
make check     # lint + typecheck + testes
make migrate   # aplica migrações
make logs
```

## Pendências

- **Nome do pacote:** o pacote Python ainda se chama `whatsapp_langchain`
  (e o banco/serviços `whatsapp_langchain`). Foi mantido de propósito para
  limitar o risco e o tamanho da migração; renomear exige mexer em imports,
  `pyproject.toml`, `langgraph.json`, Dockerfiles, compose e no nome do banco.
- **Histórico do WhatsApp:** as conversas antigas continuam no banco
  (`channel = 'whatsapp'`), mas os contatos do Instagram começam com
  histórico e memória novos.
- **Renovação do token** do Instagram (longa duração) é manual.

## Licença

[TOPHAWKS Community License](LICENSE) - uso restrito a membros da comunidade [TOPHAWKS](https://www.rhawk.pro/comunidade).
