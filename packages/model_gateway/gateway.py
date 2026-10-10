"""OpenRouter gateway: two model tiers plus Jev (third-party, TypeSafe) at decision gates.

Jev is TypeSafe's product (`typesafe/jev-1.13` via the OpenRouter Decisions API), not ours.
Budget is tracked in a ledger file and enforced before every call."""
from __future__ import annotations

import base64
import json
import os
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx

BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api")


class BudgetExceeded(Exception):
    pass


class Ledger:
    def __init__(self, path: str, cap: float):
        self.path, self.cap = Path(path), cap
        self._lock = threading.Lock()
        self.spent = 0.0
        if self.path.exists():
            try:
                self.spent = float(json.loads(self.path.read_text()).get("spent", 0.0))
            except Exception:  # noqa: BLE001
                pass

    def check(self) -> None:
        if self.spent >= self.cap:
            raise BudgetExceeded(f"presupuesto agotado ({self.spent:.2f}/{self.cap:.2f})")

    def add(self, usd: float) -> None:
        with self._lock:
            self.spent += usd
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"spent": round(self.spent, 5)}))


class Gateway:
    def __init__(self):
        self.key = os.environ.get("OPENROUTER_API_KEY", "")
        self.fast = os.environ.get("MODEL_FAST", "")
        self.strong = os.environ.get("MODEL_STRONG", "")
        self.effort_fast = os.environ.get("REASONING_FAST", "low")
        self.effort_strong = os.environ.get("REASONING_STRONG", "low")
        self.jev_model = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
        self.jev_enabled = os.environ.get("JEV_ENABLED", "1") == "1"
        cap = float(os.environ.get("BUDGET_USD", "40"))
        self.ledger = Ledger(os.path.join(os.environ.get("DATA_DIR", "data"), "ledger.json"), cap)
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10),
                                     limits=httpx.Limits(max_keepalive_connections=0))

    @property
    def ready(self) -> bool:
        return bool(self.key and self.fast and self.strong)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    async def chat(self, tier: str, system: str, user_text: str, images: list[bytes],
                   max_tokens: int = 700, timeout: float = 45) -> str:
        """One JSON-mode vision call. tier: 'fast' | 'strong'. Returns the raw text."""
        self.ledger.check()
        model = self.strong if tier == "strong" else self.fast
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        for im in images:
            b64 = base64.b64encode(im).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]},
                {"role": "user", "content": content}],
            "reasoning": {"effort": self.effort_strong if tier == "strong" else self.effort_fast},
            "max_tokens": max_tokens,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "usage": {"include": True},
        }
        last: Optional[Exception] = None
        for attempt in range(3):
            try:
                r = await self.http.post(f"{BASE}/v1/chat/completions", headers=self._headers(),
                                         json=body, timeout=timeout)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPError(f"status {r.status_code}")
                r.raise_for_status()
                data = r.json()
                self.ledger.add(float(data.get("usage", {}).get("cost", 0) or 0))
                return data["choices"][0]["message"]["content"] or ""
            except (httpx.HTTPError, KeyError, ssl.SSLError, OSError) as e:
                last = e
                await _sleep(0.8 * (attempt + 1))
        raise RuntimeError(f"modelo no disponible: {type(last).__name__}")

    async def jev(self, state: str, questions: dict, timeout: float = 8) -> Optional[dict]:
        """Decisions API call. Fails open: returns None on any error or when disabled."""
        if not (self.jev_enabled and self.key):
            return None
        try:
            self.ledger.check()
            r = await self.http.post(f"{BASE}/alpha/decisions", headers=self._headers(), timeout=timeout,
                                     json={"state": state, "model": self.jev_model, "questions": questions})
            r.raise_for_status()
            return r.json().get("answers")
        except Exception:  # noqa: BLE001
            return None


async def _sleep(s: float) -> None:
    import asyncio
    await asyncio.sleep(s)


def parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("sin JSON")
    return json.loads(t[s:e + 1])
