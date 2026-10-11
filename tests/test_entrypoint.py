import asyncio, os, time
os.environ["TEAM_TOKEN"] = "tok-test"
os.environ["DATA_DIR"] = "/tmp/operario-test-data"
import httpx, pytest
from services.entrypoint import app as appmod

H = {"Authorization": "Bearer tok-test"}


@pytest.mark.asyncio
async def test_contract_auth_and_fast_post():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        assert (await c.get("/health")).json() == {"ok": True}
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


@pytest.mark.asyncio
async def test_path_spellings_and_open_liveness():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        for path in ("/health", "/health/"):
            r = await c.get(path, headers=H)
            assert r.status_code == 200 and r.json()["model_ready"] in (True, False), path
            assert (await c.get(path)).status_code == 200
        assert (await c.get("/tasks/", headers=H)).status_code == 200


@pytest.mark.asyncio
async def test_desktop_served_only_to_token_and_kept_out_of_listing_and_file():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        r = await c.post("/tasks", headers=H, json={"tarea": "x", "escritorio": {"url": "ws://127.0.0.1:1/w", "password": "pw-secret-2"}})
        tid = r.json()["task_id"]
        assert (await c.get(f"/tasks/{tid}/desktop")).status_code == 401
        d = (await c.get(f"/tasks/{tid}/desktop", headers=H)).json()
        assert d == {"url": "ws://127.0.0.1:1/w", "password": "pw-secret-2"}
        listing = (await c.get("/tasks", headers=H)).text
        assert "pw-secret-2" not in listing and "ws://127.0.0.1:1/w" in listing
        assert "pw-secret-2" not in appmod._state_file.read_text()
        await asyncio.sleep(1)


class _FakeSession:
    def __init__(self, ok=True): self.ok = ok
    def screenshot_jpeg(self, quality=80, width=None):
        if not self.ok: raise RuntimeError("gone")
        return b"\xff\xd8fake-frame\xff\xd9"


@pytest.mark.asyncio
async def test_console_page_is_public_and_screen_needs_the_token():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        page = await c.get("/console")
        assert page.status_code == 200 and "text/html" in page.headers["content-type"] and "Operario" in page.text
        assert (await c.get("/console/")).status_code == 200
        assert (await c.get("/tasks/nope/screen")).status_code == 401
        assert (await c.get("/tasks/nope/screen", headers=H)).status_code == 404


@pytest.mark.asyncio
async def test_screen_serves_the_live_frame_then_the_last_one():
    appmod._sessions["t-live"] = _FakeSession()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        r = await c.get("/tasks/t-live/screen", headers=H)
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content.startswith(b"\xff\xd8")
        assert r.headers["cache-control"] == "no-store"
        appmod._last_frame["t-live"] = b"\xff\xd8last\xff\xd9"
        appmod._sessions["t-live"] = _FakeSession(ok=False)   # the session died: fall back to the last frame
        assert (await c.get("/tasks/t-live/screen", headers=H)).content == b"\xff\xd8last\xff\xd9"
        appmod._sessions.pop("t-live", None)
        assert (await c.get("/tasks/t-live/screen", headers=H)).content == b"\xff\xd8last\xff\xd9"


@pytest.fixture
def console_env(monkeypatch):
    monkeypatch.setenv("CONSOLE_OPEN", "1")
    monkeypatch.setenv("PRACTICE_VNC_URL", "ws://127.0.0.1:1/practice")
    monkeypatch.setenv("PRACTICE_VNC_PASSWORD", "pw-practice-secret")
    appmod._console_ids.clear(); appmod._console_starts.clear()
    yield
    appmod._console_ids.clear(); appmod._console_starts.clear()


@pytest.mark.asyncio
async def test_console_mode_is_off_by_default_and_evaluator_routes_stay_token_only(monkeypatch):
    monkeypatch.delenv("CONSOLE_OPEN", raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        assert (await c.get("/console/api/config")).json() == {"open": False}
        assert (await c.post("/console/api/tasks", json={"tarea": "x"})).status_code == 404
        assert (await c.post("/tasks", json={"tarea": "x", "escritorio": {"url": "ws://h/w", "password": "p"}})).status_code == 401
        assert (await c.get("/tasks")).status_code == 401


@pytest.mark.asyncio
async def test_console_mode_runs_without_a_token_on_the_server_desktop_and_never_reveals_it(console_env):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        assert (await c.get("/console/api/config")).json() == {"open": True}
        r = await c.post("/console/api/tasks", json={"tarea": "Cuenta algo", "escritorio": {"url": "ws://evil/w", "password": "x"}})
        assert r.status_code == 200
        tid = r.json()["task_id"]
        assert appmod._desktops[tid]["url"] == "ws://127.0.0.1:1/practice"   # the browser's desktop is ignored
        for _ in range(40):
            t = (await c.get(f"/console/api/tasks/{tid}")).json()
            if t["estado"] != "en_curso": break
            await asyncio.sleep(0.5)
        body = (await c.get(f"/console/api/tasks/{tid}")).text
        assert "pw-practice-secret" not in body and "127.0.0.1:1" not in body and "evil" not in body
        # ids that the console did not create are invisible, and the evaluator list stays closed
        appmod.tasks["other"] = {"estado": "terminada", "resumen": "", "pasos": []}
        assert (await c.get("/console/api/tasks/other")).status_code == 404
        assert (await c.get("/tasks")).status_code == 401


@pytest.mark.asyncio
async def test_console_mode_guardrails_one_at_a_time_hourly_cap_and_length(console_env, monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="http://t") as c:
        appmod.tasks["busy"] = {"estado": "en_curso", "resumen": "", "pasos": []}
        appmod._console_ids.add("busy")
        assert (await c.post("/console/api/tasks", json={"tarea": "otra"})).status_code == 409
        appmod.tasks["busy"]["estado"] = "terminada"
        assert (await c.post("/console/api/tasks", json={"tarea": "x" * 501})).status_code == 422
        monkeypatch.setattr(appmod, "CONSOLE_PER_HOUR", 1)
        appmod._console_starts[:] = [time.time()]
        assert (await c.post("/console/api/tasks", json={"tarea": "ok"})).status_code == 429
