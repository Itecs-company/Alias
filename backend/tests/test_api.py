from io import BytesIO

import httpx
import pandas as pd
import pytest

from app.api import router as router_module
from app.main import app, on_startup
from app.services.optimized_search_engine import OptimizedPartSearchEngine
from tests.conftest import FakeProvider, hit


@pytest.fixture
async def client(db_session):
    await on_startup()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _token(client, username="operator", password="operator-pass") -> str:
    response = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _auth(client, **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _token(client, **kwargs)}"}


async def test_login_rules(client):
    assert (await client.post("/api/auth/login", json={"username": "operator", "password": "wrong"})).status_code == 401
    # Раньше пароль "Admin2025" принимался всегда, даже если в .env задан другой
    assert (await client.post("/api/auth/login", json={"username": "admin", "password": "Admin2025"})).status_code == 401
    admin = await client.post("/api/auth/login", json={"username": "admin", "password": "S3cure-admin"})
    assert admin.json()["role"] == "admin"
    assert (await client.get("/api/parts")).status_code == 401


async def test_credentials_change_is_persistent(client):
    admin = await _auth(client, username="admin", password="S3cure-admin")
    response = await client.post("/api/auth/credentials", json={"username": "newop", "password": "newpass1"}, headers=admin)
    assert response.status_code == 200
    # Старые учётные данные больше не работают — даже после перезапуска
    await on_startup()
    assert (await client.post("/api/auth/login", json={"username": "operator", "password": "operator-pass"})).status_code == 401
    assert await _token(client, username="newop", password="newpass1")


async def test_parts_upload_and_export(client):
    headers = await _auth(client)
    first = await client.post("/api/parts", json={"part_number": " LM317T ", "manufacturer_hint": "ST"}, headers=headers)
    second = await client.post("/api/parts", json={"part_number": "lm317t", "manufacturer_hint": "TI"}, headers=headers)
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["submitted_manufacturer"] == "TI"

    frame = pd.DataFrame({"Article": [6030646, "NE555P", "NE555P", None], "Req.Mnfc": ["Bosch", "TI", "TI", "x"]})
    buffer = BytesIO()
    frame.to_excel(buffer, index=False)
    files = {"file": ("parts.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    upload = await client.post("/api/upload", files=files, headers=headers)
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert [item["part_number"] for item in body["items"]] == ["6030646", "NE555P"]
    assert body["items"][0]["manufacturer_hint"] == "Bosch"

    bad = await client.post("/api/upload", files={"file": ("bad.xlsx", b"not excel", "application/octet-stream")}, headers=headers)
    assert bad.status_code == 400

    parts = (await client.get("/api/parts", headers=headers)).json()
    assert [part["part_number"] for part in parts] == ["LM317T", "6030646", "NE555P"]

    export = await client.get("/api/export/excel", headers=headers)
    url = export.json()["url"]
    download = await client.get(url, headers=headers)
    assert download.status_code == 200 and download.content[:2] == b"PK"
    pdf = await client.get("/api/export/pdf", headers=headers)
    assert (await client.get(pdf.json()["url"], headers=headers)).content[:4] == b"%PDF"


async def test_download_rejects_path_traversal(client):
    headers = await _auth(client)
    assert (await client.get("/api/download/..%2F..%2Fetc%2Fpasswd", headers=headers)).status_code == 404
    assert (await client.get("/api/download/..", headers=headers)).status_code == 404
    # Статический каталог больше не отдаётся без авторизации
    assert (await client.get("/storage/export.xlsx")).status_code == 404


async def test_search_endpoint(client, monkeypatch):
    provider = FakeProvider("web", {"NE555P": [
        hit("NE555 | TI.com", "https://www.ti.com/product/NE555", "NE555P precision timer"),
        hit("NE555P Texas Instruments | Mouser", "https://www.mouser.com/ProductDetail/Texas-Instruments/NE555P"),
    ]})

    def factory(session):
        return OptimizedPartSearchEngine(session, web_providers=[provider], serpapi_provider=None, use_ai=False)

    monkeypatch.setattr(router_module, "OptimizedPartSearchEngine", factory)
    headers = await _auth(client)
    response = await client.post(
        "/api/search", json={"items": [{"part_number": "NE555P", "manufacturer_hint": "TI"}], "debug": False}, headers=headers
    )
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["manufacturer_name"] == "Texas Instruments"
    assert result["match_status"] == "matched"

    parts = (await client.get("/api/parts", headers=headers)).json()
    assert parts[0]["search_stage"] == "Internet"
    assert [stage["name"] for stage in parts[0]["stage_history"]] == ["Internet", "googlesearch", "OpenAI"]

    empty = await client.post("/api/search", json={"items": [{"part_number": "   "}]}, headers=headers)
    assert empty.status_code == 422


async def test_settings_admin_only(client):
    user = await _auth(client)
    assert (await client.get("/api/settings", headers=user)).status_code == 403
    admin = await _auth(client, username="admin", password="S3cure-admin")
    settings = (await client.get("/api/settings", headers=admin)).json()
    assert settings["telegram_enabled"] is False
    updated = await client.put("/api/settings", json={"telegram_chat_id": " 123 "}, headers=admin)
    assert updated.json()["telegram_chat_id"] == "123"
    test = await client.post("/api/settings/test-telegram", json={}, headers=admin)
    assert test.status_code == 400  # токен не задан — понятная ошибка вместо 500
