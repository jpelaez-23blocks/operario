"""Practice loop: clean __reset -> POST /tasks to a running entrypoint -> poll -> __check.
Env: PRACTICE_HTTP_URL, PRACTICE_VNC_URL, PRACTICE_VNC_PASSWORD, PRACTICE_DESK_TOKEN, TEAM_TOKEN.
Usage: practice.py E1 [E2 ...]   (ENTRYPOINT defaults to http://127.0.0.1:8000)"""
import glob, json, os, sys, time
import httpx

E = os.environ
EP = E.get("ENTRYPOINT", "http://127.0.0.1:8000")
H = {"Authorization": f"Bearer {E['TEAM_TOKEN']}"}
D = {"Authorization": f"Bearer {E['PRACTICE_DESK_TOKEN']}"}


def run(tid: str) -> bool:
    path = glob.glob(f"challenge/tests/{tid}-*.json")[0]
    test = json.load(open(path))
    httpx.post(f"{E['PRACTICE_HTTP_URL']}/__reset", headers=D, timeout=30).raise_for_status()
    time.sleep(3)
    t0 = time.time()
    r = httpx.post(f"{EP}/tasks", headers=H, timeout=5, json={
        "tarea": test["instruccion"],
        "escritorio": {"url": E["PRACTICE_VNC_URL"], "password": E["PRACTICE_VNC_PASSWORD"]}})
    post_s = time.time() - t0
    task_id = r.json()["task_id"]
    while True:
        g = httpx.get(f"{EP}/tasks/{task_id}", headers=H, timeout=5).json()
        if g["estado"] != "en_curso":
            break
        time.sleep(5)
    dur = time.time() - t0
    chk = httpx.post(f"{E['PRACTICE_HTTP_URL']}/__check", headers=D, json=test, timeout=30).json()
    exp = test["estado_esperado"]
    ok = chk.get("pass") and g["estado"] == exp
    if "respuesta_esperada" in test:
        ok = ok and f"respuesta: {test['respuesta_esperada']}".split()[1] in g["resumen"]
    print(f"{tid}: {'PASS' if ok else 'FAIL'} estado={g['estado']} (esperado {exp}) post={post_s:.2f}s total={dur:.0f}s")
    print("  checks:", [(c['nombre'], c['ok']) for c in chk.get("checks", [])])
    print("  resumen:", g["resumen"].replace("\n", " | ")[:300])
    return bool(ok)


if __name__ == "__main__":
    results = [run(t) for t in sys.argv[1:]]
    sys.exit(0 if all(results) else 1)
