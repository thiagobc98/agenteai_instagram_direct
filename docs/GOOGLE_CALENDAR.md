# Google Calendar — Setup e Ferramentas de Agendamento

Guia para conectar o agente a uma agenda do Google Calendar, permitindo
marcar, remarcar, cancelar e consultar disponibilidade de consultas.

## Visão geral

```
Paciente (Instagram Direct)
       │
       ▼
Agente (LangGraph) ──► tools/calendar.py ──► shared/google_calendar.py
                                                     │
                                                     ▼
                                          Google Calendar API
                                          (Service Account)
```

Autenticação via **Service Account** — não há tela de login/consentimento
do Google. A agenda de destino é simplesmente **compartilhada** com o
e-mail da service account, como se fosse compartilhada com outra pessoa.
Funciona tanto para uma agenda pessoal (`@gmail.com`) quanto para uma do
Google Workspace.

## 1. Criar a Service Account no Google Cloud

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/) e
   crie um projeto (ou use um existente).
2. Ative a **Google Calendar API**: menu "APIs e serviços" → "Biblioteca"
   → busque "Google Calendar API" → **Ativar**.
3. Crie a Service Account: "APIs e serviços" → "Credenciais" → **Criar
   credenciais** → **Conta de serviço**.
   - Nome: ex. `instagram-bot-agenda`
   - Não precisa conceder papéis (roles) do projeto — o acesso é dado
     diretamente na agenda, no passo 3.
4. Na lista de contas de serviço, abra a que você criou → aba **Chaves**
   → **Adicionar chave** → **Criar nova chave** → tipo **JSON**.
5. O arquivo `.json` é baixado automaticamente. **Guarde-o com cuidado** —
   ele não pode ser gerado de novo (só recriado).
6. Copie o campo `"client_email"` de dentro do JSON — algo como
   `instagram-bot-agenda@seu-projeto.iam.gserviceaccount.com`. Você vai
   precisar dele no próximo passo.

## 2. Compartilhar a agenda com a Service Account

