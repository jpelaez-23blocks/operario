# Operario

**Operador visual de sistemas sin API** — Frontier AI Builders Hackathon, Reto 1.

Un agente que aprende a operar sistemas de gestión sin API, por pantalla, y ejecuta tareas en lenguaje natural en aplicaciones que nunca ha visto. Solo VNC (1280×800, sin DOM): percibe capturas, actúa con clics y teclado, verifica cada paso y se detiene de forma segura cuando la evidencia no respalda la tarea.

## Empezar (de cero a un entrypoint en marcha)

Probado en macOS con Python 3.12 (la imagen de Docker usa 3.12). Todo desde la raíz del repo.

```bash
# 1. Entorno e instalación
python3 -m venv .venv && source .venv/bin/activate
pip install -r services/entrypoint/requirements.txt

# 2. Variables mínimas (solo en tu terminal; nunca las guardes en el repo)
export TEAM_TOKEN=dev-token-123          # el Bearer que exige el entrypoint; inventa uno
export DATA_DIR=/tmp/operario-data       # registro de tareas y contador de gasto

# 3. Arrancar
uvicorn services.entrypoint.app:app --host 127.0.0.1 --port 8000
```

Si el puerto 8000 ya está ocupado, cambia `--port 8000` por otro (p. ej. `8001`) y usa ese número en los comandos de abajo.

En otra terminal, comprueba que responde:

```bash
curl -s http://127.0.0.1:8000/health
# {"ok":true}
curl -s -H "Authorization: Bearer dev-token-123" http://127.0.0.1:8000/health
# {"ok":true,"model_ready":false,"missing_env":["OPENROUTER_API_KEY","MODEL_FAST","MODEL_STRONG"],"en_curso":0}
```

`model_ready:false` es normal en este punto: faltan las claves del modelo. Sin ellas, el servicio arranca y cumple el contrato, pero toda tarea termina al instante `fallida` con "el agente no tiene configurado el modelo".

### Enviar una tarea

```bash
curl -s -X POST http://127.0.0.1:8000/tasks \
  -H "Authorization: Bearer dev-token-123" -H "Content-Type: application/json" \
  -d '{"tarea": "Registra al cliente Papelería Los Andes, NIT 901234567, teléfono 3157654321, ciudad Pereira.",
       "escritorio": {"url": "wss://TU-ESCRITORIO/websockify", "password": "LA-CLAVE-VNC"}}'
# {"task_id":"6af15a7f64614b0590ed16dd98f4bb42"}     (responde en menos de 2 s)

curl -s -H "Authorization: Bearer dev-token-123" http://127.0.0.1:8000/tasks/<task_id>
# {"estado":"en_curso","resumen":""}   ...   {"estado":"terminada","resumen":"..."}
```

Sondea cada 5 s hasta que `estado` sea `terminada` o `fallida`. Cada tarea dura como máximo 5 minutos. La URL del escritorio es un parámetro de cada tarea, nunca una constante.

### Para que el agente trabaje de verdad

Hacen falta las claves del modelo, definidas antes de arrancar el servicio, y un escritorio VNC accesible por `ws://` o `wss://` (el del reto, 1280×800):

| Variable | Para qué | Por defecto |
|---|---|---|
| `TEAM_TOKEN` | Bearer que exige el entrypoint. Sin él todo da 401. | (obligatoria) |
| `OPENROUTER_API_KEY` | Clave de OpenRouter para el modelo y para Jev. | vacía: el agente no corre |
| `MODEL_FAST` | Modelo de visión barato, p. ej. `anthropic/claude-sonnet-5.5` | vacía: el agente no corre |
| `MODEL_STRONG` | Modelo de juicio fuerte (verificador), p. ej. `anthropic/claude-opus-5.5` | vacía: el agente no corre |
| `BUDGET_USD` | Tope de gasto del modelo; al llegar, las tareas terminan `fallida` | `40` |
| `DATA_DIR` | Dónde se guardan `tasks.json` y `ledger.json` | `data` |
| `JEV_ENABLED` | `0` apaga las puertas de decisión de Jev (el agente sigue sin ellas) | `1` |
| `JEV_MODEL` | Modelo de Jev en OpenRouter | `typesafe/jev-1.13` |
| `TASK_LIMIT_S`, `SOFT_CUT_S`, `HARD_END_S` | Tiempos: ventana de la tarea, corte de la entrada VNC, declarar estado terminal | `300`, `270`, `285` |
| `MAX_CONCURRENT` | Tareas en paralelo | `6` |
| `CORS_ORIGINS` | Orígenes permitidos para el navegador (lista separada por comas) | `*` |
| `REASONING_FAST`, `REASONING_STRONG` | Esfuerzo de razonamiento de cada modelo | `low` |

Ejemplo: `export OPENROUTER_API_KEY=... MODEL_FAST=anthropic/claude-sonnet-5.5 MODEL_STRONG=anthropic/claude-opus-5.5`. Con eso `/health` (con token) responde `model_ready:true`.

## Pruebas

```bash
pip install pytest pytest-asyncio
python -m pytest -q
# 24 passed
```

No necesitan red, escritorio ni claves: usan un servidor RFB simulado (`tests/mock_rfb.py`) y un modelo falso. Tardan unos 30 s.

## Despliegue

Ver `DEPLOY.md` (imagen en `infra/Dockerfile`, una sola réplica, volumen para `DATA_DIR`).

## Talk to My App

`apps/talk-to-my-app/talk-to-my-app.html`: una página que se abre en el navegador, sin compilar nada. Escribes la tarea en lenguaje cotidiano, la envía a `POST /tasks` y muestra los pasos en vivo, la respuesta y el resumen. En el panel "Conectar a Operario" se escribe la URL del entrypoint, el token del equipo y la URL y clave del escritorio; viven solo en la memoria de la pestaña.

## Documentos

- `documents/especificacion-operario.md`: cada comportamiento del servicio con una línea de log real y la marca CONFIRMADO o SUPUESTO.
- `documents/resumen-diseno.pdf`, `documents/diagrama-arquitectura.pdf`, `documents/operario-solution-document.pdf`: diseño y arquitectura.

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
GET  /health            → 200 siempre que el servicio vive: sin token {"ok": true}; con Bearer añade model_ready, missing_env y en_curso
POST /tasks             → {"tarea": "...", "escritorio": {"url": "wss://.../websockify", "password": "..."}}
                          responde {"task_id": "..."} en <2 s, trabaja en segundo plano (Bearer)
GET  /tasks/{task_id}   → {"estado": "en_curso|terminada|fallida", "resumen": "..."} (Bearer)
```

Cada tarea tiene 5 minutos en un escritorio limpio. El watchdog corta la entrada VNC a los ~4:30 y de inmediato al declarar estado terminal.

