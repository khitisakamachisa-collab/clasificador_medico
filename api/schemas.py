from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import Config


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(..., min_length=1, max_length=500)
    marca: str | None = Field(default=None, max_length=200)
    ubicacion: str | None = Field(default=None, max_length=200)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre del equipo no puede estar vacío.")
        return value


class EMDNValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emdn_code: str = Field(..., min_length=1, max_length=32)

    @field_validator("emdn_code")
    @classmethod
    def codigo_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El código EMDN no puede estar vacío.")
        return value


class SearchEMDNRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(..., min_length=1, max_length=200)

    @field_validator("keyword")
    @classmethod
    def keyword_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La búsqueda no puede estar vacía.")
        return value


class BatchClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipos: list[ClassificationRequest] = Field(
        ..., min_length=1, max_length=Config.BATCH_MAX_SIZE
    )


class RetrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nuevos_ejemplos: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
