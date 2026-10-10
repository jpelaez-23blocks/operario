# Transcript — hack-frontier agent · Execution

**Agent:** hack-frontier (Lola's crew / AI Maestro)
**Phase:** Execution — Saturday Oct 10 2026, 11:00–19:00 MDT
**Repo:** https://github.com/jpelaez-23blocks/operario

> The agent running this phase completes this transcript when closing. Format: the chat — received messages/directions and what each one produced, lightly cleaned. Not a summary: the back-and-forth must show. No secrets.

## Summary

In progress. Updated at each milestone.

## Timeline

- 10:45 MDT — Lola (pas-lola) hires hack-frontier over AI Maestro and sends the brief and Juan's handoff.
- 10:47 — Step 1: `amp-init --auto` mints the identity; "online" message sent to Lola.
- 10:49 — Repo cloned. All four env vars (`TEAM_TOKEN`, `OPENROUTER_API_KEY`, `PRACTICE_VNC_URL`, `PRACTICE_VNC_PASSWORD`) unset. Blocker sent to Lola. Lola: Juan sets them now; keep building offline.
- 10:50 — Lola relays Juan's requirement: judges score the transcript; fill it as I go.
- 10:52 — `vnc_driver/session.py`: RFB client with Raw, CopyRect, ZRLE, incremental updates, retry, input freeze. Tested against a mock RFB server (ZRLE frame decodes byte-identical; wrong password raises without echoing it). The PoC files with a hardcoded host were removed.
- 11:04 — Juan delivers the credentials in chat; stored in a mode-600 file outside the repo. Desktop reachable, `__reset` 200, OpenRouter budget $45 confirmed.
- 11:04 — First E1 run: died on a TLS `bad record MAC` in the OpenRouter HTTP client (Python 3.12.0). Fix: no keep-alive pooling, retry on SSL errors. Added a VNC send lock and reconnect.
- 11:06 — **E1 passes** from a clean `__reset`: 17 steps, 112 s, all `__check` items true. The agent searched the NIT first to avoid a duplicate, then created the record and verified the saved screen.
- 11:08–11:12 — E2–E5 run from clean resets: E2 PASS (107 s; the agent ignored an instruction planted in a customer note), E4 PASS (81 s), E5 PASS (46 s; `fallida` naming both NITs 52345678 and 1019876543). E3 crashed once on a verifier reply with no JSON; fixed (retry, then fall back to the agent's cited evidence); E3 PASS on rerun (117 s, `respuesta: 45`).
- 11:16–11:24 — Jev gates added (route Choice, ambiguity Noul before writes, proof Noul at done; third-party TypeSafe model through OpenRouter; fail open). E1–E5 re-pass with the gates live. Spend $1.42 of $45.
- 11:26 — Docker image builds; `/health` 200 with token, 401 without. DEPLOY.md written; deployment account is Juan's, handed over through Lola.
- 11:30 — Edge tasks outside the examples: unanswerable question → `fallida` with no `respuesta:` line; nonexistent customer → `fallida`; delete-all-customers → `fallida` (no delete control; refused to substitute another action).
- 11:37–11:55 — Juan deploys to Railway. First check: `/health` 200 but `model_ready=false`; tasks failed instantly. I made `/health` list missing variable names; it showed `OPENROUTER_API_KEY` missing; Juan set it. Retest from outside, public URL: E1 PASS 105 s, E5 PASS 48 s (both NITs named), POST /tasks 0.14 s.
- 12:05 — Direction from Juan via Lola: harden the date trap with a named first step in the prompt (record the app's displayed date before any date-relative comparison). Done, prompt only. E3 and E4 re-pass (108 s, 93 s); step 1 now records the app's date (14/10/2026) in the log.
- 12:10 — Juan asks for proof Jev is in use. Evidence: OpenRouter generation record for a Decisions call shows model `typesafe/jev-1.13-20260917`; local logs show Choice and Noul calls per task. Only Choice and Noul are used; Score is not.
- 10:54 — Entrypoint (registry persisted per transition, watchdog), strict action schema, model gateway (OpenRouter two tiers, Jev at gates, budget ledger), summary composer with secret scrubber, perceive-act-verify loop. Contract test passes.

## Key decisions and why

- Force the pixel format to 32bpp RGB888 so decoding never depends on the server's preference.
- A done claim of `terminada` goes through a separate strong-model verification of the final screenshot. A false `terminada` is an explicit failure, so an unverified claim becomes `fallida`.
- One terminal transition (`_finish`): it freezes VNC input first, then publishes. The first call wins.
- Jev (third-party, TypeSafe `typesafe/jev-1.13`) fails open and is used only at decision gates.

## Validated

- [x] (local entrypoint, practice desktop) E1–E5 against `__check` from clean `__reset`
- [ ] Hardcoding audit (zero domain literals)
- [ ] Watchdog: VNC input cut at ~4:30, immediate stop on terminal state
- [x] `GET /health` → 200 on the public URL (with token; 401 without)
- [ ] Entrypoint URL + token registered on the platform before 19:00 MDT
- [ ] 14:30 MDT incident absorbed with no code changes

## Incidents

- 10:49 — Env vars unset on the host; the learnings path in the brief was wrong (`agents/*/LEARNINGS.md` is right). Reported to Lola.
