"""Run free-form tasks against the practice desktop through the local entrypoint (no __check)."""
import os, sys, time, httpx
E = os.environ; EP = E.get("ENTRYPOINT", "http://127.0.0.1:8077")
H = {"Authorization": f"Bearer {E['TEAM_TOKEN']}"}; D = {"Authorization": f"Bearer {E['PRACTICE_DESK_TOKEN']}"}
for tarea in sys.argv[1:]:
    httpx.post(f"{E['PRACTICE_HTTP_URL']}/__reset", headers=D, timeout=30); time.sleep(3)
    t0 = time.time()
    tid = httpx.post(f"{EP}/tasks", headers=H, json={"tarea": tarea, "escritorio": {"url": E["PRACTICE_VNC_URL"], "password": E["PRACTICE_VNC_PASSWORD"]}}).json()["task_id"]
    while (g := httpx.get(f"{EP}/tasks/{tid}", headers=H).json())["estado"] == "en_curso": time.sleep(5)
    print(f"[{time.time()-t0:.0f}s] {tarea}\n  -> {g['estado']}: {g['resumen'][:400]!r}")
