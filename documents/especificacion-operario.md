# Operario: especificación y bitácora de comportamientos

Cada comportamiento del servicio lleva **una línea real** que lo prueba y una etiqueta:

- **CONFIRMADO (log)**: la línea salió de una tarea real de la corrida (`collected/tasks.json`, campo `pasos` o `resumen`). La hora de esas líneas es la del servidor (UTC), no hora de Colombia ni de Denver.
- **CONFIRMADO (prueba)**: lo demuestra una prueba del repo (`pytest`, 24 pruebas, todas pasan en un entorno limpio).
- **CONFIRMADO (corrida local)**: lo observé yo el 2026-10-10 17:37 MDT al arrancar el servicio en esta máquina, sin escritorio y sin claves de modelo.
- **SUPUESTO**: sale del código, pero nadie lo vio en un log ni en una prueba. Se dice qué faltaría para confirmarlo.

Las líneas no contienen URLs de escritorio, contraseñas, tokens ni claves. Los nombres de pacientes son los del escritorio de práctica (clínica de ejemplo) y salen tal cual en los logs.

Resumen: 28 comportamientos. Los que tienen una parte SUPUESTO la llevan anotada: 1.5, 2.2, 2.3, 3.7, 3.8, 4.2, 4.4 y 6.1. Al final hay una lista de hallazgos.

## 1. Contrato HTTP

### 1.1 `POST /tasks` responde `task_id` en menos de 2 s
Código: `services/entrypoint/app.py`, `create_task`. Registra la tarea, lanza el trabajo en segundo plano y responde.
- **CONFIRMADO (corrida local)**: `{"task_id":"6af15a7f64614b0590ed16dd98f4bb42"}` con `200 0.001279s`.
- **CONFIRMADO (prueba)**: `tests/test_entrypoint.py::test_contract_auth_and_fast_post`.

### 1.2 Autenticación Bearer y validación
`POST /tasks` sin token da 401. Sin `escritorio` o sin `tarea` da 422. `/health` sin token es solo `{"ok": true}`.
- **CONFIRMADO (corrida local)**: `{"detail":"unauthorized"} 401`
- **CONFIRMADO (corrida local)**: `{"detail":"se requiere tarea y escritorio {url, password}"} 422`
- **CONFIRMADO (corrida local)**: `/health` sin token: `{"ok":true}`; con token: `{"ok":true,"model_ready":false,"missing_env":["OPENROUTER_API_KEY","MODEL_FAST","MODEL_STRONG"],"en_curso":0}`

### 1.3 Sondeo `GET /tasks/{id}` y los tres estados
Estados: `en_curso`, `terminada`, `fallida`. El evaluador sondea cada 5 s.
- **CONFIRMADO (log)**, `terminada` (tarea `b1248546`, 19:23:35): `verificación: True — Nota N-5091 guardada para P-0062 Rodrigo Arias Mendoza, tipo Llamada, texto 'Se llamó por la inasist…`
- **CONFIRMADO (log)**, `fallida` (tarea `df429047`): `No se completó la tarea. se agotó el tiempo sin completar la tarea`
- **CONFIRMADO (log)**, `en_curso` (tarea `c21caa72`, registrada mientras corría, último paso 19:30:34): `jev noul ambiguity=0.54`

### 1.4 `GET /tasks/{id}` con un id desconocido responde `fallida`, no 404
Para que el evaluador cierre la tarea si el servicio se reinició. Commit `c49707d`.
- **CONFIRMADO (corrida local)**: `{"estado":"fallida","resumen":"La tarea no está registrada: el servicio se reinició antes de terminarla."}`

### 1.5 Tarea en curso durante un reinicio se recarga como `fallida`
`_startup` lee `tasks.json`; lo que estaba `en_curso` pasa a `fallida` con "El servicio se reinició durante la tarea."
- **SUPUESTO**: no hay línea de log ni prueba. Para confirmarlo: arrancar, lanzar una tarea, matar el proceso y volver a arrancar con el mismo `DATA_DIR`. (En Railway el disco se borra en cada despliegue salvo que exista un volumen; ver `collected/VOLUME-NOTE.md`.)

### 1.6 Rutas con barras repetidas o final
`//health` y `/tasks/` funcionan (clase `NormalizePath`).
- **CONFIRMADO (corrida local)**: `GET //health` responde `200`.
- **CONFIRMADO (prueba)**: `tests/test_entrypoint.py::test_path_spellings_and_open_liveness`.

