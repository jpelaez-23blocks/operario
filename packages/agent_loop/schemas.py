"""Strict action schema. The model sees a screenshot and answers one Action as JSON.
Coordinates are normalized 0-1000 and range-checked; the loop maps them to pixels."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

ACTIONS = ("click", "double_click", "type", "key", "scroll", "wait", "done")


class Action(BaseModel):
    model_config = {"extra": "forbid"}

    thought: str = Field(max_length=600)
    action: Literal["click", "double_click", "type", "key", "scroll", "wait", "done"]
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = Field(default=None, max_length=500)
    replace: bool = False          # type: select all first, then type
    keys: Optional[str] = None     # key: "enter", "ctrl+a", ...
    dy: Optional[int] = None       # scroll notches, + down / - up
    # done
    estado: Optional[Literal["terminada", "fallida"]] = None
    respuesta: Optional[str] = Field(default=None, max_length=300)
    razon: Optional[str] = Field(default=None, max_length=600)
    claves: Optional[list[str]] = None
    evidencia: Optional[str] = Field(default=None, max_length=400)

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
        if a == "done" and self.estado is None:
            raise ValueError("done requiere estado")
        if a == "done" and self.estado == "fallida" and not (self.razon or self.claves):
            raise ValueError("fallida requiere razon o claves")
        return self

    def px(self, width: int, height: int) -> tuple[int, int]:
        return round(self.x * (width - 1) / 1000), round(self.y * (height - 1) / 1000)


class Verification(BaseModel):
    model_config = {"extra": "forbid"}
    verificada: bool
    evidencia: str = Field(max_length=400)


def action_schema_text() -> str:
    return (
        '{"thought": str, "action": "click|double_click|type|key|scroll|wait|done", '
        '"x": 0-1000, "y": 0-1000, "text": str, "replace": bool, "keys": str, "dy": int, '
        '"estado": "terminada|fallida", "respuesta": str, "razon": str, "claves": [str], "evidencia": str}'
    )
