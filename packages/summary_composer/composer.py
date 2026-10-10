"""Builds the `resumen` from structured outcome data. Templates plus a secret scrubber.
The scrubber removes every secret this process knows (desktop password, tokens, API keys)."""
from __future__ import annotations

import re
from typing import Iterable, Optional

REDACTED = "[oculto]"


class Scrubber:
    def __init__(self, secrets: Iterable[str]):
        self.secrets = sorted({s for s in secrets if s and len(s) >= 3}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, REDACTED)
            text = re.sub(re.escape(s), REDACTED, text, flags=re.I)
        text = re.sub(r"\b(sk|or|gl|jev)[-_][A-Za-z0-9_\-]{16,}\b", REDACTED, text)
        text = re.sub(r"(?i)(contrase[ñn]a|password|clave de acceso|clave|api[ _-]?key|token|secret[oa]?|credencial(?:es)?)\s*(?:de\s+\w+\s*)?[:=]\s*\S+", r"\1: " + REDACTED, text)
        return text


def compose(estado: str, *, scrub: Scrubber, hizo: str = "", respuesta: Optional[str] = None,
            razon: str = "", claves: Optional[list[str]] = None, evidencia: str = "") -> str:
    lines: list[str] = []
    if respuesta and respuesta.strip() and estado == "terminada":
        lines.append(f"respuesta: {respuesta.strip()}")
    if estado == "terminada":
        if hizo:
            lines.append(hizo.strip())
        if evidencia:
            lines.append(f"Verificado en pantalla: {evidencia.strip()}")
    else:
        lines.append("No se completó la tarea." + (f" {razon.strip()}" if razon else ""))
        if claves:
            lines.append("Datos clave: " + ", ".join(c.strip() for c in claves if c))
    return scrub("\n".join(lines))[:1500]