1. Abra o [Google Agenda](https://calendar.google.com/) com a conta cuja
   agenda o bot vai gerenciar (ex: a conta da loja).
2. Nas configurações da agenda desejada (ícone de engrenagem → "Configurações
   e compartilhamento com pessoas específicas") → **Adicionar pessoas e
   grupos**.
3. Cole o `client_email` da service account (passo 1.6).
4. Permissão: **"Fazer alterações em eventos"** (necessário para criar,
   remarcar e cancelar consultas).
5. Salve.
6. Anote o **ID da agenda**: em "Integrar agenda", é o mesmo e-mail da
   conta Google (ex: `dra.luana@gmail.com`), ou "primary" se a service
   account for a própria dona da agenda (raro).

## 3. Configurar variáveis de ambiente

No `.env`, preencha:

```bash
GOOGLE_CALENDAR_ENABLED=true

# Opção A — cole o JSON inteiro em uma linha só (recomendado para Railway,
# onde montar um arquivo não é simples):
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"...iam.gserviceaccount.com", ...}

# Opção B — caminho para o arquivo .json (docker-compose local, monte o
# arquivo como volume e aponte o caminho aqui):
GOOGLE_SERVICE_ACCOUNT_FILE=/app/secrets/google-service-account.json

GOOGLE_CALENDAR_ID=dra.luana@gmail.com

BUSINESS_TIMEZONE=America/Sao_Paulo
BUSINESS_HOUR_START=9
BUSINESS_HOUR_END=18
APPOINTMENT_DURATION_MINUTES=30
```

> Preencha **uma das duas** opções de credencial. Se ambas estiverem
> preenchidas, `GOOGLE_SERVICE_ACCOUNT_JSON` tem prioridade.

Para transformar o arquivo `.json` em uma linha só (útil para colar no
Railway ou em qualquer `.env`):

```bash
python -c "import json; print(json.dumps(json.load(open('caminho/para/arquivo.json'))))"
```

Depois de configurar, reconstrua o worker (e a API, se ela também rodar
tools no futuro):

```bash
docker compose up -d --build worker
```

> Lembre-se: `docker compose restart worker` **não** é suficiente — o
> código e as variáveis de ambiente só são lidos de novo em um rebuild.
> Isso vale para qualquer alteração em `src/` ou no `.env`.

## 4. Testar

Envie mensagens no Direct da conta profissional simulando um paciente:

```
Quero marcar uma consulta
```

O agente deve perguntar data/horário, consultar `check_availability`,
confirmar e então chamar `book_appointment`. Verifique nos logs do worker:

```bash
docker compose logs -f worker | grep calendar
```

Deve aparecer `calendar_event_created` (ou `_updated`/`_deleted`) quando o
agente executar uma operação de agenda. O evento também aparece
imediatamente no Google Agenda com o resumo "Consulta - {nome do paciente}".

## 5. Como funciona por baixo dos panos

As ferramentas ficam em
[`src/whatsapp_langchain/agents/tools/calendar.py`](../src/whatsapp_langchain/agents/tools/calendar.py):

| Tool | O que faz |
|---|---|
| `get_current_date` | Retorna data/hora atual — o agente usa para resolver "hoje", "amanhã" etc. |
| `check_availability(date)` | Lista horários livres em uma data, respeitando `BUSINESS_HOUR_START/END` e `APPOINTMENT_DURATION_MINUTES`. |
| `book_appointment(patient_name, date, time, notes)` | Confere disponibilidade e cria o evento. |
| `reschedule_appointment(new_date, new_time)` | Move a próxima consulta futura do paciente. |
| `cancel_appointment()` | Cancela a próxima consulta futura do paciente. |
| `list_my_appointments()` | Lista as consultas futuras do paciente. |

O paciente é identificado pelo **ID da conta no Instagram** (IGSID, o `user_id`
injetado pelo worker — o mesmo usado pela memória semântica), não pelo nome.
Cada evento criado guarda esse ID em
`extendedProperties.private.external_id`, o que permite localizar a consulta do
paciente depois (para remarcar/cancelar) sem precisar de um banco de dados
próprio de agendamentos — a fonte da verdade é o Google Calendar.

`reschedule_appointment` e `cancel_appointment` sempre agem sobre a
**consulta futura mais próxima** do paciente. Se um paciente puder ter
múltiplas consultas futuras simultaneamente, isso é uma simplificação
consciente desta implementação — ajuste `find_events_by_external_id` em
`shared/google_calendar.py` se precisar listar/escolher entre várias.

## 6. Limitações conhecidas

- **Sem lembretes automáticos**: o projeto não envia lembrete de consulta nem
  resumo da agenda (mensagens proativas ficam sujeitas à janela de 24h do
  Instagram; veja [INSTAGRAM_API.md](INSTAGRAM_API.md)).
- **Eventos antigos (WhatsApp)**: eventos criados antes da migração guardam o
  telefone em `extendedProperties.private.phone`; eles aparecem no painel, mas
  as tools do agente só reconhecem `external_id`.

- **Sem lock de concorrência**: se dois pacientes tentarem marcar o mesmo
  horário ao mesmo tempo, ambos podem passar a checagem de disponibilidade
  antes que o primeiro evento seja criado (race condition rara, mas
  possível). Para um consultório de baixo volume isso raramente ocorre;
  se precisar de garantia forte, adicione um lock (ex: `pg_advisory_lock`
  como o já usado na fila de mensagens) em torno de `book_appointment`.
- **Um único calendário**: todas as consultas de todos os agentes que
  usarem essas tools vão para o mesmo `GOOGLE_CALENDAR_ID`.
- **Sem fuso horário por paciente**: todos os horários são interpretados em
  `BUSINESS_TIMEZONE`.
