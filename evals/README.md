# Evals — direction following

Evals are how agents improve instead of just running. This folder scores
**how well agents follow human directions**, using the chat-style transcripts
in `transcripts/` as the raw material.

## The loop

1. An agent works from human directions; the back-and-forth is recorded in
   `transcripts/<agent>-<phase>.md` (chat format, lightly cleaned, no secrets).
2. `direction_eval.py` extracts every (direction → response) pair and scores
   each with a Jev Score judgment: 0 = ignored, 1 = partial, 2 = satisfied.
3. Pairs scoring < 2 go to a misses file. **The agent works the misses, then
   re-runs the eval.** That is the self-improvement loop.
4. The mean score trends up across runs. That trend is the evidence that the
   agent is getting better at taking direction — show it in the debrief.

## Run it

```bash
OPENROUTER_API_KEY=... python evals/direction_eval.py transcripts/amanda-design-phase.md
```

Reports land in `evals/reports/`: a markdown report and a JSON misses file.
Use `--limit N` to score the first N pairs while iterating.

## Why Jev, not a VLM rubric

Direction-following is a judgment call ("did this response do what was
asked?"), exactly what typed classification is for. Jev Score returns a
calibrated 0–2 against fixed criteria instead of a VLM's paragraph of
maybe. It is also ~$0.042/M input tokens with no output charge — scoring
a whole day's transcript costs cents.

## Scope note

This evals the *agents* (did Amanda / hack-frontier do what Juan asked?).
Task performance (did Operario complete E1–E5?) is scored separately by
`__check` and the repo's pytest suite.

## Synthetic capability matrix

`synthetic_matrix.py` is our own task eval beyond the 5 canonical examples:
it generates synthetic scenarios across the 5 capabilities the hidden set
grades (create, update, count, export, refuse), each with a self-verifiable
outcome constructed by the harness (read-back queries, planted homonyms).

- Runs each scenario from a clean `__reset` against the **deployed**
  entrypoint — the real contract path.
- Reports per-capability pass rates to `evals/reports/`.
- 15 scenarios ≈ 40–70 min and a few dollars of model budget. Tune with
  `--n`, `--only <capability>`, `--seed`.
- Needs env: `PRACTICE_BASE`, `TEAM_TOKEN`, `ENTRYPOINT_URL`,
  `DESKTOP_URL`, `DESKTOP_PASSWORD`.
- Do not run during hidden-validation windows; it owns the practice desktop
  while it runs.
