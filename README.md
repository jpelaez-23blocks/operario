# Operario

**Operador visual de sistemas sin API** — Frontier AI Builders Hackathon, Reto 1.

Un agente que aprende a operar sistemas de gestión sin API, por pantalla, y ejecuta tareas en lenguaje natural en aplicaciones que nunca ha visto. Solo VNC (1280×800, sin DOM): percibe capturas, actúa con clics y teclado, verifica cada paso y se detiene de forma segura cuando la evidencia no respalda la tarea.

## Monorepo

```
operario/
├── challenge/                 # Input del reto (material del organizador)
│   ├── README.md                # Contrato, física del escritorio, reglas de calificación
│   └── tests/                   # Las 5 tareas de ejemplo (E1–E5)
├── documents/                 # Todos los documentos del diseño
│   ├── resumen-diseno.pdf         # Doc de diseño (1 página) — entregable
│   ├── diagrama-arquitectura.pdf  # Diagrama de arquitectura — entregable
│   └── operario-solution-document.pdf  # Documento completo de solución
├── services/
│   └── entrypoint/            # FastAPI: el contrato con el evaluador
│       ├── app.py                 # /health, POST /tasks, GET /tasks/{id}
│       └── requirements.txt
├── packages/
│   ├── vnc_driver/            # Cliente RFB 3.008 sobre WSS (validado con PoC)
│   ├── agent_loop/            # percibir → interpretar → planear → actuar → verificar
│   ├── model_gateway/         # OpenRouter (2 niveles) + Jev Judgment Layer
│   └── summary_composer/      # Resumen determinista + scrubber de secretos
└── infra/
    └── Dockerfile             # Despliegue: HTTPS pública, egreso a OpenRouter y VNC
```

## Arquitectura

Ver `documents/` — el resumen de diseño, el diagrama de arquitectura y el documento completo de solución.

Componentes (nombres en inglés, descripciones en español):

1. **Entrypoint** — FastAPI. Autentica con Bearer, valida, encola; responde `{"task_id"}` en <2 s; el evaluador sondea `GET /tasks/{id}` cada 5 s.
2. **Agent Loop** — una sola acción por captura; verifica la poscondición visual antes de continuar.
3. **Model Gateway** — OpenRouter en dos niveles (visión económica + juicio fuerte), JSON estricto.
4. **VNC Driver** — RFB 3.008 sobre el websocket `/websockify`, auth DES, ZRLE; clics ≥120 ms.
5. **Summary Composer** — determinista: línea `respuesta:` exacta, claves de razón en fallos, cero secretos.
6. **Jev Judgment Layer** (servicio de apoyo) — `Choice` enruta la tarea al entrar, `Noul` resuelve ambigüedad antes de escribir (caso E5), `Score` verifica la pantalla posterior. Solo en compuertas de decisión, vía OpenRouter Decisions API.

Decisión estructural: la URL del escritorio es un parámetro de cada tarea, nunca una constante. Nada se memoriza: ni coordenadas, ni etiquetas, ni rutas.

## Evals — medimos a los agentes, no solo a las tareas

El diferenciador: un sistema de evals que mide cómo los agentes siguen direcciones y qué tan confiable es cada capacidad. Medir → corregir → re-evaluar.

1. **Matriz sintética** (`evals/synthetic_matrix.py`) — genera escenarios sintéticos en las 5 capacidades (create, update, count, export, refuse) con resultados autoverificables (read-back, homónimos plantados, conteos construidos). Corre desde `__reset` limpio contra el entrypoint desplegado. Reporta pass rate por capacidad.
2. **Eval de direcciones** (`evals/direction_eval.py`) — extrae cada par (dirección → respuesta) de los transcripts y lo califica con un juicio Jev Score 0–2. Los misses alimentan el loop de mejora: se corrigen y se re-evalúa.
3. **`__check`** — los 5 ejemplos canónicos del organizador.

Ver `evals/README.md`. Reportes en `evals/reports/`.

## Contrato

```
GET  /health            → 200 cuando está listo (Bearer)
POST /tasks             → {"tarea": "...", "escritorio": {"url": "wss://.../websockify", "password": "..."}}
                          responde {"task_id": "..."} en <2 s, trabaja en segundo plano (Bearer)
GET  /tasks/{task_id}   → {"estado": "en_curso|terminada|fallida", "resumen": "..."} (Bearer)
```

Cada tarea tiene 5 minutos en un escritorio limpio. El watchdog corta la entrada VNC a los ~4:30 y de inmediato al declarar estado terminal.

## Desarrollo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r services/entrypoint/requirements.txt
# Variables de entorno (nunca en el repo):
#   OPENROUTER_API_KEY — VLM + Jev vía OpenRouter
#   TEAM_TOKEN         — Bearer del entrypoint
uvicorn services.entrypoint.app:app --host 0.0.0.0 --port 8000
```

## Estado

- [x] Systems design (doc + diagrama) — entregado
- [x] VNC driver — PoC validado contra escritorio real (handshake, auth, screenshot, clic verificado)
- [ ] Entrypoint FastAPI + watchdog
- [ ] Agent loop end-to-end (E1)
- [ ] Summary composer + secret scrubber
- [ ] E2–E5 contra `__check`
- [ ] Despliegue público