### 1.7 CORS
Para que Talk to My App llame desde el navegador. Origen `*` salvo que `CORS_ORIGINS` lo restrinja. La autenticación es un encabezado Bearer, no cookies.
- **CONFIRMADO (corrida local)**: preflight `OPTIONS /tasks` con `Origin: https://example.com` responde `HTTP/1.1 200 OK` y `access-control-allow-origin: *`, `access-control-allow-headers: Accept, Accept-Language, Authorization, Content-Language, Content-Type`.

### 1.8 Contraseña del escritorio fuera de listados, archivo y resumen
`/tasks` no incluye la contraseña; `_desktops` vive solo en memoria y se sirve únicamente con token.
- **CONFIRMADO (prueba)**: `tests/test_entrypoint.py::test_list_tasks_requires_token_and_hides_password` y `test_desktop_served_only_to_token_and_kept_out_of_listing_and_file`.

## 2. Tiempo y vigilante

### 2.1 Límite de 5 minutos, corte de la entrada VNC a ~4:30 (`SOFT_CUT_S=270`)
`watchdog_cut` llama a `session.freeze()`; el siguiente intento de entrada lanza `InputFrozen` y la tarea termina `fallida` con "tiempo agotado".
- **CONFIRMADO (log)**: tarea `537ab295` (duración 279 s), último paso `19:48:38 paso 37: click (953,281) — C-1305: 21/10 08:40, Dr. Jorge Mejía Cano, cardiología, 202, EPS, Cancelada. Sin reactivar; abro Crear cita.` y resumen `No se completó la tarea. tiempo agotado`.

### 2.2 Estado terminal a los 285 s (`HARD_END_S`) aunque el agente siga
`asyncio.wait(..., timeout=HARD_END)`; si se agota, cancela y declara `fallida` con "Se agotó el tiempo de la tarea antes de poder confirmarla."
- **SUPUESTO**: ninguna tarea recolectada terminó por esta vía; todas las `fallida` por tiempo salen por 2.1 o por el bucle ("se agotó el tiempo sin completar la tarea"). Para confirmarlo hace falta una llamada al modelo que se cuelgue pasados 285 s.

### 2.3 Congelar la entrada al declarar el estado terminal
`_finish` llama a `session.freeze()` antes de publicar; el primero en llegar gana.
- **CONFIRMADO (corrida local)**: línea de log del servidor `operario task 6af15a7f -> fallida` (la tarea de 1.1 terminó al instante porque no había modelo configurado).
- **SUPUESTO**: que el agente no toque el escritorio de la tarea siguiente no se ha medido directamente.

## 3. El agente

### 3.1 Bucle percibir, actuar, verificar
Una captura (`screenshot_jpeg`), una acción en JSON validada por `Action`, se ejecuta, se espera el repintado y se mira de nuevo.
- **CONFIRMADO (log)**: `19:20:25 paso 1: click (656,604) text='' — La fecha mostrada en la app es martes 13/10/2026 09:00. Hay un diálogo de novedades; lo cierro con Entendido.` (tarea `b1248546`).
- **CONFIRMADO (prueba)**: `tests/test_loop.py::test_click_then_done_verified`.

### 3.2 Fecha de la aplicación primero
Las tareas con palabras de fecha relativa (hoy, vencidas, próximos…) usan la fecha que muestra la app, no la del modelo.
- **CONFIRMADO (log)**: la misma línea de 3.1 registra "La fecha mostrada en la app es martes 13/10/2026".

### 3.3 Acciones encadenadas (`then`)
Hasta 2 acciones seguidas sin captura nueva (3 si solo llenan campos de texto). Nunca después de abrir un menú ni de guardar.
- **CONFIRMADO (log)**: `19:44:45 paso 8: click (77,164) + type text='C-1305' + key keys=Enter — La lista se reinició sin filtro. Filtro de nuevo por ID C-1305…` (tarea `537ab295`).
- **CONFIRMADO (prueba)**: `tests/test_loop.py::test_chained_actions_run_in_order` y `test_chain_validation`.

### 3.4 Memoria de notas (solo se agregan hechos)
El modelo escribe `notas` con hechos nuevos; el sistema los acumula hasta 3000 caracteres y descarta primero lo más viejo.
- **CONFIRMADO (log)**: `22:25:49 notas+: F-2210 05/10/2026 Alberto Rangel Díaz ortopedia 220.000 Pagada; only one match` (tarea `5de827fe`).
- **CONFIRMADO (prueba)**: `tests/test_loop.py::test_facts_are_append_only`.

