from __future__ import annotations

import json
import logging
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

from .config import Config
from .criticality import PESOS, calcular_criticidad, cargar_criticidad_defaults
from .utils import CATEGORÍAS

logger = logging.getLogger(__name__)

_FIELDS = tuple(PESOS)
_LABELS = {
    "impacto_clinico": "Impacto Clínico",
    "redundancia": "Redundancia",
    "frecuencia_uso": "Frecuencia de Uso",
    "historial_fallas": "Historial de Fallas",
    "costo_tiempo": "Costo/Tiempo",
}


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    Config.CORRECTIONS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(Config.CORRECTIONS_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def inicializar_criticidad() -> None:
    """Crea las tablas aditivas de criticidad en la base SQLite existente."""
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS criticidad_equipos (
                equipo_id TEXT PRIMARY KEY,
                categoria TEXT NOT NULL,
                impacto_clinico INTEGER NOT NULL,
                redundancia INTEGER NOT NULL,
                frecuencia_uso INTEGER NOT NULL,
                historial_fallas INTEGER NOT NULL,
                costo_tiempo INTEGER NOT NULL,
                indice REAL NOT NULL,
                nivel TEXT NOT NULL,
                origen_historial TEXT NOT NULL DEFAULT 'DEFAULT',
                mtbf_dias REAL,
                fecha_actualizacion TEXT NOT NULL,
                ajustado_manualmente INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS criticidad_ajustes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo_id TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                usuario TEXT NOT NULL,
                valores_anteriores TEXT NOT NULL,
                valores_nuevos TEXT NOT NULL,
                ic_anterior REAL,
                ic_nuevo REAL,
                nivel_anterior TEXT,
                nivel_nuevo TEXT,
                justificacion TEXT NOT NULL,
                origen TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_criticidad_ajustes_equipo_fecha
                ON criticidad_ajustes (equipo_id, timestamp);
            """
        )


def _values(row: sqlite3.Row | dict) -> dict[str, int]:
    return {field: int(row[field]) for field in _FIELDS}


def _record_adjustment(
    connection: sqlite3.Connection,
    *,
    equipment_id: str,
    user: str,
    previous: dict,
    current: dict,
    justification: str,
    origin: str,
) -> None:
    connection.execute(
        """
        INSERT INTO criticidad_ajustes (
            equipo_id, usuario, valores_anteriores, valores_nuevos,
            ic_anterior, ic_nuevo, nivel_anterior, nivel_nuevo,
            justificacion, origen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            equipment_id,
            user,
            json.dumps(previous.get("valores", {}), ensure_ascii=False),
            json.dumps(current.get("valores", {}), ensure_ascii=False),
            previous.get("indice"),
            current.get("indice"),
            previous.get("nivel"),
            current.get("nivel"),
            justification,
            origin,
        ),
    )


def _level(values: dict[str, int]) -> dict:
    return calcular_criticidad(*(values[field] for field in _FIELDS))


def _contextual_defaults(
    values: dict[str, int], name: str, location: str | None
) -> tuple[dict[str, int], list[str]]:
    adjusted = values.copy()
    modifiers = []
    normalized_location = (location or "").casefold()
    critical_locations = (
        "uci", "ucin", "quirófano", "quirofano", "urgencias", "emergencia",
    )
    nonclinical_locations = ("almacén", "almacen", "oficina", "depósito", "deposito", "baja")
    if any(term in normalized_location for term in critical_locations):
        adjusted["frecuencia_uso"] = min(5, adjusted["frecuencia_uso"] + 1)
        modifiers.append("ubicación crítica: frecuencia_uso +1")
    elif any(term in normalized_location for term in nonclinical_locations):
        adjusted["frecuencia_uso"] = max(1, adjusted["frecuencia_uso"] - 2)
        adjusted["impacto_clinico"] = max(1, adjusted["impacto_clinico"] - 1)
        modifiers.append("ubicación no asistencial: frecuencia_uso -2, impacto_clinico -1")
    if any(term in name.casefold() for term in ("respaldo", "backup", "reserva", "stock")):
        adjusted["impacto_clinico"] = max(1, adjusted["impacto_clinico"] - 1)
        modifiers.append("equipo de respaldo/reserva: impacto_clinico -1")
    return adjusted, modifiers


def asegurar_equipo(
    equipment_id: str,
    category: str,
    name: str = "",
    location: str | None = None,
    permitir_cambio_categoria: bool = False,
) -> dict:
    """Inicializa una sola vez el perfil del equipo y registra su procedencia."""
    if not equipment_id or category not in CATEGORÍAS:
        raise ValueError("Se requiere un identificador y una categoría válidos.")
    inicializar_criticidad()
    defaults = cargar_criticidad_defaults()
    with _connect() as connection:
        existing = connection.execute(
            "SELECT * FROM criticidad_equipos WHERE equipo_id = ?", (equipment_id,)
        ).fetchone()
        if existing:
            if existing["categoria"] != category:
                if not permitir_cambio_categoria:
                    raise ValueError(
                        f"El equipo {equipment_id} ya está asociado a {existing['categoria']}."
                    )
                current_values = _values(existing)
                previous = {
                    "valores": current_values,
                    "indice": existing["indice"],
                    "nivel": existing["nivel"],
                }
                connection.execute(
                    "UPDATE criticidad_equipos SET categoria=?, fecha_actualizacion=? "
                    "WHERE equipo_id=?",
                    (category, datetime.now(timezone.utc).isoformat(), equipment_id),
                )
                _record_adjustment(
                    connection,
                    equipment_id=equipment_id,
                    user="SISTEMA",
                    previous=previous,
                    current={**previous},
                    justification=(
                        f"Categoría actualizada por corrección manual: "
                        f"{existing['categoria']} → {category}."
                    ),
                    origin="CORRECCION_CATEGORIA",
                )
                connection.commit()
            return obtener_criticidad(equipment_id)

        base = {field: defaults[category][field] for field in _FIELDS}
        values, modifiers = _contextual_defaults(base, name, location)
        index = _level(values)
        updated = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO criticidad_equipos (
                equipo_id, categoria, impacto_clinico, redundancia, frecuencia_uso,
                historial_fallas, costo_tiempo, indice, nivel, fecha_actualizacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                equipment_id, category, *(values[field] for field in _FIELDS),
                index["indice"], index["nivel"], updated,
            ),
        )
        justification = defaults[category]["justificacion"]
        if modifiers:
            justification += " Modificadores aplicados: " + "; ".join(modifiers) + "."
            logger.info(
                "Modificadores de criticidad para %s (%s): %s",
                equipment_id,
                category,
                "; ".join(modifiers),
            )
        _record_adjustment(
            connection,
            equipment_id=equipment_id,
            user="SISTEMA",
            previous={},
            current={"valores": values, **index},
            justification=justification,
            origin="DEFAULT",
        )
    return obtener_criticidad(equipment_id)


