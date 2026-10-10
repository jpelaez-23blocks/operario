# Talk to My App

Chat console for Operario: type a task in plain language, watch the agent run
it on the app, get the result back. The "talk to my app" entry interface.

- Single self-contained file: `talk-to-my-app.html` (no build step).
- Runs entirely in the visitor's browser: it calls the entrypoint API directly.
- Connection settings (entrypoint URL, team token, desktop URL/password) are
  entered in the page and kept in memory only — never hardcoded, never stored.
- Contract: `POST /tasks` → `{"task_id"}` · `GET /tasks/{id}` → `{"estado", "resumen"}`.

Deploy: serve the HTML file anywhere static (or open it directly). Point it at
a running Operario entrypoint.
