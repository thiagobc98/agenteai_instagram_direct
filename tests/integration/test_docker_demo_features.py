"""Testes demonstrativos E2E com stack Docker.

Estes cenários são focados em demonstração de funcionalidades para aula:
- webhook com imagem
- webhook com áudio
- memória semântica no Postgres Store

Pré-requisito:
    docker compose up -d --build
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import psycopg
import pytest
from langchain_openai import OpenAIEmbeddings
from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.store.postgres.base import PostgresIndexConfig
from pydantic import SecretStr

from whatsapp_langchain.agents.tools import read_memory, save_memory
from whatsapp_langchain.shared.config import settings

from .helpers import (
    API_BASE_URL,
    clear_thread_checkpoints,
    get_db_url,
    send_webhook,
    wait_memory_saved,
    wait_terminal_status,
)

pytestmark = pytest.mark.docker_demo

ASSETS_DIR = Path(__file__).parents[1] / "assets"

save_memory_fn = save_memory.coroutine
read_memory_fn = read_memory.coroutine


def _make_tool_runtime(user_id: str) -> MagicMock:
    """Cria runtime fake no formato do webhook (configurable.user_id)."""
    runtime = MagicMock()
    runtime.config = {
        "configurable": {
            "user_id": user_id,
            "thread_id": f"{user_id}:secretaria",
        }
    }
    return runtime


@pytest.fixture(scope="module")
def ensure_docker_stack() -> str:
    """Valida pré-requisitos: API e DB acessíveis localmente."""
    try:
        response = httpx.get(f"{API_BASE_URL}/health", timeout=3)
        if response.status_code != 200:
            pytest.skip("API não saudável. Rode: docker compose up -d --build")
    except Exception:
        pytest.skip("API não acessível. Rode: docker compose up -d --build")

    db_url = get_db_url()
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception:
        pytest.skip("DB não acessível. Verifique docker compose e DATABASE_URL")

    return db_url


def _read_asset_base64(filename: str) -> str:
    path = ASSETS_DIR / filename
    if not path.exists():
        pytest.skip("Assets de demo ausentes em tests/assets/")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def test_demo_webhook_image_e2e(ensure_docker_stack: str):
    """Demonstra pipeline completo de imagem via webhook assíncrono."""
    sid = f"MSGIMG{uuid.uuid4().hex[:12]}"
    phone = f"+5511{uuid.uuid4().int % 10**8:08d}"

    response = send_webhook(
        phone,
        "Descreva esta imagem.",
        message_sid=sid,
        media_base64=_read_asset_base64("sample.png"),
        media_type="image/png",
    )
    assert response.status_code == 200

    status, output, error, media_type = wait_terminal_status(ensure_docker_stack, sid)
    assert media_type == "image/png"
    assert status == "done", f"Processamento de imagem falhou: {error}"
    assert output and output.strip()


def test_demo_webhook_audio_e2e(ensure_docker_stack: str):
    """Demonstra pipeline completo de áudio via webhook assíncrono."""
    sid = f"MSGAUD{uuid.uuid4().hex[:12]}"
    phone = f"+5521{uuid.uuid4().int % 10**8:08d}"

    response = send_webhook(
        phone,
        "Transcreva e responda.",
        message_sid=sid,
        media_base64=_read_asset_base64("sample.ogg"),
        media_type="audio/ogg",
    )
    assert response.status_code == 200

    status, output, error, media_type = wait_terminal_status(ensure_docker_stack, sid)
    assert media_type == "audio/ogg"
    assert status == "done", f"Processamento de áudio falhou: {error}"
    assert output and output.strip()


@pytest.mark.asyncio
async def test_demo_semantic_memory_roundtrip(ensure_docker_stack: str):
    """Demonstra roundtrip de memória por usuário no Postgres Store.

    O namespace segue o contrato do projeto: (user_id, "memories"),
    onde user_id é o telefone (mesmo identificador vindo do payload Evolution).
    """
    api_key = settings.openrouter_api_key
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY não configurada")

    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model,
        base_url=settings.openrouter_base_url,
        api_key=SecretStr(api_key.get_secret_value()),
    )
    index_config: PostgresIndexConfig = {
        "embed": embeddings,
        "dims": settings.embedding_dims,
        "fields": ["$"],
    }

    user_id = f"+55{uuid.uuid4().int % 10**11:011d}"
    runtime = _make_tool_runtime(user_id)

    async with AsyncPostgresStore.from_conn_string(
        ensure_docker_stack,
        index=index_config,
    ) as store:
        await store.setup()
        save_result = await save_memory_fn(
            "Meu nome é Ronnald e eu estudo sistemas de agentes.",
            runtime=runtime,
            store=store,
        )
        assert "sucesso" in save_result.lower()

        await save_memory_fn(
            "Prefiro exemplos práticos com testes automatizados.",
            runtime=runtime,
            store=store,
        )

        read_result = await read_memory_fn(
            "Qual é o meu nome?",
            runtime=runtime,
            store=store,
        )

        assert "memórias relevantes" in read_result.lower()
        assert "ronnald" in read_result.lower()

    with psycopg.connect(ensure_docker_stack) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM store
                WHERE prefix = %s
                """,
                (f"{user_id}.memories",),
            )
            row = cur.fetchone()
            assert row and row[0] >= 2


def test_demo_webhook_memory_recall_e2e(ensure_docker_stack: str):
    """E2E via webhook: salva memória e recupera sem histórico de thread.

    Fluxo:
    1) Mensagem A força o agente a salvar um fato único no store.
    2) Teste limpa checkpoints da thread para remover contexto conversacional.
    3) Mensagem B pede recall explícito via read_memory.
    4) Resposta final deve conter o fato salvo.
    """
    phone = f"+5531{uuid.uuid4().int % 10**8:08d}"
    thread_id = f"{phone}:secretaria"
    token = f"rhawk-{uuid.uuid4().hex[:10]}"

    sid_save = f"MSGMEM{uuid.uuid4().hex[:12]}"
    save_response = send_webhook(
        phone,
        (
            "Use a ferramenta save_memory e salve este fato sobre mim: "
            f"meu identificador secreto é {token}. "
            "Depois confirme em uma frase curta."
        ),
        message_sid=sid_save,
    )
    assert save_response.status_code == 200

    status_a, output_a, error_a, _ = wait_terminal_status(ensure_docker_stack, sid_save)
    assert status_a == "done", f"Falha ao salvar memória: {error_a}"
    assert output_a and output_a.strip()

    wait_memory_saved(ensure_docker_stack, phone, contains=token)

    # Remove histórico da thread para impedir recuperação via checkpointer.
    clear_thread_checkpoints(ensure_docker_stack, thread_id)

    sid_recall = f"MSGMEM{uuid.uuid4().hex[:12]}"
    recall_response = send_webhook(
        phone,
        (
            "Sem usar save_memory agora, use read_memory para recuperar "
            "meu identificador secreto e responda apenas com o valor."
        ),
        message_sid=sid_recall,
    )
    assert recall_response.status_code == 200

    status_b, output_b, error_b, _ = wait_terminal_status(
        ensure_docker_stack,
        sid_recall,
    )
    assert status_b == "done", f"Falha no recall de memória: {error_b}"
    assert output_b and output_b.strip()
    assert token.lower() in output_b.lower()
