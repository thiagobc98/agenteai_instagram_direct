"""Cliente assíncrono para envio de mensagens via Instagram Messaging API.

Usa httpx para chamadas não-bloqueantes à Graph API da Meta. Autenticação via
token de acesso da conta profissional (header `Authorization: Bearer`).

Regras do canal que este módulo trata:
- Texto de no máximo 1000 bytes UTF-8 por mensagem — respostas maiores são
  divididas em várias mensagens.
- O Instagram não renderiza markdown — o texto é convertido para texto puro.
- Só é possível enviar mensagem a quem escreveu para a conta nas últimas 24h
  (janela de mensagens). `is_within_messaging_window` ajuda quem envia por
  iniciativa própria (notificações) a checar antes de tentar.

Uso:
    from whatsapp_langchain.worker.instagram_client import InstagramClient

    client = InstagramClient(access_token="...", api_version="v25.0")
    message_id = await client.send_message(to="<IGSID>", body="Olá!")
    await client.mark_seen(to="<IGSID>")
    await client.send_typing(to="<IGSID>")
"""

import re
from datetime import UTC, datetime, timedelta

import httpx
import structlog

logger = structlog.get_logger()

DEFAULT_BASE_URL = "https://graph.instagram.com"
DEFAULT_API_VERSION = "v25.0"

# Limite da API: texto UTF-8 com no máximo 1000 bytes por mensagem.
MAX_MESSAGE_BYTES = 1000

# Janela em que a conta pode responder a um usuário após a última mensagem
# dele. A margem evita enviar "no limite" e receber erro por diferença de relógio.
MESSAGING_WINDOW = timedelta(hours=24)
_WINDOW_SAFETY_MARGIN = timedelta(minutes=5)

# Códigos de erro da Graph API tratados com log dedicado.
_ERROR_CODE_TOKEN = {190}
_ERROR_SUBCODE_WINDOW = {2534022}
_ERROR_CODES_RATE_LIMIT = {4, 17, 32, 613, 80002}


class InstagramSendError(Exception):
    """Erro ao enviar mensagem via Instagram Messaging API.

    Encapsula status HTTP, código de erro da Graph API e body para facilitar
    diagnóstico.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        code: int | None = None,
        subcode: int | None = None,
    ):
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.subcode = subcode
        super().__init__(f"Instagram API error {status_code}: {detail}")

    @property
    def is_window_closed(self) -> bool:
        """True se o envio falhou por estar fora da janela de 24h."""
        return (
            self.subcode in _ERROR_SUBCODE_WINDOW
            or "outside of allowed window" in self.detail.lower()
        )

    @property
    def is_token_invalid(self) -> bool:
        """True se o token de acesso expirou ou é inválido."""
        return self.code in _ERROR_CODE_TOKEN

    @property
    def is_rate_limited(self) -> bool:
        """True se a Graph API limitou a taxa de chamadas."""
        return self.status_code == 429 or self.code in _ERROR_CODES_RATE_LIMIT


def is_within_messaging_window(
    last_inbound_at: datetime | None, now: datetime | None = None
) -> bool:
    """Indica se ainda é possível enviar mensagem a um usuário.

    Args:
        last_inbound_at: Momento da última mensagem recebida dele (None se
            nunca escreveu — nesse caso não é possível enviar).
        now: Momento de referência (default: agora, UTC).
    """
    if last_inbound_at is None:
        return False
    now = now or datetime.now(UTC)
    if last_inbound_at.tzinfo is None:
        last_inbound_at = last_inbound_at.replace(tzinfo=UTC)
    return now - last_inbound_at < MESSAGING_WINDOW - _WINDOW_SAFETY_MARGIN


_MD_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)


def to_plain_text(text: str) -> str:
    """Remove marcações de markdown que o Instagram exibiria literalmente."""
    text = _MD_BOLD.sub(r"\2", text)
    text = _MD_HEADING.sub("", text)
    return text.replace("`", "").strip()


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _hard_split(text: str, limit: int) -> list[str]:
    """Divide `text` em pedaços de até `limit` bytes sem quebrar caracteres."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for char in text:
        char_size = _byte_len(char)
        if size + char_size > limit:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += char_size
    if current:
        chunks.append("".join(current))
    return chunks


def split_message(text: str, limit: int = MAX_MESSAGE_BYTES) -> list[str]:
    """Divide um texto em mensagens de até `limit` bytes UTF-8.

    Prefere quebrar em parágrafos, depois em linhas e por fim em palavras;
    só corta no meio de uma palavra se ela sozinha excede o limite.
    """
    text = text.strip()
    if not text:
        return []
    if _byte_len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for separator in ("\n\n", "\n", " "):
        if separator not in text:
            continue
        pieces = text.split(separator)
        if all(_byte_len(p) <= limit for p in pieces):
            for piece in pieces:
                candidate = f"{current}{separator}{piece}" if current else piece
                if _byte_len(candidate) <= limit:
                    current = candidate
                else:
                    flush()
                    current = piece
            flush()
            return chunks

    for piece in _hard_split(text, limit):
        if piece.strip():
            chunks.append(piece.strip())
    return chunks


