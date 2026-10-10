import asyncio, os
os.environ["TEAM_TOKEN"] = "tok-test"
os.environ["DATA_DIR"] = "/tmp/operario-test-data"
import httpx, pytest
from services.entrypoint import app as appmod

H = {"Authorization": "Bearer tok-test"}


@pytest.mark.asyncio
async def test_contract_auth_and_fast_post():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        assert (await c.get("/health")).status_code == 401
        assert (await c.get("/health", headers=H)).status_code == 200
        r = await c.post("/tasks", headers=H, json={"tarea": "x", "escritorio": {"url": "ws://127.0.0.1:1/w", "password": "pw-secret"}})
        assert r.status_code == 200
        tid = r.json()["task_id"]
        assert (await c.post("/tasks", headers=H, json={"tarea": "x"})).status_code == 422
        for _ in range(60):
            g = (await c.get(f"/tasks/{tid}", headers=H)).json()
            if g["estado"] != "en_curso":
                break
            await asyncio.sleep(0.5)
        assert g["estado"] == "fallida" and "pw-secret" not in g["resumen"]


@pytest.mark.asyncio
async def test_list_tasks_requires_token_and_hides_password():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        assert (await c.get("/tasks")).status_code == 401
        r = await c.get("/tasks", headers=H)
        assert r.status_code == 200 and "pw-secret" not in r.text
