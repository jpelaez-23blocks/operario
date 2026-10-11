"""Operario entrypoint: the contract with the evaluator.

GET  /health          -> 200 when ready (Bearer team token)
POST /tasks           -> {"task_id": "..."} in <2 s; work continues in the background (Bearer)
GET  /tasks/{task_id} -> {"estado": "en_curso|terminada|fallida", "resumen": "..."} (Bearer)

Each task has a hard 5-minute window. The watchdog cuts VNC input at SOFT_CUT seconds and
the instant a terminal state is set, so the agent never touches the next task's desktop.
"""
import asyncio
import hmac
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from packages.agent_loop.loop import AgentLoop, Outcome
from packages.model_gateway.gateway import BudgetExceeded, Gateway
from packages.summary_composer.composer import Scrubber, compose
from packages.vnc_driver.session import VncError, VncSession

log = logging.getLogger("operario")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

TEAM_TOKEN = os.environ.get("TEAM_TOKEN", "")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
TASK_LIMIT = float(os.environ.get("TASK_LIMIT_S", "300"))
SOFT_CUT = float(os.environ.get("SOFT_CUT_S", "270"))      # ~4:30 cut VNC input
HARD_END = float(os.environ.get("HARD_END_S", "285"))      # declare terminal before the evaluator stops polling
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "6"))

app = FastAPI(title="Operario")
# The Talk to My App page calls the API from a browser. Auth is a Bearer header, not cookies,
# so a wildcard origin adds no cookie exposure. Set CORS_ORIGINS (comma list) to restrict it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


class NormalizePath:
    """Collapse repeated slashes and drop a trailing slash, so `//health` and `/tasks/` work."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = re.sub(r"/{2,}", "/", scope["path"])
            if len(path) > 1:
                path = path.rstrip("/") or "/"
            scope = dict(scope, path=path, raw_path=path.encode())
        await self.inner(scope, receive, send)
gw = Gateway()
tasks: dict[str, dict] = {}
_sem = asyncio.Semaphore(int(os.environ.get("MAX_CONCURRENT", "6")))
_bg: set = set()
# Desktop address and password per task, in memory only: never written to the registry file, never logged,
# never in a resumen. Served only to the team token so a run's tasks can be replayed on the same desktop.
_desktops: dict[str, dict] = {}
# Live view: the VNC session of each running task and the last frame of each finished one (memory only).
_sessions: dict[str, VncSession] = {}
_last_frame: dict[str, bytes] = {}
LIVE_MAX_FRAMES = 40
CONSOLE_HTML = Path(__file__).resolve().parents[2] / "apps" / "talk-to-my-app" / "talk-to-my-app.html"
_state_file = DATA_DIR / "tasks.json"


def persist() -> None:
    """Write the registry on every state transition (atomic rename)."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        public = dict(tasks)
        tmp = _state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(public))
        tmp.replace(_state_file)
    except OSError:
        log.exception("persist failed")


@app.on_event("startup")
async def _startup() -> None:
    """Reload the registry from disk; tasks that were running at a restart become fallida."""
    if _state_file.exists():
        try:
            for k, v in json.loads(_state_file.read_text()).items():
                if v["estado"] == "en_curso":
                    v = {**v, "estado": "fallida", "resumen": "El servicio se reinició durante la tarea."}
                tasks[k] = v
        except (OSError, ValueError):
            log.exception("could not reload registry")


def bearer(authorization: str = Header("")) -> None:
    """Reject the request unless it carries the team token as a Bearer header."""
    if not TEAM_TOKEN or not hmac.compare_digest(authorization, f"Bearer {TEAM_TOKEN}"):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health(authorization: str = Header("")):
    """Liveness is open (a bare 200). Diagnostics need the token."""
    if not TEAM_TOKEN or not hmac.compare_digest(authorization, f"Bearer {TEAM_TOKEN}"):
        return {"ok": True}
    missing = [n for n in ("OPENROUTER_API_KEY", "MODEL_FAST", "MODEL_STRONG") if not os.environ.get(n)]
    return {"ok": True, "model_ready": gw.ready, "missing_env": missing,
            "en_curso": sum(1 for t in tasks.values() if t["estado"] == "en_curso")}


def _valid_desktop(d) -> bool:
    """True when the desktop object has a ws or wss URL and a string password."""
    if not isinstance(d, dict) or not d.get("url") or not isinstance(d.get("password", ""), str):
        return False
    return urlparse(str(d["url"])).scheme in ("ws", "wss")


def _start_task(tarea: str, url: str, password: str) -> str:
    """Register a task and start it in the background; returns the task id."""
    task_id = uuid.uuid4().hex
    tasks[task_id] = {"estado": "en_curso", "resumen": "", "tarea": tarea[:500], "inicio": time.time(), "pasos": [],
                      "escritorio_url": str(url)[:300]}
    _desktops[task_id] = {"url": str(url), "password": password}
    persist()
    t = asyncio.create_task(_run(task_id, tarea.strip(), url, password))
    _bg.add(t)
    t.add_done_callback(_bg.discard)
    return task_id