class InstagramClient:
    """Cliente assíncrono para a Instagram Messaging API.

    Args:
        access_token: Token de acesso da conta profissional.
        api_version: Versão da Graph API (ex: "v25.0").
        base_url: Host da Graph API (graph.instagram.com ou graph.facebook.com).

    Exemplo:
        >>> client = InstagramClient("token", api_version="v25.0")
        >>> await client.send_message("<IGSID>", "Olá!")
    """

    def __init__(
        self,
        access_token: str,
        api_version: str = DEFAULT_API_VERSION,
        base_url: str = DEFAULT_BASE_URL,
    ):
        if not access_token:
            raise ValueError("access_token não pode ser vazio")
        if not api_version:
            raise ValueError("api_version não pode ser vazio")
        if not base_url:
            raise ValueError("base_url não pode ser vazio")

        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.url = f"{self.base_url}/{api_version}/me/messages"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    async def _post(self, body: dict, *, timeout: float) -> httpx.Response:
        async with httpx.AsyncClient() as http:
            return await http.post(
                self.url, headers=self.headers, json=body, timeout=timeout
            )

    @staticmethod
    def _error_from_response(response: httpx.Response) -> InstagramSendError:
        code = subcode = None
        detail = response.text[:500]
        try:
            data = response.json()
        except ValueError:
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            code = error.get("code")
            subcode = error.get("error_subcode")
            detail = str(error.get("message") or detail)[:500]
        return InstagramSendError(
            response.status_code,
            detail,
            code=code if isinstance(code, int) else None,
            subcode=subcode if isinstance(subcode, int) else None,
        )

    def _log_send_error(self, to: str, error: InstagramSendError) -> None:
        if error.is_token_invalid:
            event = "instagram_token_invalid"
        elif error.is_window_closed:
            event = "instagram_window_closed"
        elif error.is_rate_limited:
            event = "instagram_rate_limited"
        else:
            event = "instagram_send_failed"
        logger.error(
            event,
            to=to,
            status_code=error.status_code,
            code=error.code,
            subcode=error.subcode,
            detail=error.detail,
        )

    async def _send_text(self, to: str, text: str) -> str:
        response = await self._post(
            {"recipient": {"id": to}, "message": {"text": text}}, timeout=15.0
        )

        if not response.is_success:
            error = self._error_from_response(response)
            self._log_send_error(to, error)
            raise error

        data = response.json()
        message_id = ""
        if isinstance(data, dict):
            message_id = data.get("message_id", "") or ""
        return message_id

    async def send_message(self, to: str, body: str) -> str:
        """Envia mensagem de texto pelo Instagram Direct.

        Converte o texto para texto puro e divide em várias mensagens se
        passar do limite de 1000 bytes.

        Args:
            to: IGSID do destinatário.
            body: Texto da mensagem a enviar.

        Returns:
            ID (mid) da última mensagem enviada, ou string vazia se ausente.

        Raises:
            InstagramSendError: Se a API retornar erro (4xx/5xx).
        """
        parts = split_message(to_plain_text(body))
        if not parts:
            raise ValueError("body não pode ser vazio")

        message_id = ""
        for part in parts:
            message_id = await self._send_text(to, part)

        logger.info(
            "instagram_message_sent",
            to=to,
            message_id=message_id,
            parts=len(parts),
        )
        return message_id

    async def get_user_profile(self, igsid: str) -> dict[str, str | None] | None:
        """Busca o perfil público de um contato (User Profile API, best-effort).

        Só funciona para quem já enviou mensagem à conta. Falhas (token,
        permissão, rede) retornam None: o painel cai para o ID numérico.

        Returns:
            Dict com `username`, `name` e `profile_pic_url`, ou None.
        """
        url = f"{self.base_url}/{self.api_version}/{igsid}"
        try:
            async with httpx.AsyncClient() as http:
                response = await http.get(
                    url,
                    headers={"Authorization": self.headers["Authorization"]},
                    params={"fields": "name,username,profile_pic"},
                    timeout=8.0,
                )
        except Exception as exc:
            logger.warning("instagram_profile_error", igsid=igsid, error=str(exc))
            return None

        if not response.is_success:
            logger.warning(
                "instagram_profile_failed",
                igsid=igsid,
                status_code=response.status_code,
                detail=response.text[:200],
            )
            return None

        data = response.json()
        return {
            "username": data.get("username") or None,
            "name": data.get("name") or None,
            "profile_pic_url": data.get("profile_pic") or None,
        }

    async def _send_action(self, to: str, action: str) -> bool:
        """Envia um sender_action (best-effort): falha não interrompe o fluxo."""
        try:
            response = await self._post(
                {"recipient": {"id": to}, "sender_action": action}, timeout=5.0
            )

            if response.is_success:
                logger.info("instagram_sender_action_sent", to=to, action=action)
                return True

            logger.warning(
                "instagram_sender_action_failed",
                to=to,
                action=action,
                status_code=response.status_code,
                detail=response.text[:200],
            )
            return False
        except Exception as exc:
            logger.warning(
                "instagram_sender_action_error", to=to, action=action, error=str(exc)
            )
            return False

    async def send_typing(self, to: str) -> bool:
        """Mostra o indicador de digitação (`typing_on`, best-effort).

        O indicador some sozinho quando a mensagem de resposta é enviada.
        """
        return await self._send_action(to, "typing_on")

    async def mark_seen(self, to: str) -> bool:
        """Marca a última mensagem do usuário como vista (best-effort)."""
        return await self._send_action(to, "mark_seen")
