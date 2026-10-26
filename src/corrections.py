from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .config import Config


class Base(DeclarativeBase):
    pass


class CorrectionLog(Base):
    __tablename__ = "correction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    nombre_equipo: Mapped[str] = mapped_column(String(500), nullable=False)
    marca: Mapped[str | None] = mapped_column(String(200))
    ubicacion: Mapped[str | None] = mapped_column(String(200))
    categoria_original: Mapped[str | None] = mapped_column(String(16))
    emdn_original: Mapped[str | None] = mapped_column(String(32))
    mdr_original: Mapped[str | None] = mapped_column(String(16))
    metodo_original: Mapped[str | None] = mapped_column(String(32))
    categoria_corregida: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_original: Mapped[float | None] = mapped_column(Float)
    confidence_corregida: Mapped[float] = mapped_column(Float, nullable=False)
    usuario: Mapped[str | None] = mapped_column(String(200))
    cmms_equipment_id: Mapped[str | None] = mapped_column(String(200))
    resultado_corregido: Mapped[str] = mapped_column(Text, nullable=False)
    estado_revision: Mapped[str] = mapped_column(
        String(32), default="PENDIENTE", nullable=False
    )
    revisada_por: Mapped[str | None] = mapped_column(String(200))
    fecha_revision: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_rechazo: Mapped[str | None] = mapped_column(Text)
    notas: Mapped[str | None] = mapped_column(Text)


class TrainingExample(Base):
    __tablename__ = "training_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(500), nullable=False)
    marca: Mapped[str | None] = mapped_column(String(200))
    ubicacion: Mapped[str | None] = mapped_column(String(200))
    categoria: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    cmms_equipment_id: Mapped[str | None] = mapped_column(String(200))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    usuario: Mapped[str] = mapped_column(String(200), nullable=False)
    accion: Mapped[str] = mapped_column(String(32), nullable=False)
    entidad: Mapped[str] = mapped_column(String(64), nullable=False)
    entidad_id: Mapped[str | None] = mapped_column(String(64))
    datos_anteriores: Mapped[str | None] = mapped_column(Text)
    datos_nuevos: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))


@lru_cache(maxsize=4)
def _engine_for(path: str):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    return engine


def _engine():
    Config.CORRECTIONS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = _engine_for(str(Config.CORRECTIONS_DB_PATH.resolve()))
    Base.metadata.create_all(engine)
    columns = {item["name"] for item in inspect(engine).get_columns("correction_logs")}
    if "estado_revision" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE correction_logs ADD COLUMN "
                    "estado_revision VARCHAR(32) NOT NULL DEFAULT 'PENDIENTE'"
                )
            )
    for column, declaration in (
        ("emdn_original", "VARCHAR(32)"),
        ("mdr_original", "VARCHAR(16)"),
        ("metodo_original", "VARCHAR(32)"),
        ("revisada_por", "VARCHAR(200)"),
        ("fecha_revision", "DATETIME"),
        ("motivo_rechazo", "TEXT"),
        ("notas", "TEXT"),
    ):
        if column not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(f"ALTER TABLE correction_logs ADD COLUMN {column} {declaration}")
                )
    return engine


def save_correction(
    entrada_original: dict,
    categoria_correcta: str,
    resultado_corregido: dict,
    usuario: str | None = None,
) -> int:
    """Guarda una corrección pendiente; no crea entrenamiento antes de aprobarla."""
    engine = _engine()
    corrected_confidence = float(resultado_corregido["confidence"])
    with Session(engine) as session, session.begin():
        log = CorrectionLog(
            nombre_equipo=entrada_original["nombre"],
            marca=entrada_original.get("marca"),
            ubicacion=entrada_original.get("ubicacion"),
            categoria_original=entrada_original.get("categoria_original"),
            emdn_original=entrada_original.get("emdn_original"),
            mdr_original=entrada_original.get("mdr_original"),
            metodo_original=entrada_original.get("metodo_original"),
            categoria_corregida=categoria_correcta,
            confidence_original=entrada_original.get("confidence_original"),
            confidence_corregida=corrected_confidence,
            usuario=usuario,
            cmms_equipment_id=entrada_original.get("cmms_equipment_id"),
            resultado_corregido=json.dumps(resultado_corregido, ensure_ascii=False),
            estado_revision="PENDIENTE",
        )
        session.add(log)
        session.flush()
        return log.id


def load_training_examples() -> list[dict[str, str | None]]:
    """Carga exclusivamente ejemplos aprobados explícitamente por un administrador."""
    engine = _engine()
    with Session(engine) as session:
        corrections = session.scalars(
            select(CorrectionLog)
            .where(CorrectionLog.estado_revision == "APROBADA")
            .order_by(CorrectionLog.id)
        ).all()
        return [
            {
                "nombre": item.nombre_equipo,
                "marca": item.marca,
                "ubicacion": item.ubicacion,
                "categoria": item.categoria_corregida,
                "source": "USER_CORRECTION",
            }
            for item in corrections
        ]


def validate_saved_corrections() -> int:
    """Cuenta las correcciones aprobadas y aptas para reentrenar."""
    engine = _engine()
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(CorrectionLog)
            .where(CorrectionLog.estado_revision == "APROBADA")
        ) or 0


