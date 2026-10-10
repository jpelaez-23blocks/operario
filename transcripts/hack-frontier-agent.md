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

## 13:00 incident: platform validation got 404 on /health

The platform registered the base URL with a trailing slash and called `//health`, which returned 404. Fix, pushed at `en_curso` 0 as `75c0d0c`: collapse repeated slashes and drop a trailing slash on every route; `/health` answers a bare 200 without a token (diagnostics need the token). Confirmed from outside on four spellings. My own error: a failed `sed` in a chained command let a broken test file go to `main` with the fix. The image does not contain tests; the test was fixed on a branch.

## 13:20 performance incident: hidden run too slow

Facts from `GET /tasks` on the public service (read by the agent): the evaluator sends one task at a time (overlap 2 only for two instant refusals); 10 tasks so far, 5 fallida, 4 terminada; three tasks hit the 4:30 cut at 264-269 s with 37-40 steps, so they failed on time. Measured per step: model call 3.3-3.8 s (fast tier), 8.9 s (strong tier), repaint wait about 1.3 s, Jev 0.3 s, JPEG encode 5 ms. Railway was not slower than local (public E1 105 s vs local 112 s). Conclusion: many model-call steps at about 7 s each. Fix: short thoughts and the date only in step 1, strong tier after 3 stale screens, and up to 2 chained actions per model call (never across menus/dialogs or save/submit/export/delete). On the practice desktop: E1 112->62 s, E2 107->57 s, E3 117->72 s, E4 81->77 s, E5 46->26 s, all `__check` true. Juan first ordered no deploy during the run, then ordered deploy; shipped as `37ff927` at 13:31.

## Test totals (as of 12:57 MDT)

- End-to-end task runs on a real desktop: 27. Hidden runs triggered by this agent: 0.
  - Local entrypoint, 21 runs. 16 judged by `__check`: 13 PASS, 3 FAIL (two TLS errors on E1, one verifier crash on E3; both fixed). 5 free-form edge tasks judged by hand: 5 correct.
  - Public URL, 6 runs. 3 real PASS (E1, E5, E3). 1 E1 FAIL and 1 false E5 "pass" while Railway had no model key (instant failure). 1 E3 lost to a redeploy mid-task, no verdict.
- Unit tests: 9 at that time (12 now), all passing.
- OpenRouter spend: about $2.22 of $45 from local ledgers; public-URL runs not included.
- Counts rebuilt from the session record; local server logs were overwritten at each restart.

## Validated

- [x] (local entrypoint, practice desktop) E1–E5 against `__check` from clean `__reset`
- [ ] Hardcoding audit (zero domain literals)
- [ ] Watchdog: VNC input cut at ~4:30, immediate stop on terminal state
- [x] `GET /health` → 200 on the public URL (with token; 401 without)
- [ ] Entrypoint URL + token registered on the platform before 19:00 MDT
- [ ] 14:30 MDT incident absorbed with no code changes

## Incidents

- 10:49 — Env vars unset on the host; the learnings path in the brief was wrong (`agents/*/LEARNINGS.md` is right). Reported to Lola.
