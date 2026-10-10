# Transcript — Amanda · Systems design phase

**Agente:** Amanda (Muse, asistente personal de Juan)
**Fase:** Systems design — sábado 10 oct 2026, 08:00–10:35 MDT
**Reto:** Reto 1 — "El agente que opera lo que no tiene API"

## Resumen

Diseño completo del sistema **Operario**, validación del driver VNC contra el escritorio real, documentos de diseño entregados en la plataforma (30%), monorepo público creado y handoff del build enviado a Lola.

## Línea de tiempo

**08:00–09:30 — Elección y mecánicas.**
Juan elige Reto 1 ("it looks totally uncomfortable"). Confirmo scoring (design 30 / ejecución 40 / demo 15 / debrief 15), deadlines (diseño 11:00, entrypoint 19:00, incidente 14:30) y contrato del evaluador. Copio el README y las 5 tareas de ejemplo al workspace.

**09:15–09:30 — PoC del driver VNC (la capa más riesgosa primero).**
Conecto al escritorio del evento vía `wss://…/websockify`: handshake RFB 3.008, auth DES por challenge-response, screenshot 1280×800 real, clic con hold de 150 ms verificado visualmente (paginación a página 2). El grounding por coordenadas del modelo funciona; mi estimación manual a ojo falló — evidencia a favor de grounding + verificación.

**09:30–09:45 — Investigación de mejores prácticas.**
Síntesis de seguridad (RFB dentro de WSS, SSRF guard, Bearer, parseo estricto del output del modelo, scrubber de secretos), performance (ZRLE + incrementales vs Raw ≈4 MB/frame) y confiabilidad (deadlines cooperativos, persistencia por transición). → `best-practices.md`.

**09:45–10:00 — Arquitectura Operario.**
FastAPI entrypoint (contrato), Agent Loop (percibir→verificar), VNC Driver, Model Gateway (2 niveles OpenRouter), Summary Composer determinista, Watchdog (corte ~4:30). **Decisión estructural:** la URL del escritorio es parámetro, nunca constante — el incidente de las 14:30 (cambio de pantallas) no cambia la arquitectura.

**10:00–10:20 — Documentos de diseño.**
Una página + diagrama, en español, con marca Operario. Tres iteraciones de layout (el builder de artefactos produjo tarjetas superpuestas; reconstruí a mano en HTML/SVG y lo imprimí a PDF, verificando cada render). Incluye capa **Jev Judgment Layer** — propuesta de Juan, verificada disponible en OpenRouter (`typesafe/jev-1.13` vía Decisions API, misma key): Choice enruta, Noul desambigua (E5), Score verifica. Solo en compuertas de decisión.

**10:20–10:35 — Monorepo + handoff.**
Repo público `github.com/jpelaez-23blocks/operario`: `documents/` (3 PDFs), `challenge/` (README + E1–E5 del organizador, auditados sin secretos), `services/entrypoint` (esqueleto), `packages/vnc_driver` (PoC), stubs, `infra/Dockerfile`. Email de handoff a lola@3metas.com: contratar agente hack-frontier y empezar a construir.

## Decisiones clave y por qué

1. **Python 3.12** — el cuello es latencia del VLM, no del lenguaje; velocidad de iteración manda.
2. **Regresión directa de coordenadas** en vez de two-stage — más simple y general; la verificación visual compensa la precisión.
3. **Jev en compuertas, no por paso** — los fallos del reto son de juicio (E5, `terminada` falsa), no de percepción; un Noul tipado decide donde el VLM adivina.
4. **Cero memorización** — ningún literal de dominio en el código; el incidente se absorbe por diseño.
5. **Resumen determinista** — el VLM nunca compone libremente el `resumen` calificado.

## Validado (no planeado)

- Driver VNC funcional contra escritorio real (screenshot + clic verificado).
- Ambos PDFs renderizados y revisados visualmente página por página antes de entregar.
- URLs de entrega verificadas con HTTP 200 antes de pasarlas a Juan.
- Repo sin secretos (grep de credenciales antes de cada push).