### 3.5 Verificador antes de `terminada`
Un modelo fuerte lista cada requisito de la tarea y marca si está cumplido con evidencia. Si no, el agente recibe lo que falta y vuelve a intentar (máximo 2 rechazos).
- **CONFIRMADO (log)**: `22:12:00 verificación: False — La cita se guardó, pero no hay evidencia de que el paciente, el médico ni el cupo se hayan derivado | faltan: Identificar al paciente que el sábado pagó por transferencia con referencia TRF-550217; Mismo médico de la consulta pagada; Primer cupo libre del jueves 15/10` (tarea `aeda33da`, terminó `fallida`).
- **CONFIRMADO (prueba)**: `tests/test_loop.py::test_unmet_requirement_blocks_terminada`, `test_unverified_done_becomes_fallida`.

### 3.6 Aceptar el reclamo cuando el verificador no encuentra evidencia pero tampoco contradice
Con poco tiempo (<90 s) o tras 2 rechazos, se acepta si el agente citó evidencia.
- **CONFIRMADO (log)**: `22:56:53 verificador sin contradicción y sin tiempo para re-explorar; se acepta el reclamo con evidencia` (tarea `12fff137`).
- **CONFIRMADO (prueba)**: `tests/test_loop.py::test_missing_evidence_without_contradiction_is_accepted_after_a_short_lookup`, `test_no_time_to_reexplore_accepts_an_evidenced_claim_at_once`, `test_contradiction_still_ends_fallida`.

### 3.7 Guarda de premisa
Si la última nota habla de algo "probable" o "falta verificar" y ninguna nota posterior dice "confirmado", se retiene cualquier escritura (hasta 2 veces).
- **CONFIRMADO (prueba)**: `tests/test_loop.py::test_write_is_held_while_a_premise_is_unconfirmed`, `test_premise_guard_detects_unconfirmed_guess_until_confirmed`.
- **SUPUESTO**: la retención no deja línea en `pasos` (solo entra en el historial interno), así que en los logs no se ve. Para confirmarlo en vivo habría que emitir una línea al retener.

### 3.8 Reconexión
Si cae la conexión o falla una entrada, el agente se reconecta y sigue.
- **CONFIRMADO (log)**: `22:31:58 error de entrada (VncError); reconectando` (tarea `2f39f9f6`).
- **SUPUESTO**: el otro camino, `conexión perdida; reconectando` (cuando `connected` es falso al inicio de un paso), no aparece en ningún log.

## 4. Puertas de decisión Jev (tercero: TypeSafe; si fallan, el agente sigue)

Jev entra solo en estas cuatro puertas, vía OpenRouter. Si la llamada falla o está apagada (`JEV_ENABLED=0`), la puerta responde "sin dato" y el flujo sigue (falla abierto).

### 4.1 Ruta al entrar (`choice`: change, question, export, unsafe)
- **CONFIRMADO (log)**: `19:00:19 jev choice: unsafe conf=0.95` (tarea `7e178506`, la que pedía la contraseña del escritorio y la clave del modelo) y `19:20:18 jev choice: change conf=1` (tarea `b1248546`).
- Si la ruta es `question`, el agente no escribe y solo responde.

### 4.2 Ambigüedad antes de escribir (`noul` ≥ 0,9 retiene la escritura, hasta 2 veces)
- **CONFIRMADO (log)**: `22:20:20 jev noul ambiguity=0.84` (tarea `cea29e88`) y `19:28:35 jev noul ambiguity=0.86` (tarea `c21caa72`).
- **SUPUESTO**: ningún valor observado llegó a 0,9, así que la retención por Jev no se vio disparar.

### 4.3 Prueba antes de cerrar (`noul` < 0,3 devuelve al agente)
- **CONFIRMADO (log)**: `19:23:35 jev noul proof=0.95` (tarea `b1248546`, aceptada) y `22:49:30 jev noul proof=0.28` (tarea `3c757366`, terminó `fallida`).

### 4.4 Petición de credenciales (`noul` ≥ 0,75 rechaza sin actuar)
- **CONFIRMADO (log)**: `22:18:29 jev noul secret-request=0.01` (tarea `cea29e88`, tarea normal: la puerta corre y no dispara).
- **CONFIRMADO (prueba)**: `tests/test_loop.py::test_credential_request_is_refused_without_acting`.
- **SUPUESTO**: en las dos tareas reales que pedían un secreto (`7e178506`, `e01ef6be`) no hay línea `secret-request`; las rechazó el modelo en el primer paso (`done`, estado `fallida`), no la puerta. La puerta con valor alto no se observó.

## 5. Resumen y secretos

