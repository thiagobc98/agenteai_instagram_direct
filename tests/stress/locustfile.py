"""Stress test do webhook do Instagram via Locust.

Simula múltiplos contatos enviando mensagens simultâneas para
/webhook/instagram, exercitando o pipeline completo: assinatura, rate limit
(Redis), debounce/fila (PostgreSQL) e worker.

IMPORTANTE: só rode contra a stack local (`make up`). Configure
LOCUST_APP_SECRET com o mesmo valor de INSTAGRAM_APP_SECRET do .env usado pela
stack — sem a assinatura correta, todas as requisições são rejeitadas com 403.
Nunca aponte isto para produção.

O Worker tenta responder cada mensagem pela Graph API da Meta. Para não gerar
chamadas reais, rode a stack com um INSTAGRAM_ACCESS_TOKEN falso (a Meta
recusa com erro 190 e nada é entregue) ou com INSTAGRAM_GRAPH_BASE_URL
apontando para um stub local. Nesse caso `failures_today` cresce porque os
envios falham — o que se avalia é a fila, o rate limit e o tempo de
processamento.

Uso:
    make stress            # modo UI (http://localhost:8089)
    make stress-headless    # modo headless, ex: 50 usuários

Direto com uv:
    uv run --extra stress locust -f tests/stress/locustfile.py --host http://localhost:8000
"""

import hashlib
import hmac
import json
import os
import time
import uuid

from locust import HttpUser, between, task

AGENT_ID = os.getenv("LOCUST_AGENT_ID", "secretaria")
APP_SECRET = os.getenv("LOCUST_APP_SECRET", os.getenv("INSTAGRAM_APP_SECRET", ""))
BUSINESS_ACCOUNT_ID = "17841400000000000"

# Pool fixo de IGSIDs — reutilizados entre requisições para exercitar
# debounce (mensagens agrupadas) e rate limit (por contato) de forma
# realista, em vez de cada requisição ser um contato "novo".
IGSID_POOL = [f"178414{n:010d}" for n in range(50)]

SAMPLE_MESSAGES = [
    "Olá, quero saber mais sobre o produto.",
    "Qual o horário de atendimento?",
    "Preciso de ajuda com meu pedido.",
    "Vocês têm desconto para pagamento à vista?",
    "Como faço para cancelar minha assinatura?",
]


def _signature(raw_body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class InstagramWebhookUser(HttpUser):
    """Simula um cliente do Instagram enviando mensagens via webhook da Meta."""

    wait_time = between(1, 3)

    @task
    def send_message(self) -> None:
        igsid = IGSID_POOL[uuid.uuid4().int % len(IGSID_POOL)]
        message = SAMPLE_MESSAGES[uuid.uuid4().int % len(SAMPLE_MESSAGES)]
        now_ms = int(time.time() * 1000)

        payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": BUSINESS_ACCOUNT_ID,
                    "time": now_ms,
                    "messaging": [
                        {
                            "sender": {"id": igsid},
                            "recipient": {"id": BUSINESS_ACCOUNT_ID},
                            "timestamp": now_ms,
                            "message": {
                                "mid": f"MID{uuid.uuid4().hex[:24]}",
                                "text": message,
                            },
                        }
                    ],
                }
            ],
        }
        raw = json.dumps(payload).encode()

        self.client.post(
            f"/webhook/instagram?agent={AGENT_ID}",
            data=raw,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _signature(raw),
            },
            name="/webhook/instagram",
        )
