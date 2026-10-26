from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import Config


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(..., min_length=1, max_length=500)
    marca: str | None = Field(default=None, max_length=200)
    ubicacion: str | None = Field(default=None, max_length=200)
    cmms_equipment_id: str | None = Field(default=None, max_length=200)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre del equipo no puede estar vacío.")
        return value


class RecalculateRequest(ClassificationRequest):
    categoria_forzada: str = Field(..., min_length=1, max_length=16)
    usuario: str | None = Field(default=None, max_length=200)

    @field_validator("categoria_forzada")
    @classmethod
    def categoria_valida(cls, value: str) -> str:
        from src.utils import CATEGORÍAS

        value = value.strip()
        if value not in CATEGORÍAS:
            raise ValueError("La categoría forzada no existe.")
        return value


class CorrectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(..., min_length=1, max_length=500)
    marca: str | None = Field(default=None, max_length=200)
    ubicacion: str | None = Field(default=None, max_length=200)
    categoria_original: str | None = Field(default=None, max_length=16)
    emdn_original: str | None = Field(default=None, max_length=32)
    mdr_original: str | None = Field(default=None, max_length=16)
    metodo_original: str | None = Field(default=None, max_length=32)
    confidence_original: float | None = Field(default=None, ge=0, le=1)
    cmms_equipment_id: str | None = Field(default=None, max_length=200)

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre del equipo no puede estar vacío.")
        return value


class RegisterCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrada_original: CorrectionInput
    categoria_correcta: str = Field(..., min_length=1, max_length=16)
    resultado_corregido: dict[str, Any]
    usuario: str | None = Field(default=None, max_length=200)

    @field_validator("categoria_correcta")
    @classmethod
    def categoria_valida(cls, value: str) -> str:
        from src.utils import CATEGORÍAS

        value = value.strip()
        if value not in CATEGORÍAS:
            raise ValueError("La categoría correcta no existe.")
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

    validar_correcciones: bool = True
    nueva_version: str | None = Field(default=None, pattern=r"^v[1-9][0-9]*$")


class RejectCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo_rechazo: str = Field(..., min_length=1, max_length=2000)

    @field_validator("motivo_rechazo")
    @classmethod
    def motivo_no_vacio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El motivo de rechazo es obligatorio.")
        return value


class RequestInformationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nota: str = Field(..., min_length=1, max_length=2000)

    @field_validator("nota")
    @classmethod
    def nota_no_vacia(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La nota es obligatoria.")
        return value
