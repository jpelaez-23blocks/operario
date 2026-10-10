#!/usr/bin/env python3
"""Synthetic capability-matrix eval for Operario.

Our own eval harness beyond the 5 canonical examples. Generates synthetic
tasks across the 5 capabilities the hidden set grades (create, update, count,
export, refuse), each with a *self-verifiable* outcome constructed by the
harness itself -- no hidden answer key needed.

Every scenario runs from a clean __reset against the deployed entrypoint
(the real contract path the hidden eval will hit), and each scenario grades
itself by read-back: creates and updates are verified with follow-up queries,
counts use records the harness created, refuses plant their own homonyms.

Usage:
    PRACTICE_BASE=https://<practice host> TEAM_TOKEN=... \
    ENTRYPOINT_URL=https://operario-production.up.railway.app \
    DESKTOP_URL=wss://<host>/websockify DESKTOP_PASSWORD=... \
    python evals/synthetic_matrix.py [--n 3] [--only create] [--seed 7]

    --n      scenarios per capability (default 3 -> 15 scenarios)
    --only   run one capability: create | update | count | export | refuse
    --seed   random seed for reproducible names (default: random)

Env (no secrets in the repo, ever):
    PRACTICE_BASE, TEAM_TOKEN, ENTRYPOINT_URL, DESKTOP_URL, DESKTOP_PASSWORD

Cost: each scenario is 1-4 entrypoint tasks (~1-2 min each). 15 scenarios is
roughly 40-70 minutes and a few dollars of model budget. The crew decides
when to run it; it must not collide with hidden-validation windows.
"""
import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------- config

PRACTICE = os.environ.get("PRACTICE_BASE", "").rstrip("/")
TOKEN = os.environ.get("TEAM_TOKEN", "")
ENTRY = os.environ.get("ENTRYPOINT_URL", "").rstrip("/")
DESK_URL = os.environ.get("DESKTOP_URL", "")
DESK_PW = os.environ.get("DESKTOP_PASSWORD", "")

for name in ("PRACTICE_BASE", "TEAM_TOKEN", "ENTRYPOINT_URL", "DESKTOP_URL", "DESKTOP_PASSWORD"):
    if not os.environ.get(name):
        raise SystemExit(f"missing env: {name}")

CITIES = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga", "Pereira"]
POLL_EVERY = 5
POLL_TIMEOUT = 340  # task hard-ends at 285s server-side; margin for polling


# ---------------------------------------------------------------- http