def obtener_criticidad(equipment_id: str) -> dict | None:
    inicializar_criticidad()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM criticidad_equipos WHERE equipo_id = ?", (equipment_id,)
        ).fetchone()
    if not row:
        return None
    defaults = cargar_criticidad_defaults()[row["categoria"]]
    values = _values(row)
    radar_data = [
        {
            "criterio": _LABELS[field],
            "valor": values[field],
            "default": defaults[field],
            "peso": Config.CRITICALITY_WEIGHTS[field],
        }
        for field in _FIELDS
    ]
    contributions = [
        {
            "criterio": _LABELS[field],
            "aporte": round(values[field] * Config.CRITICALITY_WEIGHTS[field], 2),
            "porcentaje": round(
                values[field] * Config.CRITICALITY_WEIGHTS[field] / row["indice"] * 100,
                1,
            ),
        }
        for field in _FIELDS
    ]
    return {
        **values,
        "indice": row["indice"],
        "nivel": row["nivel"],
        "ajustado_manualmente": bool(row["ajustado_manualmente"]),
        "origen_historial": row["origen_historial"],
        "mtbf_dias": row["mtbf_dias"],
        "umbrales": {
            "ALTA": Config.CRITICALITY_LEVELS["ALTA"],
            "MEDIA": Config.CRITICALITY_LEVELS["MEDIA"],
        },
        "radar_data": radar_data,
        "contribuciones": contributions,
        "categoria": row["categoria"],
        "defaults": {field: defaults[field] for field in _FIELDS},
    }