@app.post("/tasks", dependencies=[Depends(bearer)])
async def create_task(payload: dict):
    """Validate the task and desktop, register the task and start it in the background; answers with the task id at once."""
    tarea, desk = payload.get("tarea"), payload.get("escritorio")
    if not isinstance(tarea, str) or not tarea.strip() or not _valid_desktop(desk):
        raise HTTPException(status_code=422, detail="se requiere tarea y escritorio {url, password}")
    return {"task_id": _start_task(tarea, desk["url"], desk.get("password", ""))}


# ---- Console mode (quick proof of concept): no typing, the practice desktop comes from the server ----------------
# Off unless CONSOLE_OPEN=1. These routes never accept a desktop from the browser: they always use the server's own
# PRACTICE_VNC_URL / PRACTICE_VNC_PASSWORD, so they cannot be pointed at another host. The evaluator routes above
# stay token-only. Guardrails: one console task at a time, a per-hour cap, short task text, ids the console created.
CONSOLE_PER_HOUR = int(os.environ.get("CONSOLE_PER_HOUR", "30"))
_console_ids: set[str] = set()
_console_starts: list[float] = []


def _console_open() -> bool:
    return os.environ.get("CONSOLE_OPEN", "") == "1"


def _console_desktop() -> Optional[dict]:
    url, pw = os.environ.get("PRACTICE_VNC_URL", ""), os.environ.get("PRACTICE_VNC_PASSWORD", "")
    return {"url": url, "password": pw} if _valid_desktop({"url": url, "password": pw}) else None


def _console_guard() -> None:
    if not _console_open():
        raise HTTPException(status_code=404, detail="console mode is off")


@app.get("/console/api/config", include_in_schema=False)
def console_config():
    """Tells the page whether it can run without typing a token and a desktop (it never reveals either)."""
    return {"open": _console_open() and _console_desktop() is not None}


@app.post("/console/api/tasks", include_in_schema=False)
async def console_create_task(payload: dict):
    """Start a task on the server's practice desktop; one at a time and capped per hour."""
    _console_guard()
    desk = _console_desktop()
    tarea = payload.get("tarea")
    if desk is None:
        raise HTTPException(status_code=503, detail="the practice desktop is not configured on the server")
    if not isinstance(tarea, str) or not tarea.strip() or len(tarea) > 500:
        raise HTTPException(status_code=422, detail="se requiere una tarea de hasta 500 caracteres")
    if any(tasks.get(i, {}).get("estado") == "en_curso" for i in _console_ids):
        raise HTTPException(status_code=409, detail="ya hay una tarea de la consola en curso")
    now = time.time()
    _console_starts[:] = [t for t in _console_starts if now - t < 3600]
    if len(_console_starts) >= CONSOLE_PER_HOUR:
        raise HTTPException(status_code=429, detail="límite de tareas por hora de la consola alcanzado")
    _console_starts.append(now)
    task_id = _start_task(tarea, desk["url"], desk["password"])
    _console_ids.add(task_id)
    return {"task_id": task_id}


def _console_task(task_id: str) -> dict:
    _console_guard()
    if task_id not in _console_ids or task_id not in tasks:
        raise HTTPException(status_code=404, detail="unknown task")
    return tasks[task_id]


@app.get("/console/api/tasks/{task_id}", include_in_schema=False)
def console_get_task(task_id: str):
    """State, summary and step log of a task started from the console (never the desktop address or password)."""
    v = _console_task(task_id)
    return {"task_id": task_id, "estado": v["estado"], "tarea": v.get("tarea", ""), "resumen": v["resumen"],
            "segundos": round(v.get("fin", time.time()) - v.get("inicio", time.time())), "pasos": v.get("pasos", [])[-300:]}


@app.get("/console/api/tasks/{task_id}/screen", include_in_schema=False)
def console_get_screen(task_id: str):
    """Current or last desktop frame of a console task."""
    _console_task(task_id)
    return get_task_screen(task_id)


@app.get("/tasks", dependencies=[Depends(bearer)])
def list_tasks(limit: int = 20):
    """Recent tasks for operators: no desktop URL or password is ever stored here."""
    rows = sorted(tasks.items(), key=lambda kv: kv[1].get("inicio", 0), reverse=True)[:max(1, min(limit, 100))]
    return [{"task_id": k, "estado": v["estado"], "tarea": v.get("tarea", ""), "resumen": v["resumen"],
             "escritorio_url": v.get("escritorio_url", ""),
             "segundos": round(v.get("fin", time.time()) - v.get("inicio", time.time())),
             "pasos": v.get("pasos", [])[-300:]} for k, v in rows]


@app.get("/tasks/{task_id}/desktop", dependencies=[Depends(bearer)])
def get_task_desktop(task_id: str):
    """The desktop URL and password of one task, in memory only, for the team token."""
    d = _desktops.get(task_id)
    if d is None:
        raise HTTPException(status_code=404, detail="unknown task")
    return d


