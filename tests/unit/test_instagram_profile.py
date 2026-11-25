"""Testes de InstagramClient.get_user_profile (User Profile API).

Usa httpx mock: nenhuma chamada HTTP real.
"""

import httpx
import pytest

from whatsapp_langchain.worker.instagram_client import InstagramClient

TEST_TOKEN = "test-access-token"
IGSID = "17841400000000001"


@pytest.fixture
def client():
    return InstagramClient(access_token=TEST_TOKEN, api_version="v25.0")


def patch_async_client(monkeypatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self_client, **kwargs):
        kwargs["transport"] = transport
        original_init(self_client, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def fixed_response(status_code: int, body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status_code, json=body))


class TestGetUserProfile:
    async def test_returns_username_name_and_picture(self, client, monkeypatch):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["host"] = request.url.host
            seen["fields"] = request.url.params["fields"]
            seen["auth"] = request.headers["authorization"]
            return httpx.Response(
                200,
                json={
                    "name": "Maria Silva",
                    "username": "maria.silva",
                    "profile_pic": "https://cdn.example/p.jpg",
                    "id": IGSID,
                },
            )

        patch_async_client(monkeypatch, httpx.MockTransport(handler))

        profile = await client.get_user_profile(IGSID)

        assert profile == {
            "username": "maria.silva",
            "name": "Maria Silva",
            "profile_pic_url": "https://cdn.example/p.jpg",
        }
        assert seen["host"] == "graph.instagram.com"
        assert seen["path"] == f"/v25.0/{IGSID}"
        assert seen["fields"] == "name,username,profile_pic"
        assert seen["auth"] == f"Bearer {TEST_TOKEN}"

    async def test_missing_fields_become_none(self, client, monkeypatch):
        patch_async_client(monkeypatch, fixed_response(200, {"id": IGSID}))

        assert await client.get_user_profile(IGSID) == {
            "username": None,
            "name": None,
            "profile_pic_url": None,
        }

    async def test_api_error_returns_none(self, client, monkeypatch):
        patch_async_client(
            monkeypatch, fixed_response(400, {"error": {"code": 100, "message": "x"}})
        )

        assert await client.get_user_profile(IGSID) is None

    async def test_network_error_returns_none(self, client, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sem rede")

        patch_async_client(monkeypatch, httpx.MockTransport(handler))

        assert await client.get_user_profile(IGSID) is None
