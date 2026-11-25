"""Cliente do Wuzapi (WhatsApp via whatsmeow), usado só para ENVIAR avisos.

O número conectado pelo QR Code (tela "WhatsApp" do painel) manda os avisos de
mensagens novas do Direct para o celular do atendente. Não recebe mensagens:
a instância é criada sem webhook.

API REST do Wuzapi: https://github.com/asternic/wuzapi (autenticação pelo
header `token` da instância; `/admin/*` usa o token de administrador).
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog

from whatsapp_langchain.shared.config import settings

logger = structlog.get_logger()

# Limite seguro de um texto no WhatsApp (o app aceita bem mais, mas aviso é curto)
MAX_TEXT_CHARS = 4000
_NON_DIGITS = re.compile(r"\D")


class WuzapiError(Exception):
    """Wuzapi recusou o pedido (status HTTP + detalhe)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Wuzapi {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _data(response: httpx.Response) -> dict[str, Any]:
    """Corpo da resposta, com ou sem o envelope {"data": ...}."""
    try:
        body = response.json()
    except ValueError:
        return {}
    if isinstance(body, dict) and "data" in body:
        body = body["data"]
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return {}
    return body if isinstance(body, dict) else {}


def _field(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def br_number_variants(phone: str) -> list[str]:
    """Grafias possíveis de um celular brasileiro no WhatsApp.

    Contas antigas ficaram registradas sem o 9 extra (55 31 8318-1760), as
    novas com ele (55 31 98318-1760). Testar as duas evita mandar o aviso para
    um número que "não existe" no WhatsApp.
    """
    digits = _NON_DIGITS.sub("", phone)
    if len(digits) in (10, 11):
        digits = "55" + digits
    variants = [digits]
    if digits.startswith("55") and len(digits) == 13 and digits[4] == "9":
        variants.append(digits[:4] + digits[5:])
    elif digits.startswith("55") and len(digits) == 12:
        variants.append(digits[:4] + "9" + digits[4:])
    return variants


class WuzapiClient:
    """Cliente assíncrono da instância do Wuzapi.

    Args:
        base_url: URL do Wuzapi (ex: http://wuzapi:8080).
        token: Token da instância (header `token`).
    """

    def __init__(self, base_url: str, token: str, *, timeout: float = 20.0):
        if not base_url or not token:
            raise ValueError("WUZAPI_API_URL e WUZAPI_TOKEN são obrigatórios")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            response = await http.request(
                method,
                f"{self.base_url}/{path}",
                headers={"token": self.token},
                json=payload,
            )
        if not response.is_success:
            raise WuzapiError(response.status_code, response.text[:300])
        return _data(response)

    async def session_status(self) -> dict[str, Any]:
        """Situação da sessão: {"connected": bool, "logged_in": bool, "jid"}."""
        data = await self._request("GET", "session/status")
        return {
            "connected": bool(_field(data, "Connected", "connected")),
            "logged_in": bool(_field(data, "LoggedIn", "loggedIn", "logged_in")),
            "jid": str(_field(data, "Jid", "jid", "JID") or ""),
        }

    async def connect(self) -> None:
        """Liga a sessão. Sem eventos assinados: este número só envia."""
        try:
            await self._request(
                "POST", "session/connect", {"Subscribe": ["Message"], "Immediate": True}
            )
        except WuzapiError as exc:
            if "already" not in exc.detail.lower():
                raise

    async def qr_code(self) -> str:
        """QR Code para parear (data URI PNG), vazio se ainda não gerou."""
        data = await self._request("GET", "session/qr")
        return str(_field(data, "QRCode", "qrcode") or "")

    async def logout(self) -> None:
        """Desconecta o número (para conectar de novo, outro QR Code)."""
        await self._request("POST", "session/logout", {})

    async def whatsapp_jid(self, phone: str) -> str | None:
        """JID com que o número está no WhatsApp (testa com e sem o 9), ou
        None se nenhuma grafia tiver WhatsApp."""
        variants = br_number_variants(phone)
        data = await self._request("POST", "user/check", {"Phone": variants})
        users = _field(data, "Users", "users") or []
        for variant in variants:
            for user in users:
                query = _NON_DIGITS.sub("", str(_field(user, "Query", "query") or ""))
                if query == variant and _field(user, "IsInWhatsapp", "isInWhatsapp"):
                    return str(_field(user, "JID", "jid") or variant)
        return None

    async def send_text(self, phone_or_jid: str, body: str) -> str:
        """Envia um texto e devolve o id da mensagem."""
        phone = phone_or_jid.split("@")[0].split(":")[0]
        data = await self._request(
            "POST", "chat/send/text", {"Phone": phone, "Body": body[:MAX_TEXT_CHARS]}
        )
        return str(_field(data, "Id", "id") or "")


async def create_instance(
    base_url: str, admin_token: str, token: str, name: str = "berberich-avisos"
) -> None:
    """Cria a instância no Wuzapi (POST /admin/users), sem webhook."""
    async with httpx.AsyncClient(timeout=15.0) as http:
        response = await http.post(
            f"{base_url.rstrip('/')}/admin/users",
            headers={"Authorization": admin_token},
            json={"name": name, "token": token, "webhook": "", "events": "Message"},
        )
    if not response.is_success:
        raise WuzapiError(response.status_code, response.text[:300])
    logger.info("wuzapi_instance_created", name=name)


def build_wuzapi_client() -> WuzapiClient | None:
    """Cliente a partir do .env, ou None se o Wuzapi não estiver configurado."""
    token = settings.wuzapi_token.get_secret_value() if settings.wuzapi_token else ""
    if not (settings.wuzapi_api_url and token):
        return None
    return WuzapiClient(settings.wuzapi_api_url, token)
