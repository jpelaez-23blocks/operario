#!/usr/bin/env python3
"""Direction-following eval for agent transcripts.

Scores how well an agent's responses satisfy the human's directions, using
the chat-style transcripts in transcripts/ (e.g. **Juan:** -> **Amanda:**).

Each (direction, response) pair goes to a Jev Score judgment via the
OpenRouter Decisions API. Pairs scoring < 2 are written to a misses file --
that is the self-improvement loop's input: the agent works the misses, then
re-runs the eval.

Usage:
    OPENROUTER_API_KEY=... python evals/direction_eval.py transcripts/amanda-design-phase.md
    OPENROUTER_API_KEY=... python evals/direction_eval.py transcripts/hack-frontier-agent.md --limit 5

Env:
    OPENROUTER_API_KEY   required
    JEV_MODEL            optional, default typesafe/jev-1.13
    OPENROUTER_BASE      optional, default https://openrouter.ai/api
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api")
MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")

TURN_RE = re.compile(r"^\*\*(.+?):\*\*\s*(.*)$")
# Human authors whose turns count as directions.
HUMANS = {"juan"}

CRITERIA = [
    "The response ignores the direction, refuses without reason, or does something unrelated.",
    "The response partially addresses the direction but misses key parts or needed rework.",
    "The response fully satisfies the direction as stated.",
]


def parse_transcript(path: Path):
    """Return [(direction, response)] pairs from a chat-style transcript."""
    turns = []  # (speaker, text)
    speaker, buf = None, []
    for line in path.read_text().splitlines():
        m = TURN_RE.match(line)
        if m:
            if speaker:
                turns.append((speaker, "\n".join(buf).strip()))
            speaker = m.group(1).strip().lower()
            buf = [m.group(2)]
        elif speaker:
            buf.append(line)
    if speaker:
        turns.append((speaker, "\n".join(buf).strip()))

    pairs = []
    i = 0
    while i < len(turns):
        spk, text = turns[i]
        if spk in HUMANS and text:
            # Collect following agent turns until the next human turn.
            resp_parts = []
            j = i + 1
            while j < len(turns) and turns[j][0] not in HUMANS:
                if turns[j][1]:
                    resp_parts.append(turns[j][1])
                j += 1
            response = "\n\n".join(resp_parts).strip()
            if response:
                pairs.append((text, response))
            i = j
        else:
            i += 1
    return pairs


def jev_score(direction: str, response: str) -> dict:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is required")
    state = f"Human direction:\n{direction}\n\nAgent response:\n{response[:4000]}"
    payload = {
        "state": state,
        "model": MODEL,
        "questions": {
            "satisfaction": {
                "type": "score",
                "instructions": "How well does the agent response satisfy the human direction?",
                "criteria": CRITERIA,
            }
        },
    }
    req = urllib.request.Request(
        f"{BASE}/alpha/decisions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        answers = json.loads(r.read()).get("answers", {})
    return answers.get("satisfaction", {})


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: direction_eval.py <transcript.md> [--limit N]")
    path = Path(sys.argv[1])
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0

    pairs = parse_transcript(path)
    if limit:
        pairs = pairs[:limit]
    print(f"{len(pairs)} direction/response pairs from {path.name}", flush=True)

    results = []
    for n, (direction, response) in enumerate(pairs, 1):
        try:
            ans = jev_score(direction, response)
        except Exception as e:  # noqa: BLE001 -- report and continue
            ans = {"error": str(e)}
        # Jev score answers carry the winning criterion index in various shapes;
        # normalize to an int 0..2 when present.
        score = ans.get("score", ans.get("value", ans.get("index")))
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = None
        results.append(
            {
                "n": n,
                "direction": direction[:500],
                "response_excerpt": response[:500],
                "score": score,
                "raw": ans,
            }
        )
        print(f"  [{n}/{len(pairs)}] score={score}", flush=True)

    scored = [r for r in results if r["score"] is not None]
    avg = sum(r["score"] for r in scored) / len(scored) if scored else 0
    misses = [r for r in results if r["score"] is not None and r["score"] < 2]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    outdir = Path("evals/reports")
    outdir.mkdir(parents=True, exist_ok=True)
    slug = path.stem

    report = [
        f"# Direction-following eval — {path.name}",
        f"_{stamp} UTC · {len(scored)}/{len(results)} pairs scored · model {MODEL}_",
        "",
        f"**Mean score: {avg:.2f} / 2.00**",
        f"**Misses (score < 2): {len(misses)}**",
        "",
        "## Pairs",
    ]
    for r in results:
        mark = {0: "❌", 1: "⚠️", 2: "✅"}.get(r["score"], "❓")
        report += [
            f"### {r['n']}. {mark} score={r['score']}",
            f"**Direction:** {r['direction']}",
            f"**Response:** {r['response_excerpt']}",
            "",
        ]
    (outdir / f"{slug}-report-{stamp}.md").write_text("\n".join(report))

    misses_path = outdir / f"{slug}-misses-{stamp}.json"
    misses_path.write_text(json.dumps(misses, indent=2, ensure_ascii=False))

    print(f"\nmean={avg:.2f} misses={len(misses)}")
    print(f"report: {outdir / f'{slug}-report-{stamp}.md'}")
    print(f"misses: {misses_path}")
    print("Self-improvement loop: fix the misses, then re-run this eval.")


if __name__ == "__main__":
    main()
