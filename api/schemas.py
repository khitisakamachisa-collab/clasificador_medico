from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

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


class CriticalityValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impacto_clinico: StrictInt = Field(..., ge=1, le=5)
    redundancia: StrictInt = Field(..., ge=1, le=5)
    frecuencia_uso: StrictInt = Field(..., ge=1, le=5)
    historial_fallas: StrictInt = Field(..., ge=1, le=5)
    costo_tiempo: StrictInt = Field(..., ge=1, le=5)


class AdjustCriticalityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipo_id: str = Field(..., min_length=1, max_length=200)
    valores: CriticalityValues
    usuario: str = Field(..., min_length=1, max_length=200)
    justificacion: str = Field(..., max_length=2000)

    @field_validator("equipo_id", "usuario")
    @classmethod
    def trim_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El campo es obligatorio.")
        return value


class MTBFRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipo_id: str = Field(..., min_length=1, max_length=200)
    mtbf_dias: float = Field(..., ge=0, allow_inf_nan=False)

    @field_validator("equipo_id")
    @classmethod
    def equipment_id_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("equipo_id es obligatorio.")
        return value

    @field_validator("mtbf_dias", mode="before")
    @classmethod
    def mtbf_not_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError("mtbf_dias debe ser un número, no un booleano.")
        return value


class MTBFRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipo_id: str | None = Field(default=None, max_length=200)
    mtbf_dias: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    equipos: list[MTBFRecord] | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("mtbf_dias", mode="before")
    @classmethod
    def mtbf_not_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError("mtbf_dias debe ser un número, no un booleano.")
        return value

    @model_validator(mode="after")
    def single_or_batch(self):
        if self.equipos is not None and (self.equipo_id is not None or self.mtbf_dias is not None):
            raise ValueError("Envía equipo_id/mtbf_dias o equipos, no ambos.")
        if self.equipos is None and (self.equipo_id is None or self.mtbf_dias is None):
            raise ValueError("Se requiere equipo_id y mtbf_dias o una lista equipos.")
        if self.equipo_id is not None:
            self.equipo_id = self.equipo_id.strip()
            if not self.equipo_id:
                raise ValueError("equipo_id es obligatorio.")
        return self