def ajustar_criticidad(
    equipment_id: str, values: dict[str, int], user: str, justification: str
) -> tuple[dict, bool]:
    if set(values) != set(_FIELDS) or any(
        isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5
        for value in values.values()
    ):
        raise ValueError("Cada criterio debe ser un entero entre 1 y 5.")
    inicializar_criticidad()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM criticidad_equipos WHERE equipo_id = ?", (equipment_id,)
        ).fetchone()
        if not row:
            raise LookupError("No se encontró el equipo.")
        previous_values = _values(row)
        if previous_values == values:
            return obtener_criticidad(equipment_id), False
        if len(justification.strip()) < 15:
            raise ValueError(
                "Debe justificar el cambio de criticidad (mínimo 15 caracteres)."
            )
        previous = {
            "valores": previous_values, "indice": row["indice"], "nivel": row["nivel"]
        }
        result = _level(values)
        history_changed = previous_values["historial_fallas"] != values["historial_fallas"]
        connection.execute(
            """
            UPDATE criticidad_equipos
            SET impacto_clinico=?, redundancia=?, frecuencia_uso=?, historial_fallas=?,
                costo_tiempo=?, indice=?, nivel=?, ajustado_manualmente=1,
                origen_historial=CASE WHEN ? THEN 'MANUAL' ELSE origen_historial END,
                fecha_actualizacion=?
            WHERE equipo_id=?
            """,
            (
                *(values[field] for field in _FIELDS), result["indice"], result["nivel"],
                int(history_changed), datetime.now(timezone.utc).isoformat(), equipment_id,
            ),
        )
        _record_adjustment(
            connection,
            equipment_id=equipment_id,
            user=user,
            previous=previous,
            current={"valores": values, **result},
            justification=justification.strip(),
            origin="MANUAL",
        )
    return obtener_criticidad(equipment_id), True