def get_correction(correction_id: int) -> dict | None:
    """Lee el registro de auditoría para permitir que el CMMS consulte el resultado."""
    engine = _engine()
    with Session(engine) as session:
        item = session.get(CorrectionLog, correction_id)
        if item is None:
            return None
        return {
            "correction_id": item.id,
            "timestamp": item.timestamp.isoformat(),
            "nombre_equipo": item.nombre_equipo,
            "marca": item.marca,
            "ubicacion": item.ubicacion,
            "cmms_equipment_id": item.cmms_equipment_id,
            "categoria_original": item.categoria_original,
            "emdn_original": item.emdn_original,
            "mdr_original": item.mdr_original,
            "metodo_original": item.metodo_original,
            "categoria_corregida": item.categoria_corregida,
            "confidence_original": item.confidence_original,
            "confidence_corregida": item.confidence_corregida,
            "estado_revision": item.estado_revision,
            "revisada_por": item.revisada_por,
            "fecha_revision": item.fecha_revision.isoformat() if item.fecha_revision else None,
            "motivo_rechazo": item.motivo_rechazo,
            "notas": item.notas,
            "usuario": item.usuario,
            "source": "USER_CORRECTION",
            "resultado_corregido": json.loads(item.resultado_corregido),
        }


def _correction_data(item: CorrectionLog) -> dict:
    result = json.loads(item.resultado_corregido)
    return {
        "id": item.id,
        "timestamp": item.timestamp.isoformat(),
        "nombre_equipo": item.nombre_equipo,
        "marca": item.marca,
        "ubicacion": item.ubicacion,
        "cmms_equipment_id": item.cmms_equipment_id,
        "categoria_original": item.categoria_original,
        "categoria_corregida": item.categoria_corregida,
        "emdn_original": item.emdn_original,
        "emdn_corregido": result.get("emdn_code"),
        "emdn_term": result.get("emdn_term"),
        "confidence_original": item.confidence_original,
        "confidence_corregida": item.confidence_corregida,
        "metodo_original": item.metodo_original,
        "metodo_correccion": result.get("metodo"),
        "estado": item.estado_revision,
        "corregida_por": item.usuario or "No especificado",
        "validada_por": item.revisada_por,
        "fecha_validacion": item.fecha_revision.isoformat() if item.fecha_revision else None,
        "motivo_rechazo": item.motivo_rechazo,
        "notas": item.notas,
        "resultado_corregido": result,
        "validacion_semantica": result.get("validacion_correccion", {})
        .get("validaciones", {})
        .get("semantica_valida", False),
    }


def list_corrections(estado: str | None = None) -> list[dict]:
    """Lista correcciones en orden reciente para el panel administrativo."""
    engine = _engine()
    with Session(engine) as session:
        query = select(CorrectionLog).order_by(CorrectionLog.timestamp.desc())
        if estado:
            query = query.where(CorrectionLog.estado_revision == estado)
        return [_correction_data(item) for item in session.scalars(query).all()]


def review_correction(
    correction_id: int,
    *,
    action: str,
    user: str,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict | None:
    """Aprueba o rechaza una corrección pendiente de forma transaccional y auditable."""
    if action not in {"APROBAR", "RECHAZAR", "SOLICITAR_INFORMACION"}:
        raise ValueError("Acción de revisión desconocida.")
    if action == "RECHAZAR" and not (reason or "").strip():
        raise ValueError("El motivo de rechazo es obligatorio.")

    engine = _engine()
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        item = session.get(CorrectionLog, correction_id)
        if item is None:
            return None
        if item.estado_revision != "PENDIENTE":
            raise ValueError("La corrección ya fue revisada.")
        previous = {"estado": item.estado_revision}
        if action == "SOLICITAR_INFORMACION":
            item.notas = reason.strip()
        else:
            item.estado_revision = "APROBADA" if action == "APROBAR" else "RECHAZADA"
            item.revisada_por = user
            item.fecha_revision = now
            item.motivo_rechazo = reason.strip() if action == "RECHAZAR" else None
        if action == "APROBAR":
            session.add(
                TrainingExample(
                    nombre=item.nombre_equipo,
                    marca=item.marca,
                    ubicacion=item.ubicacion,
                    categoria=item.categoria_corregida,
                    source="USER_CORRECTION",
                    cmms_equipment_id=item.cmms_equipment_id,
                )
            )
        session.add(
            AuditLog(
                usuario=user,
                accion=action,
                entidad="CORRECCION",
                entidad_id=str(item.id),
                datos_anteriores=json.dumps(previous, ensure_ascii=False),
                datos_nuevos=json.dumps(
                    {
                        "estado": item.estado_revision,
                        "notas": item.notas,
                        "motivo_rechazo": item.motivo_rechazo,
                    },
                    ensure_ascii=False,
                ),
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        session.flush()
        return _correction_data(item)


def record_audit(
    *,
    user: str,
    action: str,
    entity: str,
    entity_id: str | None = None,
    old_data: dict | None = None,
    new_data: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Registra una acción administrativa para mantener trazabilidad."""
    engine = _engine()
    with Session(engine) as session, session.begin():
        session.add(
            AuditLog(
                usuario=user,
                accion=action,
                entidad=entity,
                entidad_id=entity_id,
                datos_anteriores=json.dumps(old_data, ensure_ascii=False) if old_data else None,
                datos_nuevos=json.dumps(new_data, ensure_ascii=False) if new_data else None,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )


def list_audit_logs() -> list[dict]:
    """Devuelve el registro de auditoría más reciente para personal autorizado."""
    engine = _engine()
    with Session(engine) as session:
        logs = session.scalars(select(AuditLog).order_by(AuditLog.timestamp.desc())).all()
        return [
            {
                "id": item.id,
                "timestamp": item.timestamp.isoformat(),
                "usuario": item.usuario,
                "accion": item.accion,
                "entidad": item.entidad,
                "entidad_id": item.entidad_id,
                "datos_anteriores": json.loads(item.datos_anteriores) if item.datos_anteriores else None,
                "datos_nuevos": json.loads(item.datos_nuevos) if item.datos_nuevos else None,
                "ip_address": item.ip_address,
                "user_agent": item.user_agent,
            }
            for item in logs
        ]
