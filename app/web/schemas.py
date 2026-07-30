"""Pydantic schemas for API (扩展位，目前主要在 sources.models)."""
from pydantic import BaseModel


class GenericResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    data: dict | list | None = None