@app.get("/console", include_in_schema=False)
def console_page():
    """The Talk to My App page (static, no secrets): the user types the entrypoint token and desktop in the page itself."""
    if not CONSOLE_HTML.exists():
        raise HTTPException(status_code=404, detail="console not available")
    return FileResponse(CONSOLE_HTML, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.get("/tasks/{task_id}/screen", dependencies=[Depends(bearer)])
def get_task_screen(task_id: str):
    """Current desktop frame of a task as a JPEG: live while it runs, the last frame after it ends."""
    sess = _sessions.get(task_id)
    frame = None
    if sess is not None:
        try:
            frame = sess.screenshot_jpeg(quality=70, width=960)
        except Exception:  # noqa: BLE001
            frame = None
    if frame is None:
        frame = _last_frame.get(task_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="no frame")
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/tasks/{task_id}", dependencies=[Depends(bearer)])
def get_task(task_id: str):
    """State of one task: en_curso, terminada or fallida plus the summary; an unknown id answers fallida so a restart never stalls the evaluator."""
    task = tasks.get(task_id)
    if task is None:
        # The registry is in memory and resets on a restart. Answer a terminal state so the
        # evaluator closes the task instead of polling a 404 for the rest of its run.
        return {"estado": "fallida",
                "resumen": "La tarea no está registrada: el servicio se reinició antes de terminarla."}
    return {"estado": task["estado"], "resumen": task["resumen"]}


def _finish(task_id: str, estado: str, resumen: str, session: Optional[VncSession]) -> None:
    """Single terminal transition. Cuts input first, then publishes; first call wins."""
    if session is not None:
        session.freeze()
        try:  # keep the final frame BEFORE the state is published, so the console's last fetch finds it
            _last_frame[task_id] = session.screenshot_jpeg(quality=70, width=960)
        except Exception:  # noqa: BLE001
            pass
    if tasks[task_id]["estado"] != "en_curso":
        return
    tasks[task_id].update({"estado": estado, "resumen": resumen, "fin": time.time()})
    persist()
    log.info("task %s -> %s", task_id[:8], estado)


async def _run(task_id: str, tarea: str, url: str, password: str) -> None:
    """Run one task end to end with the watchdog: cut input at the soft limit, publish a terminal state once, always close the session."""
    start = time.monotonic()
    scrub = Scrubber([password, TEAM_TOKEN, gw.key])
    holder: dict = {"session": None, "emit": []}

    def emit(msg: str) -> None:
        holder["emit"].append(msg)
        clean = scrub(msg)
        tasks[task_id]["pasos"].append(f"{time.strftime('%H:%M:%S')} {clean}"[:300])
        log.info("task %s %s", task_id[:8], clean)

    async def work() -> Outcome:
        async with _sem:
            if not gw.ready:
                return Outcome("fallida", razon="el agente no tiene configurado el modelo")
            holder["session"] = await VncSession.open(url, password)
            _sessions[task_id] = holder["session"]
            emit("conectado al escritorio")
            return await AgentLoop(gw, holder["session"], tarea, start + SOFT_CUT, emit).run()

    def watchdog_cut() -> None:
        s = holder["session"]
        if s is not None:
            s.freeze()

    runner = asyncio.create_task(work())
    try:
        loop = asyncio.get_running_loop()
        loop.call_later(SOFT_CUT, watchdog_cut)
        done, _ = await asyncio.wait({runner}, timeout=HARD_END)
        if not done:
            runner.cancel()
            _finish(task_id, "fallida", compose("fallida", scrub=scrub,
                    razon="Se agotó el tiempo de la tarea antes de poder confirmarla."), holder["session"])
            return
        out = runner.result()
        resumen = compose(out.estado, scrub=scrub, hizo=out.hizo, respuesta=out.respuesta,
                          razon=out.razon, claves=out.claves, evidencia=out.evidencia)
        _finish(task_id, out.estado, resumen, holder["session"])
    except BudgetExceeded:
        _finish(task_id, "fallida", compose("fallida", scrub=scrub, razon="Presupuesto de modelo agotado."), holder["session"])
    except VncError as e:
        _finish(task_id, "fallida", compose("fallida", scrub=scrub, razon=f"Error con el escritorio: {e}"), holder["session"])
    except Exception as e:  # noqa: BLE001
        log.exception("task %s crashed", task_id[:8])
        _finish(task_id, "fallida", compose("fallida", scrub=scrub, razon=f"Error interno ({type(e).__name__})."), holder["session"])
    finally:
        s = holder["session"]
        if s is not None:
            try:
                _last_frame[task_id] = s.screenshot_jpeg(quality=70, width=960)
            except Exception:  # noqa: BLE001
                pass
            _sessions.pop(task_id, None)
            while len(_last_frame) > LIVE_MAX_FRAMES:
                _last_frame.pop(next(iter(_last_frame)))
            await s.close()


app = NormalizePath(app)  # uvicorn serves this wrapper; routes above are on the inner FastAPI app