def _history_manually_changed_recently(
    connection: sqlite3.Connection, equipment_id: str
) -> bool:
    threshold = datetime.now(timezone.utc) - timedelta(days=90)
    rows = connection.execute(
        """
        SELECT timestamp, valores_anteriores, valores_nuevos
        FROM criticidad_ajustes
        WHERE equipo_id=? AND origen='MANUAL'
        ORDER BY timestamp DESC
        """,
        (equipment_id,),
    ).fetchall()
    for row in rows:
        try:
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            previous = json.loads(row["valores_anteriores"])
            current = json.loads(row["valores_nuevos"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if previous.get("historial_fallas") != current.get("historial_fallas"):
            return timestamp >= threshold
    return False


def recalcular_por_mtbf(
    equipment_id: str, mtbf_days: float, user: str = "SISTEMA"
) -> dict:
    if (
        isinstance(mtbf_days, bool)
        or not isinstance(mtbf_days, (int, float))
        or not math.isfinite(mtbf_days)
        or mtbf_days < 0
    ):
        raise ValueError("mtbf_dias debe ser un número finito no negativo.")
    inicializar_criticidad()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM criticidad_equipos WHERE equipo_id=?", (equipment_id,)
        ).fetchone()
        if not row:
            raise LookupError(f"No se encontró el equipo {equipment_id}.")
        previous_values = _values(row)
        previous = {
            "valores": previous_values, "indice": row["indice"], "nivel": row["nivel"]
        }
        if _history_manually_changed_recently(connection, equipment_id):
            _record_adjustment(
                connection,
                equipment_id=equipment_id,
                user=user,
                previous=previous,
                current=previous,
                justification="MTBF_OMITIDO_POR_AJUSTE_MANUAL_RECIENTE",
                origin="MTBF_OMITIDO_POR_AJUSTE_MANUAL_RECIENTE",
            )
            logger.info(
                "MTBF omitido para %s: historial_fallas ajustado manualmente hace menos de 90 días.",
                equipment_id,
            )
            return {
                "equipo_id": equipment_id,
                "actualizado": False,
                "omitido": True,
                "motivo": "MTBF_OMITIDO_POR_AJUSTE_MANUAL_RECIENTE",
                "criticidad": obtener_criticidad(equipment_id),
            }

        failure_rating = (
            1 if mtbf_days > 365 else
            2 if mtbf_days > 180 else
            3 if mtbf_days > 90 else
            4 if mtbf_days > 30 else 5
        )
        values = {**previous_values, "historial_fallas": failure_rating}
        result = _level(values)
        connection.execute(
            """
            UPDATE criticidad_equipos
            SET impacto_clinico=?, redundancia=?, frecuencia_uso=?, historial_fallas=?,
                costo_tiempo=?, indice=?, nivel=?, origen_historial='MTBF_REAL',
                mtbf_dias=?, fecha_actualizacion=?
            WHERE equipo_id=?
            """,
            (
                *(values[field] for field in _FIELDS), result["indice"], result["nivel"],
                float(mtbf_days), datetime.now(timezone.utc).isoformat(), equipment_id,
            ),
        )
        _record_adjustment(
            connection,
            equipment_id=equipment_id,
            user=user,
            previous=previous,
            current={"valores": values, **result},
            justification=f"Actualización externa por MTBF: {mtbf_days:g} días.",
            origin="MTBF",
        )
    return {
        "equipo_id": equipment_id,
        "actualizado": True,
        "omitido": False,
        "criticidad": obtener_criticidad(equipment_id),
    }


def listar_ajustes(
    equipment_id: str | None = None,
    user: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    inicializar_criticidad()
    clauses, parameters = [], []
    for column, value in (
        ("equipo_id", equipment_id), ("usuario", user),
    ):
        if value:
            clauses.append(f"{column}=?")
            parameters.append(value)
    if date_from:
        clauses.append("date(timestamp)>=date(?)")
        parameters.append(date_from)
    if date_to:
        clauses.append("date(timestamp)<=date(?)")
        parameters.append(date_to)
    query = "SELECT * FROM criticidad_ajustes"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY timestamp DESC, id DESC"
    with _connect() as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [
        {
            **dict(row),
            "valores_anteriores": json.loads(row["valores_anteriores"]),
            "valores_nuevos": json.loads(row["valores_nuevos"]),
        }
        for row in rows
    ]


def reporte_distribucion() -> dict:
    inicializar_criticidad()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT equipo_id, categoria, indice, nivel, origen_historial, mtbf_dias "
            "FROM criticidad_equipos ORDER BY indice DESC"
        ).fetchall()
    levels = {name: 0 for name in ("ALTA", "MEDIA", "BAJA")}
    categories = {}
    for row in rows:
        levels[row["nivel"]] += 1
        item = categories.setdefault(
            row["categoria"],
            {"categoria": row["categoria"], "total": 0, "indices": [], "ALTA": 0,
             "MEDIA": 0, "BAJA": 0},
        )
        item["total"] += 1
        item["indices"].append(row["indice"])
        item[row["nivel"]] += 1
    by_category = [
        {
            "categoria": category,
            "total": data["total"],
            "ic_promedio": round(sum(data["indices"]) / data["total"], 2),
            "alta": data["ALTA"],
            "media": data["MEDIA"],
            "baja": data["BAJA"],
        }
        for category, data in sorted(categories.items())
    ]
    return {
        "total": len(rows),
        "por_nivel": levels,
        "por_categoria": by_category,
        "top_criticos": [
            {
                "equipo": row["equipo_id"],
                "equipo_id": row["equipo_id"],
                "categoria": row["categoria"],
                "indice": row["indice"],
                "nivel": row["nivel"],
                "mtbf_dias": row["mtbf_dias"],
                "origen": row["origen_historial"],
            }
            for row in rows[:10]
        ],
    }
