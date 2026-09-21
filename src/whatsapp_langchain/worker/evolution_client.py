"""Cliente assíncrono para envio de mensagens WhatsApp via Evolution API.

Usa httpx para chamadas não-bloqueantes à API REST do Evolution API v2,
auto-hospedado na VPS do usuário. Autenticação via header `apikey`
(chave da instância).

Uso:
    from whatsapp_langchain.worker.evolution_client import EvolutionClient

    client = EvolutionClient(
        base_url="https://evo.seudominio.com",
        api_key="sua-api-key",
        instance="minha-instancia",
    )
    message_id = await client.send_message(to="+5511999999999", body="Olá!")
    await client.send_typing(to="+5511999999999")
"""

import httpx
import structlog

logger = structlog.get_logger()


class EvolutionSendError(Exception):
    """Erro ao enviar mensagem via Evolution API.

    Encapsula status HTTP e body de erro para facilitar diagnóstico.
    """

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Evolution API error {status_code}: {detail}")


def _normalize_number(to: str) -> str:
    """Remove '+' e caracteres não numéricos — Evolution espera só dígitos."""
    return "".join(c for c in to if c.isdigit())


class EvolutionClient:
    """Cliente assíncrono para envio de mensagens WhatsApp via Evolution API.

    Encapsula autenticação (header apikey) e chamadas HTTP à instância
    Evolution API v2 configurada.

    Args:
        base_url: URL base da instância Evolution (ex: https://evo.dominio.com).
        api_key: apikey da instância.
        instance: Nome da instância conectada ao WhatsApp.

    Exemplo:
        >>> client = EvolutionClient("https://evo.dominio.com", "key123", "minha")
        >>> await client.send_message("+5511999999999", "Olá!")
    """

    def __init__(self, base_url: str, api_key: str, instance: str):
        if not base_url:
            raise ValueError("base_url não pode ser vazio")
        if not api_key:
            raise ValueError("api_key não pode ser vazio")
        if not instance:
            raise ValueError("instance não pode ser vazio")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.instance = instance
        self.headers = {"apikey": api_key, "Content-Type": "application/json"}

    async def send_message(self, to: str, body: str) -> str:
        """Envia mensagem de texto via Evolution API (sendText).

        Args:
            to: Número destino em E.164 (ex: +5511999999999).
            body: Texto da mensagem a enviar.

        Returns:
            ID da mensagem criada (key.id), ou string vazia se ausente.

        Raises:
            EvolutionSendError: Se a API retornar erro (4xx/5xx).
        """
        url = f"{self.base_url}/message/sendText/{self.instance}"

        async with httpx.AsyncClient() as http:
            response = await http.post(
                url,
                headers=self.headers,
                json={
                    "number": _normalize_number(to),
                    "text": body,
                },
                timeout=15.0,
            )

        if not response.is_success:
            detail = response.text[:500]
            logger.error(
                "evolution_send_failed",
                to=to,
                status_code=response.status_code,
                detail=detail,
            )
            raise EvolutionSendError(response.status_code, detail)

        data = response.json()
        message_id = ""
        if isinstance(data, dict):
            key = data.get("key")
            if isinstance(key, dict):
                message_id = key.get("id", "") or ""

        logger.info("evolution_message_sent", to=to, message_id=message_id)
        return message_id

    async def send_typing(self, to: str, duration_ms: int = 3000) -> bool:
        """Envia indicador de digitação via Evolution API (best-effort).

        Usa /chat/sendPresence com presence="composing" pelo tempo
        indicado. Falha não interrompe o processamento — best-effort.

        Args:
            to: Número destino em E.164.
            duration_ms: Tempo em ms que o indicador fica ativo. Default: 3000.

        Returns:
            True se o indicador foi enviado, False caso contrário.
        """
        url = f"{self.base_url}/chat/sendPresence/{self.instance}"

        try:
            async with httpx.AsyncClient() as http:
                response = await http.post(
                    url,
                    headers=self.headers,
                    json={
                        "number": _normalize_number(to),
                        "presence": "composing",
                        "delay": duration_ms,
                    },
                    timeout=5.0,
                )

            if response.is_success:
                logger.info("evolution_typing_sent", to=to)
                return True

            logger.warning(
                "evolution_typing_failed",
                to=to,
                status_code=response.status_code,
                detail=response.text[:200],
            )
            return False
        except Exception as exc:
            logger.warning("evolution_typing_error", to=to, error=str(exc))
            return False
