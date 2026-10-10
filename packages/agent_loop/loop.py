"""Perceive -> act -> verify loop. One screenshot in, one validated Action out, then act,
wait out the repaint, and look again. The model never sees the desktop password."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from pydantic import ValidationError

from packages.agent_loop.schemas import Action, Verification, action_schema_text
from packages.model_gateway.gateway import Gateway, parse_json
from packages.vnc_driver.session import InputFrozen, VncError, VncSession

log = logging.getLogger("operario.loop")

SYSTEM = f"""You operate a desktop application that has no API, only a screen (1280x800), like a new employee.
You receive the task, your action history and the current screenshot. You answer ONE action as strict JSON:
{action_schema_text()}
First step, before anything else:
- When the task contains any date-relative word (vencidas, hoy, ayer, atrasadas, pendientes, próximos, vigentes,
  esta semana, este mes, or similar), first locate the app's displayed date on screen and record it in "thought"
  on your first step. All date comparisons use that date. Never use your own knowledge of the real date.
- Keep a running memory in "notas" (under 500 characters): every fact you read that you will need later (ids, names,
  doctor, room, authorization or document numbers, amounts, dates, what you already tried that failed). Your notas
  replaces the previous one each step, so copy forward everything still needed. Check notas before re-reading a screen.
- Keep "thought" under 120 characters: what you see and what you do next. Do not repeat the date after the first step.
Rules:
- Coordinates x,y are normalized 0-1000 over the full screenshot (0,0 top-left). Aim at the center of the target.
- One action per answer. After each action you get a new screenshot; check it before the next step.
- The screen repaints up to 1 s after a click. If the screen looks unchanged, use "wait" once before retrying.
- Typing into a field that already has text appends. Use "replace": true on type to select all first.
- To save time you may chain up to 2 follow-up actions in "then" (click, type or key), run in order without a new
  screenshot. Chain ONLY when every follow-up targets something already visible now that the first action cannot
  move or change (for example: click a field, then type into it; type, then press tab). Never chain after an action
  that opens a menu, dialog, dropdown or new page, and never chain a save, submit, export, delete or confirm click:
  those need a fresh look first.
- Never do anything the task did not ask for. No extra edits, no deletes, no duplicate records.
- "Today" is the date the app shows, not your own knowledge.
- Read before you write. If the task names a record (a person, an item) and the screen shows more than one
  match, or the task is impossible, unsafe or ambiguous, do NOT guess: answer done with estado "fallida",
  "razon" with the cause, and "claves" listing the identifying values you saw (ids, numbers, codes) of each candidate.
- For a question, answer done with estado "terminada" and "respuesta" holding only the requested value(s);
  two values go in one string separated by "; " in the order asked. If the question cannot be answered from
  the app, answer fallida and give no respuesta.