def _req(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Authorization": f"Bearer {TOKEN}",
                                        "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def practice_reset():
    _req("POST", f"{PRACTICE}/__reset", {})


def submit(tarea):
    r = _req("POST", f"{ENTRY}/tasks",
             {"tarea": tarea, "escritorio": {"url": DESK_URL, "password": DESK_PW}})
    return r["task_id"]


def poll(task_id):
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        r = _req("GET", f"{ENTRY}/tasks/{task_id}")
        if r.get("estado") != "en_curso":
            return r
        time.sleep(POLL_EVERY)
    return {"estado": "en_curso", "resumen": "TIMEOUT del harness esperando el terminal."}


def run_task(tarea):
    """One entrypoint task, fully polled. Returns the final {estado, resumen}."""
    return poll(submit(tarea))


def respuesta_value(resumen):
    for line in (resumen or "").splitlines():
        if line.strip().lower().startswith("respuesta:"):
            return line.split(":", 1)[1].strip()
    return ""


# ---------------------------------------------------------------- generators
# Each returns (name, [tarea, ...], grader) where grader([results]) -> (ok, note).

def _uniq(rng, prefix):
    return f"{prefix} {rng.randint(1000, 9999)}"


def gen_create(rng, i):
    name = _uniq(rng, "EvalCli")
    nit = str(rng.randint(100000000, 999999999))
    phone = f"3{rng.randint(100000000, 199999999)}"
    city = CITIES[i % len(CITIES)]
    steps = [
        f"Registra al cliente {name}, NIT {nit}, teléfono {phone}, ciudad {city}.",
        f"Busca el cliente {name} e indica su NIT con respuesta: <nit>.",
    ]

    def grade(res):
        if res[0].get("estado") != "terminada":
            return False, f"create no terminó: {res[0].get('estado')}"
        val = respuesta_value(res[1].get("resumen"))
        if res[1].get("estado") == "terminada" and nit in val:
            return True, "read-back OK"
        return False, f"read-back falló (respuesta={val!r})"

    return f"create-{i}", steps, grade


def gen_update(rng, i):
    name = _uniq(rng, "EvalUpd")
    nit = str(rng.randint(100000000, 999999999))
    addr = f"Calle {rng.randint(1, 99)} # {rng.randint(1, 99)}-{rng.randint(1, 99)}"
    steps = [
        f"Registra al cliente {name}, NIT {nit}, teléfono 3{rng.randint(100000000, 199999999)}, ciudad {CITIES[i % len(CITIES)]}.",
        f"Cambia la dirección del cliente {name} a {addr}.",
        f"Busca el cliente {name} e indica su dirección con respuesta: <dirección>.",
    ]

    def grade(res):
        if res[1].get("estado") != "terminada":
            return False, f"update no terminó: {res[1].get('estado')}"
        val = respuesta_value(res[2].get("resumen"))
        if res[2].get("estado") == "terminada" and addr in val:
            return True, "read-back OK"
        return False, f"read-back falló (respuesta={val!r})"

    return f"update-{i}", steps, grade


def gen_count(rng, i):
    tag = f"EvalCnt{rng.randint(1000, 9999)}"
    names = [f"{tag} A", f"{tag} B"]
    steps = [
        f"Registra al cliente {names[0]}, NIT {rng.randint(100000000, 999999999)}, "
        f"teléfono 3{rng.randint(100000000, 199999999)}, ciudad {CITIES[i % len(CITIES)]}.",
        f"Registra al cliente {names[1]}, NIT {rng.randint(100000000, 999999999)}, "
        f"teléfono 3{rng.randint(100000000, 199999999)}, ciudad {CITIES[(i + 1) % len(CITIES)]}.",
        f"¿Cuántos clientes se llaman {tag} A o {tag} B? Responde con respuesta: <número>.",
    ]

    def grade(res):
        val = respuesta_value(res[2].get("resumen"))
        if res[2].get("estado") == "terminada" and val.strip() == "2":
            return True, "conteo OK"
        return False, f"conteo falló (respuesta={val!r}, estado={res[2].get('estado')})"

    return f"count-{i}", steps, grade


def gen_export(rng, i):
    meses = [("enero", "2026-01"), ("febrero", "2026-02"), ("marzo", "2026-03"),
             ("abril", "2026-04"), ("mayo", "2026-05")]
    mes, _ = meses[i % len(meses)]
    steps = [f"Exporta el reporte de pedidos entregados de {mes} de 2026."]

    def grade(res):
        if res[0].get("estado") == "terminada":
            return True, "exportación limpia"
        return False, f"exportación falló: {res[0].get('estado')}"

    return f"export-{i}", steps, grade


def gen_refuse(rng, i):
    name = _uniq(rng, "EvalHom")
    nit1 = str(rng.randint(100000000, 999999999))
    nit2 = str(rng.randint(100000000, 999999999))
    steps = [
        f"Registra al cliente {name}, NIT {nit1}, teléfono 3{rng.randint(100000000, 199999999)}, ciudad Bogotá.",
        f"Registra al cliente {name}, NIT {nit2}, teléfono 3{rng.randint(200000000, 299999999)}, ciudad Cali.",
        f"Cambia el teléfono del cliente {name} a 3001112222.",
    ]

    def grade(res):
        r = res[2]
        if r.get("estado") != "fallida":
            return False, f"debió rehusar, dio {r.get('estado')}"
        resumen = r.get("resumen", "")
        if nit1 in resumen and nit2 in resumen:
            return True, "rehusó nombrando ambos"
        return False, "rehusó pero sin nombrar ambos identificadores"

    return f"refuse-{i}", steps, grade


GENERATORS = {"create": gen_create, "update": gen_update, "count": gen_count,
              "export": gen_export, "refuse": gen_refuse}


# ---------------------------------------------------------------- main

def main():
    n = 3
    only = None
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
        assert only in GENERATORS, f"--only debe ser uno de {list(GENERATORS)}"
    if "--seed" in sys.argv:
        random.seed(int(sys.argv[sys.argv.index("--seed") + 1]))
    rng = random.Random()

    caps = [only] if only else list(GENERATORS)
    scenarios = []
    for cap in caps:
        for i in range(n):
            scenarios.append((cap, GENERATORS[cap](rng, i)))

    print(f"{len(scenarios)} escenarios sintéticos ({', '.join(caps)})", flush=True)
    results = []
    for cap, (name, steps, grade) in scenarios:
        print(f"\n== {name} ==", flush=True)
        try:
            practice_reset()
            outs = []
            for s, tarea in enumerate(steps):
                print(f"  paso {s + 1}/{len(steps)}: {tarea[:70]}...", flush=True)
                outs.append(run_task(tarea))
                if outs[-1].get("estado") == "en_curso":
                    break
            ok, note = grade(outs)
        except Exception as e:  # noqa: BLE001 -- un escenario roto no tumba la matriz
            ok, note = False, f"error del harness: {type(e).__name__}: {e}"
        print(f"  -> {'PASS' if ok else 'FAIL'}: {note}", flush=True)
        results.append({"capability": cap, "name": name, "ok": ok, "note": note})

    by_cap = {}
    for r in results:
        by_cap.setdefault(r["capability"], []).append(r["ok"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    lines = [f"# Matriz sintética — {stamp} UTC", ""]
    total_ok = 0
    for cap, oks in by_cap.items():
        rate = sum(oks) / len(oks)
        total_ok += sum(oks)
        lines.append(f"- **{cap}**: {sum(oks)}/{len(oks)} ({rate:.0%})")
    lines += ["", f"**Total: {total_ok}/{len(results)} ({total_ok / len(results):.0%})**", "",
              "## Detalle"]
    for r in results:
        lines.append(f"- {'✅' if r['ok'] else '❌'} {r['name']}: {r['note']}")
    outdir = "evals/reports"
    os.makedirs(outdir, exist_ok=True)
    path = f"{outdir}/synthetic-matrix-{stamp}.md"
    open(path, "w").write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines[:8]))
    print(f"\nreporte: {path}")


if __name__ == "__main__":
    main()
