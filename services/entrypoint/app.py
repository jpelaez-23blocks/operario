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
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException

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
gw = Gateway()
tasks: dict[str, dict] = {}
_sem = asyncio.Semaphore(int(os.environ.get("MAX_CONCURRENT", "6")))
_bg: set = set()
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
    if _state_file.exists():
        try:
            for k, v in json.loads(_state_file.read_text()).items():
                if v["estado"] == "en_curso":
                    v = {**v, "estado": "fallida", "resumen": "El servicio se reinició durante la tarea."}
                tasks[k] = v
        except (OSError, ValueError):
            log.exception("could not reload registry")


def bearer(authorization: str = Header("")) -> None:
    if not TEAM_TOKEN or not hmac.compare_digest(authorization, f"Bearer {TEAM_TOKEN}"):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health", dependencies=[Depends(bearer)])
def health():
    missing = [n for n in ("OPENROUTER_API_KEY", "MODEL_FAST", "MODEL_STRONG") if not os.environ.get(n)]
    return {"ok": True, "model_ready": gw.ready, "missing_env": missing,
            "en_curso": sum(1 for t in tasks.values() if t["estado"] == "en_curso")}


def _valid_desktop(d) -> bool:
    if not isinstance(d, dict) or not d.get("url") or not isinstance(d.get("password", ""), str):
        return False
    return urlparse(str(d["url"])).scheme in ("ws", "wss")


@app.post("/tasks", dependencies=[Depends(bearer)])
async def create_task(payload: dict):
    tarea, desk = payload.get("tarea"), payload.get("escritorio")
    if not isinstance(tarea, str) or not tarea.strip() or not _valid_desktop(desk):
        raise HTTPException(status_code=422, detail="se requiere tarea y escritorio {url, password}")
    task_id = uuid.uuid4().hex
    tasks[task_id] = {"estado": "en_curso", "resumen": "", "tarea": tarea[:500], "inicio": time.time(), "pasos": []}
    persist()
    t = asyncio.create_task(_run(task_id, tarea.strip(), desk["url"], desk.get("password", "")))
    _bg.add(t)
    t.add_done_callback(_bg.discard)
    return {"task_id": task_id}


@app.get("/tasks", dependencies=[Depends(bearer)])
def list_tasks(limit: int = 20):
    """Recent tasks for operators: no desktop URL or password is ever stored here."""
    rows = sorted(tasks.items(), key=lambda kv: kv[1].get("inicio", 0), reverse=True)[:max(1, min(limit, 100))]
    return [{"task_id": k, "estado": v["estado"], "tarea": v.get("tarea", ""), "resumen": v["resumen"],
             "segundos": round(v.get("fin", time.time()) - v.get("inicio", time.time())),
             "pasos": v.get("pasos", [])[-40:]} for k, v in rows]


@app.get("/tasks/{task_id}", dependencies=[Depends(bearer)])
def get_task(task_id: str):
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="unknown task")
    return {"estado": task["estado"], "resumen": task["resumen"]}


def _finish(task_id: str, estado: str, resumen: str, session: Optional[VncSession]) -> None:
    """Single terminal transition. Cuts input first, then publishes; first call wins."""
    if session is not None:
        session.freeze()
    if tasks[task_id]["estado"] != "en_curso":
        return
    tasks[task_id].update({"estado": estado, "resumen": resumen, "fin": time.time()})
    persist()
    log.info("task %s -> %s", task_id[:8], estado)


async def _run(task_id: str, tarea: str, url: str, password: str) -> None:
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
            await s.close()