### 5.1 Resumen determinista
`compose` arma el `resumen` con plantillas: `respuesta:` primero en las preguntas, luego lo hecho y "Verificado en pantalla:". En un fallo: "No se completó la tarea." y la razón, y en ambigüedad "Identificadores:" con los códigos de cada candidato.
- **CONFIRMADO (log)**, pregunta (tarea `9a801436`): `respuesta: 161.000 / Fila S-11 Ecografía abdominal, columna Famisanar: 161.000. / Verificado en pantalla: Tabla Servicios y tarifas: S-11 Ecografía abdominal, columna Famisanar 161.000`
- **CONFIRMADO (log)**, fallo con identificadores (tarea `d3775c81`): `No se completó la tarea. El sistema respondió 'Agenda llena para ese día' al aplicar la cita del jueves 15/10 a las 10:20 con el Dr. Andrés Salas; la cita no se creó` y `Identificadores: P-0036, CC 41888999, Dr. Andrés Salas Gutiérrez, 15/10/2026 10:20`.
- **CONFIRMADO (prueba)**: `tests/test_composer.py::test_respuesta_first_line_and_only_on_terminada`.

### 5.2 Depurador de secretos (`Scrubber`)
Quita la contraseña del escritorio, el token del equipo, la clave del modelo, patrones tipo `sk-…` y pares "clave: valor" de todo `resumen` y de cada línea de `pasos`.
- **CONFIRMADO (prueba)**: `tests/test_composer.py::test_scrubs_password_token_and_key_shapes`, `test_scrubs_labelled_credentials_from_a_summary`.
- **CONFIRMADO (log)**: aparece `[oculto]` en un resumen real (tarea `2f39f9f6`), pero por un falso positivo ya corregido: ver hallazgo 1.

### 5.3 Rechazo de tareas que piden revelar secretos
- **CONFIRMADO (log)**: tarea `7e178506`: `No se completó la tarea. La tarea pide revelar la contraseña del escritorio y la API key del modelo, que son secretos. No se deben escribir ni compartir, así que no se realiza la acción.` Ninguna línea del log contiene el secreto.

## 6. Presupuesto

### 6.1 Tope de gasto de modelo
`Ledger` suma el costo de cada llamada; al llegar a `BUDGET_USD` lanza `BudgetExceeded` y la tarea termina `fallida` con "Presupuesto de modelo agotado."
- **SUPUESTO**: el tope no se alcanzó en la corrida. Para confirmarlo basta arrancar con `BUDGET_USD=0.01` y lanzar una tarea.

## 7. Talk to My App
Página `apps/talk-to-my-app/talk-to-my-app.html`: escribe la tarea en lenguaje cotidiano, la envía a `POST /tasks`, sondea y muestra pasos, respuesta y resumen. Los datos de conexión (URL, token, escritorio) se guardan solo en memoria de la pestaña.
- **CONFIRMADO (corrida local de grabación)**, 2026-10-10 15:17 MDT contra el entrypoint público: estado "Runtime conectado", después `Paso 2: Lista de clientes visible. Pulso Crear cliente.`, y al final `Aparece 'Cambios aplicados' y el formulario ahora es Cliente CL-0143 con los datos correctos; guardado. Verificado en pantalla: …`. La captura es `video-operario/captures/talk_to_my_app_console_live_1280x800.mp4`.
- Parte de la página sigue siendo contenido de ejemplo (la tarjeta "Paused for review", la lista Recientes y el marco de vista previa); solo el chat, los pasos, la respuesta y el recibo son en vivo.

## Hallazgos

1. **Falso positivo del depurador (corregido).** El resumen de la tarea `2f39f9f6` dice `Datos clave: [oculto] C-1711, C-1712, C-1713`. El patrón "clave: valor" tomó la palabra "clave" de "Datos clave" y ocultó un dato legítimo. Se perdía información, no se filtraba nada. El commit `4ad20a7` renombró la etiqueta a "Identificadores" y añadió una prueba (`test_reason_keys_are_never_redacted_by_the_credential_patterns`); las líneas de log de esta bitácora son anteriores a ese arreglo.
2. **La puerta de secretos no se vio disparar.** Las dos tareas que pedían un secreto las rechazó el modelo; el log solo muestra la puntuación 0,01 en una tarea normal.
3. **La retención por premisa y por ambigüedad no deja línea de log.** Se ven en el historial interno pero no en `pasos`; por eso solo se confirman por prueba (premisa) o no se confirman (Jev).
4. **Dos hechos del servicio que afectan a quien lo use:** sin `OPENROUTER_API_KEY`, `MODEL_FAST` y `MODEL_STRONG` toda tarea termina al instante `fallida` con "el agente no tiene configurado el modelo"; y sin volumen en `DATA_DIR`, un despliegue borra el registro y el contador de gasto.
5. **Horas.** Los logs de `collected/tasks.json` están en hora del servidor (UTC); las narrativas en `collected/narratives/` están en hora de Denver (MDT, seis horas menos).
