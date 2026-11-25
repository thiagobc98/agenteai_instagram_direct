"""Agente de rascunhos de resposta a comentários do Instagram.

Não é um agente do catálogo (LangGraph com conversa e ferramentas): é uma
única chamada ao modelo por comentário, que devolve o rascunho público e o
privado em JSON. O rascunho fica aguardando aprovação no painel.

Uso:
    from whatsapp_langchain.agents.comments import generate_draft

    draft = await generate_draft(
        comment_text="Tem no 36?",
        from_username="fulana",
        post_caption="Scarpin nude...",
        is_reply=False,
    )
"""

from whatsapp_langchain.agents.comments.drafter import (
    CommentDraft,
    DraftParseError,
    generate_draft,
    parse_draft,
)

__all__ = ["CommentDraft", "DraftParseError", "generate_draft", "parse_draft"]