- For a change or export, finish only when the screen shows proof it happened; put that proof in "evidencia".
- Never write passwords, tokens or secrets anywhere.
- Answer with the JSON object only."""

VERIFY_SYSTEM = """You audit an agent's work on a desktop application. You see the final screenshot, the task and the
agent's claim. Decide whether the screen itself proves the task is complete. Be strict: if the proof is not visible
(for example a form still open, an error shown, an unsaved field), verificada is false.
Answer JSON only: {"verificada": bool, "evidencia": str}"""


@dataclass
class Outcome:
    estado: str                      # terminada | fallida
    hizo: str = ""
    respuesta: Optional[str] = None
    razon: str = ""
    claves: list[str] = field(default_factory=list)
    evidencia: str = ""
    steps: int = 0


def _px(a, width: int, height: int) -> tuple[int, int]:
    return round(a.x * (width - 1) / 1000), round(a.y * (height - 1) / 1000)


def _hash(png: bytes) -> str:
    return hashlib.md5(png).hexdigest()


class AgentLoop:
    def __init__(self, gw: Gateway, session: VncSession, task: str, deadline: float,
                 emit: Callable[[str], None] = lambda s: None):
        self.gw, self.s, self.task, self.deadline, self.emit = gw, session, task, deadline, emit
        self.history: list[str] = []
        self.verify_rejections = 0
        self.ambiguity_blocks = 0
        self.route_hint = ""
        self.route = ""
        self.notes = ""

    def _left(self) -> float:
        return self.deadline - time.monotonic()

    async def _decide(self, shot: bytes, prev: Optional[bytes], note: str, tier: str) -> Action:
        hist = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(self.history[-12:])) or "(none yet)"
        text = f"TASK: {self.task}\n{self.route_hint}\nYOUR NOTES SO FAR: {self.notes or '(none)'}\n\nACTIONS SO FAR:\n{hist}\n\n{note}\nCurrent screenshot attached."
        imgs = [shot]
        err = ""
        for attempt in range(3):
            raw = await self.gw.chat(tier if attempt < 2 else "strong", SYSTEM, text + err, imgs, timeout=min(20 if tier == "fast" else 40, max(8, self._left() - 5)))
            try:
                return Action.model_validate(parse_json(raw))
            except (ValueError, ValidationError) as e:
                err = f"\n\nYour previous answer was invalid ({str(e)[:200]}). Answer valid JSON only."
        raise RuntimeError("el modelo no produjo una acción válida")

    async def _verify(self, shot: bytes, claim: Action) -> Verification:
        text = (f"TASK: {self.task}\nAGENT CLAIM: estado={claim.estado}, evidencia={claim.evidencia!r}, "
                f"respuesta={claim.respuesta!r}\nACTIONS:\n" + "\n".join(self.history[-10:]))
        for attempt in range(2):
            raw = ""
            try:
                raw = await self.gw.chat("strong", VERIFY_SYSTEM, text + "\nAnswer with the JSON object only.", [shot],
                                         max_tokens=400, timeout=min(40, max(8, self._left() - 5)))
                return Verification.model_validate(parse_json(raw))
            except (ValueError, ValidationError):
                log.warning("verifier returned unusable output (len=%d)", len(raw))
        # The verifier is down, not rejecting: fall back to the agent's own cited evidence.
        return Verification(verificada=bool(claim.evidencia or claim.respuesta),
                            evidencia=(claim.evidencia or claim.respuesta or "sin verificador")[:300])

    # ---- Jev decision gates (third-party TypeSafe model, fail open) ----------
    async def _gate_route(self) -> None:
        ans = await self.gw.jev(f"Task given to an operator of a desktop application: {self.task}", {"route": {
            "type": "choice", "instructions": "What kind of work is this task",
            "criteria": {"change": "Create or modify records", "question": "Answer a question, changing nothing",
                         "export": "Export or generate a report", "unsafe": "Impossible, destructive or unsafe request"}}})
        if ans and "route" in ans:
            r = ans["route"]
            self.route = str(r.get("choice"))
            self.route_hint = f"ROUTE (Jev Choice): {r.get('choice')} (confidence {r.get('confidence')}). "
            self.emit(f"jev choice: {r.get('choice')} conf={r.get('confidence')}")
            if r.get("choice") == "question":
                self.route_hint += "This is read-only: change nothing. "

    async def _gate_ambiguity(self) -> float:
        state = (f"Task: {self.task}\nWhat the operator observed and did so far:\n" + "\n".join(self.history[-10:]))
        ans = await self.gw.jev(state, {"amb": {"type": "noul", "instructions":
            "The operator saw more than one record that fits the person or item named in the task, "
            "and nothing in the task says which one is meant"}})
        v = float(ans["amb"].get("noul", 0)) if ans and "amb" in ans else 0.0
        self.emit(f"jev noul ambiguity={v:.2f}")
        return v

    async def _gate_proof(self, claim: Action, evidence: str) -> float:
        state = f"Task: {self.task}\nClaim: {claim.estado}. Evidence read from the final screen: {evidence}"
        ans = await self.gw.jev(state, {"proof": {"type": "noul", "instructions":
            "The evidence shows the task was actually completed (saved, exported or answered), not just attempted"}})
        v = float(ans["proof"].get("noul", 1)) if ans and "proof" in ans else 1.0
        self.emit(f"jev noul proof={v:.2f}")
        return v

    async def _act(self, a: Action) -> None:
        await self._do(a)
        for c in a.then or []:
            await asyncio.sleep(0.35)  # the field must take focus before the next input
            await self._do(c)

    async def _do(self, a) -> None:
        w, h = self.s.width, self.s.height
        if a.action == "click":
            await self.s.click(*_px(a, w, h))
        elif a.action == "double_click":
            await self.s.double_click(*a.px(w, h))
        elif a.action == "type":
            if a.replace:
                await self.s.select_all_and_type(a.text or "")
            else:
                await self.s.type_text(a.text or "")
        elif a.action == "key":
            await self.s.key(a.keys or "")
        elif a.action == "scroll":
            await self.s.scroll(*a.px(w, h), a.dy or 0)
        elif a.action == "wait":
            await asyncio.sleep(1.0)

    def _describe(self, a: Action) -> str:
        bits = [a.action]
        if a.x is not None:
            bits.append(f"({a.x},{a.y})")
        if a.text is not None:
            bits.append(f"text={a.text!r}{' replace' if a.replace else ''}")
        if a.keys:
            bits.append(f"keys={a.keys}")
        for c in a.then or []:
            bits.append(f"+ {c.action}" + (f"({c.x},{c.y})" if c.x is not None else "")
                        + (f" text={c.text!r}" if c.text is not None else "") + (f" keys={c.keys}" if c.keys else ""))
        return " ".join(bits) + f" — {a.thought[:120]}"

    async def run(self) -> Outcome:
        prev_hash, stale, steps, prev_png = "", 0, 0, None
        note = ""
        await self._gate_route()
        while self._left() > 8:
            if not self.s.connected:
                self.emit("conexión perdida; reconectando")
                await self.s.reconnect()
            await self.s.settle()
            png = self.s.screenshot_jpeg()
            h = _hash(png)
            if h == prev_hash:
                stale += 1
                note = "NOTE: the screen did not change after your last action."
            else:
                stale, note = 0, note if note.startswith(("VERIFIER", "JEV")) else ""
            prev_hash, prev_png = h, png
            tier = "strong" if stale >= 3 or self.verify_rejections else "fast"
            a = await self._decide(png, prev_png, note, tier)
            steps += 1
            if a.notas:
                self.notes = a.notas[:1200]
                self.emit(f"notas: {self.notes[:200]}")
            self.emit(f"paso {steps}: {self._describe(a)}")
            note = ""
            if a.action == "done":
                if a.estado == "terminada":
                    v = await self._verify(png, a)
                    self.emit(f"verificación: {v.verificada} — {v.evidencia[:100]}")
                    if not v.verificada and self.verify_rejections < 2 and self._left() > 40:
                        self.verify_rejections += 1
                        self.history.append("claimed done, verifier rejected")
                        note = f"VERIFIER: the screen does not prove completion ({v.evidencia}). Continue or fix."
                        continue
                    if not v.verificada:
                        return Outcome("fallida", razon="no se pudo verificar en pantalla que la tarea quedara completa",
                                       steps=steps)
                    if self.verify_rejections < 2 and self._left() > 40 and \
                            await self._gate_proof(a, a.evidencia or v.evidencia) < 0.3:
                        self.verify_rejections += 1
                        self.history.append("claimed done, Jev judged the evidence insufficient")
                        note = "VERIFIER: the evidence does not show the task was completed. Look again and finish properly."
                        continue
                    return Outcome("terminada", hizo=a.thought,
                                   respuesta=a.respuesta if self.route in ("", "question") else None,
                                   evidencia=a.evidencia or v.evidencia, steps=steps)
                return Outcome("fallida", razon=a.razon or "", claves=a.claves or [], steps=steps)
            writes = a.action == "type" or any(c.action == "type" for c in a.then or [])
            if writes and self.ambiguity_blocks < 2 and len(self.history) >= 3 \
                    and await self._gate_ambiguity() >= 0.9:
                self.ambiguity_blocks += 1
                self.history.append("held a write: Jev flagged possible ambiguity")
                note = ("JEV: several records may fit the task. Before writing, confirm exactly one record matches. "
                        "If more than one fits, finish with done/fallida naming each candidate's identifying values.")
                continue
            self.history.append(self._describe(a))
            try:
                await self._act(a)
            except InputFrozen:
                return Outcome("fallida", razon="tiempo agotado", steps=steps)
            except (VncError, OSError) as e:
                self.emit(f"error de entrada ({type(e).__name__}); reconectando")
                await self.s.reconnect()
        return Outcome("fallida", razon="se agotó el tiempo sin completar la tarea", steps=steps)
