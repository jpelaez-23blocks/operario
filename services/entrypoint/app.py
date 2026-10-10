"""Operario entrypoint — el contrato con el evaluador.

GET  /health          -> 200 cuando está listo (Bearer team token)
POST /tasks           -> {"task_id": "..."} en <2 s; trabaja en segundo plano (Bearer)
GET  /tasks/{task_id} -> {"estado": "en_curso|terminada|fallida", "resumen": "..."} (Bearer)
"""

import os
import uuid
from fastapi import Depends, FastAPI, Header, HTTPException

TEAM_TOKEN = os.environ.get("TEAM_TOKEN", "")

app = FastAPI(title="Operario")

# Registro en memoria + persistencia por transición (restart-safe sin Redis).
tasks: dict[str, dict] = {}


def bearer(authorization: str = Header("")) -> None:
    if not TEAM_TOKEN or authorization != f"Bearer {TEAM_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health(_: None = Depends(bearer)):
    return {"ok": True}


@app.post("/tasks", dependencies=[Depends(bearer)])
def create_task(payload: dict):
    # TODO: validar payload, encolar el Agent Loop en segundo plano.
    task_id = uuid.uuid4().hex
    tasks[task_id] = {"estado": "en_curso", "resumen": ""}
    return {"task_id": task_id}


@app.get("/tasks/{task_id}", dependencies=[Depends(bearer)])
def get_task(task_id: str):
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="unknown task")
    return task
