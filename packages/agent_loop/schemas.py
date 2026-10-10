"""Strict action schema. The model sees a screenshot and answers one Action as JSON.
Coordinates are normalized 0-1000 and range-checked; the loop maps them to pixels."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

ACTIONS = ("click", "double_click", "type", "key", "scroll", "wait", "done")


class Chained(BaseModel):
    """A follow-up action run right after the main one, without a new screenshot."""
    model_config = {"extra": "forbid"}
    action: Literal["click", "type", "key"]
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = Field(default=None, max_length=500)
    replace: bool = False
    keys: Optional[str] = None

    @model_validator(mode="after")
    def _shape(self):
        if self.action == "click" and (self.x is None or self.y is None or not (0 <= self.x <= 1000 and 0 <= self.y <= 1000)):
            raise ValueError("click encadenado requiere x e y en 0-1000")
        if self.action == "type" and self.text is None:
            raise ValueError("type encadenado requiere text")
        if self.action == "key" and not self.keys:
            raise ValueError("key encadenado requiere keys")
        return self


MAX_CHAIN = 3


class Action(BaseModel):
    model_config = {"extra": "forbid"}

    thought: str = Field(max_length=2000)
    action: Literal["click", "double_click", "type", "key", "scroll", "wait", "done"]
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = Field(default=None, max_length=500)
    replace: bool = False          # type: select all first, then type
    keys: Optional[str] = None     # key: "enter", "ctrl+a", ...
    dy: Optional[int] = None       # scroll notches, + down / - up
    notas: Optional[str] = Field(default=None, max_length=1200)
    then: Optional[list[Chained]] = Field(default=None, max_length=MAX_CHAIN)
    # done
    estado: Optional[Literal["terminada", "fallida"]] = None
    respuesta: Optional[str] = Field(default=None, max_length=300)
    razon: Optional[str] = Field(default=None, max_length=600)
    claves: Optional[list[str]] = None
    evidencia: Optional[str] = Field(default=None, max_length=400)

    @field_validator("thought")
    @classmethod
    def _short(cls, v):
        return v[:300]

    @field_validator("x", "y")
    @classmethod
    def _range(cls, v):
        if v is not None and not 0 <= v <= 1000:
            raise ValueError("coordenada fuera de 0-1000")
        return v

    @model_validator(mode="after")
    def _shape(self):
        a = self.action
        if a in ("click", "double_click") and (self.x is None or self.y is None):
            raise ValueError(f"{a} requiere x e y")
        if a == "scroll" and (self.x is None or self.y is None or not self.dy):
            raise ValueError("scroll requiere x, y y dy")
        if a == "type" and self.text is None:
            raise ValueError("type requiere text")
        if a == "key" and not self.keys:
            raise ValueError("key requiere keys")
        if self.then and a not in ("click", "double_click", "type", "key"):
            raise ValueError("then solo se permite tras click, type o key")
        if a == "done" and self.estado is None:
            raise ValueError("done requiere estado")
        if a == "done" and self.estado == "fallida" and not (self.razon or self.claves):
            raise ValueError("fallida requiere razon o claves")
        return self

    def px(self, width: int, height: int) -> tuple[int, int]:
        return round(self.x * (width - 1) / 1000), round(self.y * (height - 1) / 1000)


class Requisito(BaseModel):
    model_config = {"extra": "forbid"}
    requisito: str = Field(max_length=300)
    cumplido: bool
    evidencia: str = Field(default="", max_length=300)


class Verification(BaseModel):
    model_config = {"extra": "forbid"}
    verificada: bool
    evidencia: str = Field(max_length=400)
    contradiccion: bool = False  # true only if the screen or the notes CONTRADICT the claim
    requisitos: list[Requisito] = Field(default_factory=list, max_length=12)

    @property
    def ok(self) -> bool:
        """Verified only when the overall flag and every listed requirement hold."""
        return self.verificada and all(r.cumplido for r in self.requisitos)

    def faltantes(self) -> list[str]:
        return [r.requisito for r in self.requisitos if not r.cumplido]


def action_schema_text() -> str:
    return (
        '{"thought": str, "action": "click|double_click|type|key|scroll|wait|done", '
        '"x": 0-1000, "y": 0-1000, "text": str, "replace": bool, "keys": str, "dy": int, '
        '"notas": str, '
        '"then": [{"action": "click|type|key", "x", "y", "text", "replace", "keys"}] (max 2), '
        '"estado": "terminada|fallida", "respuesta": str, "razon": str, "claves": [str], "evidencia": str}'
    )
