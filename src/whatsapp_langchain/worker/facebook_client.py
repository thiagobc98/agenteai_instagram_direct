"""Cliente da Graph API do Facebook para a Página da loja (comentários).

Segurança:
- O Page Access Token vai no header `Authorization` (nunca na URL: URLs
  acabam em logs de proxy e mensagens de erro).
- Cada chamada leva `appsecret_proof` (HMAC-SHA256 do token com o App
  Secret) quando o App Secret está configurado. Assim, um token vazado não
  serve sozinho: a Graph API recusa chamadas sem a prova (ative "Exigir
  prova do segredo do app" nas configurações avançadas do app).
- Erros da Graph API viram `FacebookGraphError` com a mensagem da Meta, sem
  o token. Os logs nunca registram o token nem o corpo das mensagens.

Os posts da Página são convertidos para o mesmo formato das postagens do
Instagram (`id`, `caption`, `media_url`, `permalink`, `timestamp`...), para
reaproveitar o banco e a tela de comentários.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx
import structlog

from whatsapp_langchain.shared.config import settings
from whatsapp_langchain.worker.instagram_client import to_plain_text

logger = structlog.get_logger()

GRAPH_BASE_URL = "https://graph.facebook.com"

# Limites da Meta: resposta a comentário (8000) e mensagem do Messenger (2000).
# A resposta pública usa o mesmo teto do Instagram (2200) para o painel ter
# uma regra só.
MAX_REPLY_CHARS = 2200
MAX_MESSENGER_CHARS = 2000
# Teto de páginas ao ler comentários de um post (100 por página)
MAX_COMMENT_PAGES = 5

# Códigos da Graph API
_TOKEN_INVALID = {190}
_PERMISSION = {10, 200, 3}


class FacebookGraphError(Exception):
    """A Graph API do Facebook recusou o pedido."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        code: int | None = None,
        subcode: int | None = None,
    ):
        super().__init__(f"Facebook API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.subcode = subcode

    @property
    def is_token_invalid(self) -> bool:
        return self.code in _TOKEN_INVALID

    @property
    def is_permission_error(self) -> bool:
        # 200-299: família de erros de permissão da Graph API
        code = self.code
        return code in _PERMISSION or (code is not None and 200 <= code < 300)


def appsecret_proof(access_token: str, app_secret: str) -> str:
    """Prova do segredo do app exigida pela Graph API (HMAC-SHA256)."""
    return hmac.new(
        app_secret.encode(), access_token.encode(), hashlib.sha256
    ).hexdigest()


def post_to_media(post: dict[str, Any]) -> dict[str, Any]:
    """Converte um post da Página para o formato de postagem do Instagram."""
    summary = (post.get("comments") or {}).get("summary") or {}
    picture = post.get("full_picture")
    return {
        "id": post.get("id"),
        "caption": post.get("message") or post.get("story"),
        "media_type": "FACEBOOK_POST",
        "media_url": picture,
        "thumbnail_url": picture,
        "permalink": post.get("permalink_url"),
        "timestamp": post.get("created_time"),
        "comments_count": summary.get("total_count"),
    }


class FacebookPageClient:
    """Cliente assíncrono da Página (Page Access Token).

    Args:
        page_id: ID da Página.
        access_token: Page Access Token.
        app_secret: App Secret do app Meta (para o appsecret_proof). Opcional,
            mas recomendado.
        api_version: Versão da Graph API (ex: "v25.0").
    """

    def __init__(
        self,
        page_id: str,
        access_token: str,
        *,
        app_secret: str = "",
        api_version: str = "v25.0",
        base_url: str = GRAPH_BASE_URL,
        timeout: float = 20.0,
    ):
        if not page_id or not access_token:
            raise ValueError(
                "FACEBOOK_PAGE_ID e FACEBOOK_PAGE_ACCESS_TOKEN são obrigatórios"
            )
        self.page_id = page_id
        self._token = access_token
        self._proof = appsecret_proof(access_token, app_secret) if app_secret else None
        self.api_version = api_version
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __repr__(self) -> str:  # nunca expõe o token
        return f"FacebookPageClient(page_id={self.page_id!r})"

    # --- HTTP -------------------------------------------------------------------

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(extra or {})
        if self._proof:
            params["appsecret_proof"] = self._proof
        return params

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            response = await http.request(
                method,
                f"{self.base_url}/{self.api_version}/{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                params=self._params(params),
                json=json,
            )
        if not response.is_success:
            raise self._error(response, path)
        data = response.json()
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _error(response: httpx.Response, path: str) -> FacebookGraphError:
        try:
            err = (response.json() or {}).get("error") or {}
        except ValueError:
            err = {}
        error = FacebookGraphError(
            response.status_code,
            str(err.get("message") or response.text[:300]),
            code=err.get("code"),
            subcode=err.get("error_subcode"),
        )
        # Só o caminho (sem token, sem parâmetros) e o código do erro
        logger.warning(
            "facebook_graph_error",
            path=path.split("?")[0],
            status=error.status_code,
            code=error.code,
            subcode=error.subcode,
        )
        return error

    # --- Página e posts ---------------------------------------------------------

    async def get_page(self) -> dict[str, Any]:
        """ID e nome da Página do token (`GET /me`)."""
        return await self._request("GET", "me", params={"fields": "id,name"})

    async def list_posts(self, limit: int = 25) -> list[dict[str, Any]]:
        """Posts publicados da Página, já no formato de postagem."""
        data = await self._request(
            "GET",
            f"{self.page_id}/published_posts",
            params={
                "fields": "id,message,story,created_time,permalink_url,"
                "full_picture,comments.summary(total_count).limit(0)",
                "limit": min(limit, 100),
            },
        )
        return [post_to_media(p) for p in data.get("data") or [] if p.get("id")]

    async def get_post(self, post_id: str) -> dict[str, Any]:
        post = await self._request(
            "GET",
            post_id,
            params={
                "fields": "id,message,story,created_time,permalink_url,"
                "full_picture,comments.summary(total_count).limit(0)"
            },
        )
        return post_to_media(post)

    async def list_comments(self, post_id: str) -> list[dict[str, Any]]:
        """Comentários do post (inclusive respostas), mais antigos antes.

        `filter=stream` traz as respostas junto, cada uma com `parent`.
        Pagina pelo cursor `after` (sem seguir a URL `next` da Meta, que
        poderia carregar credenciais).
        """
        comments: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(MAX_COMMENT_PAGES):
            params: dict[str, Any] = {
                "fields": "id,message,from{id,name},created_time,parent{id}",
                "filter": "stream",
                "order": "chronological",
                "limit": 100,
            }
            if after:
                params["after"] = after
            data = await self._request("GET", f"{post_id}/comments", params=params)
            comments += [c for c in data.get("data") or [] if c.get("id")]
            paging = data.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not paging.get("next") or not after:
                break
        return comments

    # --- Respostas --------------------------------------------------------------

    async def reply_to_comment(self, comment_id: str, text: str) -> str:
        """Resposta pública ao comentário (`POST /{comment_id}/comments`)."""
        message = to_plain_text(text)[:MAX_REPLY_CHARS]
        if not message:
            raise ValueError("Resposta vazia")
        data = await self._request(
            "POST", f"{comment_id}/comments", json={"message": message}
        )
        return str(data.get("id") or "")

    async def send_private_reply(self, comment_id: str, text: str) -> str:
        """Mensagem privada no Messenger de quem comentou (private reply).

        Só uma por comentário, até 7 dias depois dele; outras mensagens só
        depois que a pessoa responder.
        """
        message = to_plain_text(text)[:MAX_MESSENGER_CHARS]
        if not message:
            raise ValueError("Mensagem vazia")
        data = await self._request(
            "POST",
            f"{self.page_id}/messages",
            json={
                "recipient": {"comment_id": comment_id},
                "message": {"text": message},
            },
        )
        return str(data.get("message_id") or data.get("id") or "")


def build_facebook_client() -> FacebookPageClient | None:
    """Cliente a partir do .env, ou None se a Página não estiver configurada."""
    token = settings.facebook_page_access_token
    if not settings.facebook_page_id or token is None or not token.get_secret_value():
        return None
    secret = settings.facebook_app_secret
    return FacebookPageClient(
        settings.facebook_page_id,
        token.get_secret_value(),
        app_secret=secret.get_secret_value() if secret else "",
        api_version=settings.facebook_graph_api_version,
    )
