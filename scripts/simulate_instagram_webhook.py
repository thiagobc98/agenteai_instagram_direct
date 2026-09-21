"""Simula um webhook de mensagem do Instagram, assinado como a Meta faz.

O webhook exige o header X-Hub-Signature-256 (HMAC-SHA256 do body com o App
Secret), então não dá para testá-lo direto pelo Swagger ou com um curl simples.
Este script monta o payload, assina com INSTAGRAM_APP_SECRET (lido do .env ou
do ambiente) e faz o POST.

Uso:
    python scripts/simulate_instagram_webhook.py "Olá, quero marcar consulta"
    python scripts/simulate_instagram_webhook.py "Oi" --external-id 17841400000000002
    python scripts/simulate_instagram_webhook.py "" --image-url https://exemplo.com/foto.jpg
    python scripts/simulate_instagram_webhook.py "Oi" --url https://meu-tunel.ngrok.app

Atenção: o Worker vai tentar RESPONDER de verdade ao --external-id informado.
Com um ID fictício o envio falha (a mensagem entra no fluxo de retry); use o ID
de uma conta real de teste para ver a resposta chegar, ou o endpoint
/webhook/sync para testar só o agente.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid

import httpx
from dotenv import load_dotenv

DEFAULT_EXTERNAL_ID = "17841400000000001"
BUSINESS_ACCOUNT_ID = "17841400000000000"


def build_payload(
    external_id: str,
    text: str,
    image_url: str | None = None,
    audio_url: str | None = None,
) -> dict:
    message: dict = {"mid": f"MID{uuid.uuid4().hex[:12]}"}
    if text:
        message["text"] = text

    attachments = []
    if image_url:
        attachments.append({"type": "image", "payload": {"url": image_url}})
    if audio_url:
        attachments.append({"type": "audio", "payload": {"url": audio_url}})
    if attachments:
        message["attachments"] = attachments

    now_ms = int(time.time() * 1000)
    return {
        "object": "instagram",
        "entry": [
            {
                "id": BUSINESS_ACCOUNT_ID,
                "time": now_ms,
                "messaging": [
                    {
                        "sender": {"id": external_id},
                        "recipient": {"id": BUSINESS_ACCOUNT_ID},
                        "timestamp": now_ms,
                        "message": message,
                    }
                ],
            }
        ],
    }


def sign(raw_body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("text", help='Texto da mensagem (use "" para só mídia)')
    parser.add_argument("--external-id", default=DEFAULT_EXTERNAL_ID)
    parser.add_argument("--agent", default="secretaria")
    parser.add_argument("--url", default="http://localhost:8000", help="Base da API")
    parser.add_argument("--image-url", help="URL https de uma imagem (attachment)")
    parser.add_argument("--audio-url", help="URL https de um áudio (attachment)")
    args = parser.parse_args()

    load_dotenv()
    app_secret = os.getenv("INSTAGRAM_APP_SECRET", "")
    if not app_secret:
        print("INSTAGRAM_APP_SECRET não definido (.env ou ambiente).", file=sys.stderr)
        return 1

    payload = build_payload(args.external_id, args.text, args.image_url, args.audio_url)
    raw = json.dumps(payload).encode()

    response = httpx.post(
        f"{args.url.rstrip('/')}/webhook/instagram?agent={args.agent}",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(raw, app_secret),
        },
        timeout=15,
    )
    print(response.status_code, response.text)
    return 0 if response.is_success else 1


if __name__ == "__main__":
    sys.exit(main())
