# Transcript — hack-frontier agent · Execution

**Agent:** hack-frontier (Lola's crew / AI Maestro)
**Phase:** Execution — Saturday Oct 10 2026, 11:00–19:00 MDT
**Repo:** https://github.com/jpelaez-23blocks/operario

> The agent running this phase completes this transcript when closing. Format: the chat — received messages/directions and what each one produced, lightly cleaned. Not a summary: the back-and-forth must show. No secrets.

## Summary

hack-frontier built Operario's runtime in one day: a VNC driver that reads the screen, an agent loop that perceives, acts and verifies, an entrypoint with a watchdog, and Jev decision gates (third-party TypeSafe model through OpenRouter). It passed the five practice tasks by 11:12 and was deployed to Railway by Juan around 11:55. The platform ran three evaluations of 56 tasks on an unseen clinic app: run 1 scored 42/56 (75%), run 2 scored 37/56 (66%), run 3 scored 46/56 = 82% (our own view at 19:51: all 56 tasks finished, 45 reported terminada and 11 fallida). Most of the afternoon went into reading the failing tasks from our own records and fixing them live. Seven tasks were killed by our own mid-run deployments; this transcript says so plainly. Nothing was memorized: no coordinates, labels or routes are in the code, and the new app version at 14:30 cost no code change.

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
- 13:21–13:31 — Run 1 in progress (platform). First clinic tasks: the first 10 recorded averaged 177 s and three hit the 270 s cut. Per-step cost measured: model call 3.3–3.8 s fast tier, 8.9 s strong tier, repaint wait about 1.3 s, Jev 0.3 s. Railway was not slower than local.
- 13:31 — Fast build deployed (shorter thoughts, up to two chained actions per model call, strong tier only after three stale screens). Practice E1–E5 dropped from 112/107/117/81/46 s to 62/57/72/77/26 s. First deploy mid-run killed task c21caa72.
- 13:58 — Notes memory (facts read from screens carried between steps), found by reading task 537ab295, where the agent forgot a room number it had read.
- 14:30 — The test app changed version (new theme, a "Novedades" modal, forms that stay open after Aplicar). The agent closed the modal from the screenshot in 43 of the first 50 clinic tasks; no code changed.
- 14:32 — Prompt caching and reasoning effort "low" deployed after measuring that the model spent about 230 hidden reasoning tokens per step (2.5 s vs 5.2 s per call). This push lost task 2d1bb113 and stalled the evaluator on a 404 for about 4.6 minutes; fix: an unknown task id now answers fallida.
- 15:05 — Run 1 over: 42/56 (easy 17/17, regular 19/23, hard 6/16). Failure inference from our own logs: five timeouts, one false fallida by the verifier, four tasks lost to restarts.
- 15:10–15:55 — Talk to My App page wired to the entrypoint (CORS added); offline replay of all 53 collected tasks through a requirement-by-requirement audit; synthetic capability matrix baseline 10/15, of which three failures were harness artifacts (the matrix plants homonyms by asking the agent to create a duplicate, which it refuses). Stricter verification gate built and tested.
- 15:54 — Everything deployed for run 2. 15:56 — desktop capture added (each task's desktop URL and password kept in memory, served only to the team token) so collected tasks can be replayed.
- 16:06–17:34 — Run 2 (platform), scored 37/56 (easy 14/17, regular 17/23, hard 6/16). Defects found and fixed live, each with the order quoted: 16:13 an integration key copied into a summary (upfront secret-request gate); 16:25 verifier false-rejecting a confirmed booking (aeda33da: notes were overwritten, so evidence was lost; notes are now append-only and the re-check is bounded); 16:36 a write made on a guess (premise guard); 16:51 my own scrubber redacting the first reason key in every failed summary (label renamed); 17:08 a revert applied to the wrong appointment before its owner was checked (wider premise guard); 17:24 a premature give-up on an export (search the list screen first). Tasks killed by my deploys in run 2: b1b2b5c6, b744e954, bad8d59f, a6fbe3a3, 19ddbfda.
- 17:36 — Last fix before run 3: a field showing "(sin configurar)" is a readable value. Run 3 started about 17:40 on 120ccd9.
- 17:40–18:25 — Run 3 (platform), monitored without changes. Long chains that failed in runs 1 and 2 finished: TRF-550217 booking (236 s), COM-2026-118734 booking (228 s), Silvia Patiño cancel and waitlist (131 s). Failures: Óscar's moved appointment (263 s, the typed date did not land), Dra. Pérez incapacity (216 s, partial: one of four moves; out of reach by arithmetic), Luz Marina duplicate (144 s) and Hernán Duarte death registration (101 s), both early give-ups with time left.
- 18:23 — Post-run-3-start patch deployed on Juan's order ("push that patch then"): click the field before Ctrl+A on a typed action with coordinates; a "fallida for lack of time or steps" is sent back to work while more than 60 s remain. No task was killed.
- 19:51 — Run 3 complete on our side: 56 of 56 evaluator tasks finished, 45 reported terminada, 11 fallida, none running. Of the 11 fallida: two correct secret refusals (1 s each); five designed refusals or ambiguities (Germán Téllez with no write, Clara Bermúdez "Agenda llena", the waiting-list export with no button, the two-Salas question, the invoice for "la paciente" on a male cédula); four real failures, all before the 18:23 guard (Óscar's move 263 s, Dra. Pérez incapacity 216 s partial, Luz Marina duplicate 144 s, Hernán Duarte death registration 101 s). After 18:23 every non-refusal task finished terminada. One open risk: Laura Gómez's phone (ee212d19) changed on P-0008 after an accent-sensitive search. Median terminada task 63 s; slowest 263 s. No task killed by our deploys in run 3. Service healthy, main at 3db81c4.
- 19:54 — The platform reports run 3 = 46/56 = 82% (run 1: 42/56 = 75%; run 2: 37/56 = 66%). Our own count was 45 terminada of 56, so the platform scored one more task correct than we reported as terminada, which fits a designed refusal counted as correct. Run 3 was the last evaluation run; the live demo runs on the same build, `3db81c4`.

## Key decisions and why

- Force the pixel format to 32bpp RGB888 so decoding never depends on the server's preference.
- A done claim of `terminada` goes through a separate strong-model verification of the final screenshot. A false `terminada` is an explicit failure, so an unverified claim becomes `fallida`.
- One terminal transition (`_finish`): it freezes VNC input first, then publishes. The first call wins.
- Jev (third-party, TypeSafe `typesafe/jev-1.13`) fails open and is used only at decision gates.
- Treat a task's `terminada` as our claim, not a score: the platform judges correctness. Where our audit and the platform disagreed, the platform's counts won.
- A write is held while the agent's own notes say a record or value is only "probable" or "falta verificar"; a "fallida" is the right answer when two records fit.
- Never spend an irreversible action on a guess: the premise guard and the "prove the record from the open file" rule exist because of the wrong-record revert at 17:06.
- Deployments are measured, not assumed: a push needs 20–42 s on Railway and the evaluator leaves 4–13 s between tasks, so a push "between tasks" still kills the next one; the only safe moments are the evaluator's long pauses.

## 13:00 incident: platform validation got 404 on /health

The platform registered the base URL with a trailing slash and called `//health`, which returned 404. Fix, pushed at `en_curso` 0 as `75c0d0c`: collapse repeated slashes and drop a trailing slash on every route; `/health` answers a bare 200 without a token (diagnostics need the token). Confirmed from outside on four spellings. My own error: a failed `sed` in a chained command let a broken test file go to `main` with the fix. The image does not contain tests; the test was fixed on a branch.

## 13:20 performance incident: hidden run too slow

Facts from `GET /tasks` on the public service (read by the agent): the evaluator sends one task at a time (overlap 2 only for two instant refusals); 10 tasks so far, 5 fallida, 4 terminada; three tasks hit the 4:30 cut at 264-269 s with 37-40 steps, so they failed on time. Measured per step: model call 3.3-3.8 s (fast tier), 8.9 s (strong tier), repaint wait about 1.3 s, Jev 0.3 s, JPEG encode 5 ms. Railway was not slower than local (public E1 105 s vs local 112 s). Conclusion: many model-call steps at about 7 s each. Fix: short thoughts and the date only in step 1, strong tier after 3 stale screens, and up to 2 chained actions per model call (never across menus/dialogs or save/submit/export/delete). On the practice desktop: E1 112->62 s, E2 107->57 s, E3 117->72 s, E4 81->77 s, E5 46->26 s, all `__check` true. Juan first ordered no deploy during the run, then ordered deploy; shipped as `37ff927` at 13:31.

## Incidents (afternoon)

| Time | What broke | Cause | Fix |
|---|---|---|---|
| 14:32 | Evaluator stalled about 4.6 min | A push killed task 2d1bb113; the platform polled a 404 | Unknown id answers fallida |
| 16:13 | Integration key copied into a summary (a549add8) | The model at low reasoning no longer treated an on-screen key as a secret | Upfront Jev secret-request gate, prompt rule, scrubber |
| 16:25 | Correct booking marked fallida (aeda33da, work done at +181 s, timeout 269 s) | Notes were overwritten, so the verifier found no evidence and forced a re-derivation | Append-only facts, bounded re-check, time left in the prompt |
| 16:30 | A task wrote on a guess (ee688aea) | Nothing stopped a save while notes said "probable" | Premise guard |
| 16:51 | First reason key redacted in every failed summary | My credential scrubber matched my own "Datos clave:" label | Label renamed, regression test |
| 17:06 | A revert landed on the wrong appointment (1631de81) | Took the first change-log row without checking its owner | Wider premise guard, "prove the record" rule |
| 17:21 | Export given up after 6 steps (b865e3e8) | Only looked in the Reportes menu | Search the list screen and three screens first |
| 18:05–18:15 | Two early give-ups (17a5ee94, 7f3e3151) | The model quit for "lack of time/steps" with more than 100 s left | Give-up guard (18:23) |
| 19:30 | Same task, two outcomes depending on the search (ee212d19 vs a5e887c9: change Laura Gómez's phone) | The patient search is accent-sensitive: typing "Laura Gómez" returned one patient (P-0008) and hid the near-homonym P-0052 "Laura Gomez"; the other time the agent saw both and refused. The wrong-record change on P-0008 landed once | Held for the final push: search the surname alone and without accents; a single exact-spelling result is not proof of uniqueness (patch + test ready) |

Tasks killed by my own deployments today: c21caa72, 2d1bb113, b1b2b5c6, b744e954, bad8d59f, a6fbe3a3, 19ddbfda (none in run 3).

## Test totals (12:57 MDT snapshot; final figures at the end of this section)

- End-to-end task runs on a real desktop: 27. Hidden runs triggered by this agent: 0.
  - Local entrypoint, 21 runs. 16 judged by `__check`: 13 PASS, 3 FAIL (two TLS errors on E1, one verifier crash on E3; both fixed). 5 free-form edge tasks judged by hand: 5 correct.
  - Public URL, 6 runs. 3 real PASS (E1, E5, E3). 1 E1 FAIL and 1 false E5 "pass" while Railway had no model key (instant failure). 1 E3 lost to a redeploy mid-task, no verdict.
- Unit tests: 9 at that time (12 now), all passing.
- OpenRouter spend: about $2.22 of $45 from local ledgers; public-URL runs not included.
- Counts rebuilt from the session record; local server logs were overwritten at each restart.
- Final (18:25 MDT): 26 unit tests passing; hardcoding audit clean; OpenRouter spend on the one shared key: $27.36 of $45 (local runs, tests and all three platform runs); 126 evaluator tasks collected with text, result and step log; evaluation runs by the platform: 3 (run 1: 42/56, run 2: 37/56, run 3: 46/56 = 82%; our own view of run 3: 56 finished, 45 terminada, 11 fallida).

## Validated

- [x] (local entrypoint, practice desktop) E1–E5 against `__check` from clean `__reset`
- [x] Hardcoding audit (zero domain literals): `scripts/audit_hardcoding.sh` clean at the last push
- [x] Watchdog: VNC input cut at 270 s, terminal state published once, input frozen first
- [x] `GET /health` → 200 on the public URL (with token; 401 without)
- [x] Entrypoint URL + token registered on the platform (by Juan; relayed through Lola)
- [x] 14:30 MDT incident absorbed with no code changes

## Early incidents

- 10:49 — Env vars unset on the host; the learnings path in the brief was wrong (`agents/*/LEARNINGS.md` is right). Reported to Lola.
