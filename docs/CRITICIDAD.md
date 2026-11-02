# Modelo de criticidad por equipo

## Alcance y criterios

La criticidad es un índice de apoyo a la priorización del mantenimiento. Cada equipo tiene un perfil persistido e identificable por `cmms_equipment_id` cuando está disponible; si no, se usa el código interno generado por el clasificador. La API no consulta ni depende de un CMMS.

| Criterio | Peso | 1 | 2 | 3 | 4 | 5 |
|---|---:|---|---|---|---|---|
| Impacto clínico | 0.40 | Sin impacto asistencial | Impacto menor | Afecta una actividad clínica | Riesgo clínico significativo | Soporte vital o riesgo directo |
| Redundancia | 0.20 | Muchos sustitutos | Varios sustitutos | Respaldo parcial | Pocas alternativas | Equipo único sin respaldo |
| Frecuencia de uso | 0.15 | Ocasional | Baja | Regular | Alta | Uso continuo |
| Historial de fallas | 0.15 | Muy confiable | Pocas fallas | Fallas ocasionales | Fallas frecuentes | Fallas muy frecuentes |
| Costo/tiempo | 0.10 | Reparación barata y rápida | Bajo | Moderado | Alto o prolongado | Muy costoso o de reparación prolongada |

Los pesos priorizan el impacto clínico; redundancia modera las consecuencias de la indisponibilidad. Frecuencia, historial de fallas y costo/tiempo incorporan carga operativa y experiencia de mantenimiento.

## Fórmula y niveles

`IC = Σ(valor del criterio × peso del criterio)`, con resultados entre 1.00 y 5.00, redondeados a dos decimales.

| Nivel | Umbral predeterminado |
|---|---:|
| ALTA | IC ≥ 4.00 |
| MEDIA | 2.50 ≤ IC < 4.00 |
| BAJA | IC < 2.50 |

Pesos y umbrales se centralizan en `src/config.py`; los pesos pueden parametrizarse mediante `CRITICALITY_WEIGHTS_JSON` y los umbrales mediante `CRITICALITY_LEVEL_HIGH` y `CRITICALITY_LEVEL_MEDIUM`. La API valida al iniciar que los pesos sumen 1.00 con tolerancia 0.001. El archivo externo `data/rules/criticidad_defaults.json` contiene los 25 perfiles de categoría, su índice esperado y la justificación. Verifica ese catálogo con `python scripts/validar_criticidad_defaults.py`.

| Categoría | Impacto | Redundancia | Uso | Fallas | Costo/tiempo | IC |
|---|---:|---:|---:|---:|---:|---:|
| ANE-01 | 5 | 4 | 5 | 3 | 4 | 4.40 |
| CAR-01 | 3 | 2 | 5 | 2 | 2 | 2.85 |
| CAR-02 | 5 | 5 | 5 | 2 | 5 | 4.55 |
| CIR-01 | 4 | 3 | 5 | 2 | 4 | 3.65 |
| CIR-02 | 5 | 4 | 5 | 2 | 3 | 4.15 |
| DEN-01 | 2 | 2 | 5 | 3 | 3 | 2.70 |
| DIA-01 | 5 | 4 | 5 | 3 | 4 | 4.40 |
| END-01 | 4 | 3 | 5 | 3 | 4 | 3.80 |
| EST-01 | 2 | 3 | 5 | 3 | 3 | 3.30 |
| FRM-01 | 3 | 3 | 5 | 2 | 2 | 3.05 |
| GAS-01 | 5 | 3 | 5 | 2 | 2 | 3.85 |
| IMG-01 | 4 | 3 | 5 | 3 | 4 | 3.80 |
| IMG-02 | 4 | 5 | 5 | 3 | 5 | 4.30 |
| IMG-03 | 3 | 2 | 5 | 3 | 3 | 3.10 |
| INF-01 | 5 | 3 | 5 | 3 | 3 | 4.10 |
| LAB-01 | 4 | 3 | 5 | 3 | 4 | 3.80 |
| LAB-02 | 5 | 4 | 5 | 2 | 3 | 4.15 |
| MOB-01 | 2 | 2 | 5 | 3 | 2 | 2.60 |
| MON-01 | 4 | 3 | 5 | 3 | 3 | 3.70 |
| NEO-01 | 5 | 4 | 5 | 3 | 4 | 4.40 |
| OFI-01 | 1 | 2 | 5 | 2 | 1 | 1.95 |
| OTR-01 | 2 | 2 | 4 | 3 | 2 | 2.45 |
| RES-01 | 5 | 4 | 5 | 3 | 4 | 4.40 |
| TER-01 | 2 | 2 | 5 | 2 | 2 | 2.45 |
| URG-01 | 5 | 4 | 4 | 2 | 4 | 4.10 |

## Creación y precedencia

Los perfiles nuevos se inicializan una sola vez. Los modificadores de ubicación se aplican antes de guardar el perfil inicial y se registran en la auditoría:

- UCI, UCIN, quirófano, urgencias o emergencia: frecuencia de uso +1, máximo 5.
- Almacén, oficina, depósito o baja: frecuencia de uso -2, mínimo 1; impacto clínico -1, mínimo 1.
- Nombre con “respaldo”, “backup”, “reserva” o “stock”: impacto clínico -1, mínimo 1.

`DEFAULT → MODIFICADOR_UBICACION → MANUAL → MTBF`

Los perfiles manuales y los datos MTBF no se recalculan por consulta. Un cambio posterior de MTBF respeta un ajuste manual reciente del criterio `historial_fallas` (menos de 90 días); el intento omitido también queda en la auditoría. Después de ese plazo, MTBF puede actualizar ese criterio.

## Ajustes manuales y MTBF

Un ajuste manual requiere autenticación `ADMIN_API_KEY`, valores enteros de 1 a 5 y una justificación de al menos 15 caracteres si algún criterio cambia. Las solicitudes sin cambios no crean una entrada de auditoría. Se guardan los valores y niveles anteriores y nuevos, el usuario, la fecha y el origen en `criticidad_ajustes`.

MTBF se recibe como dato externo (CMMS, CSV u otro sistema), sin integración ni acoplamiento con el CMMS:

| MTBF en días | Historial de fallas |
|---:|---:|
| > 365 | 1 |
| > 180 y ≤ 365 | 2 |
| > 90 y ≤ 180 | 3 |
| > 30 y ≤ 90 | 4 |
| ≤ 30 | 5 |

Ejecuta `python scripts/simular_mtbf.py` para validar el flujo con ejemplos de 15 y 400 días. El script usa una base temporal y no modifica la base de datos de la aplicación.

## Nota metodológica

El modelo es un índice multicriterio ponderado de construcción propia, alineado con los principios de priorización basada en riesgo de ISO 55001 y con los enfoques de mantenimiento basado en riesgo de AAMI. Ni ISO 55000/55001 ni AAMI prescriben esta fórmula ni estos pesos; son parametrizables por la institución y fueron definidos mediante juicio de expertos.
