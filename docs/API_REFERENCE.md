# Referencia de la API

Base local: `http://127.0.0.1:8000`. La documentación OpenAPI interactiva está en `/docs`.

Las entradas inválidas reciben `400` con detalle de validación. Se devuelve `429` al superar el límite configurado y `Retry-After` indica cuándo reintentar. Errores internos se mantienen como errores HTTP; no se presentan como una clasificación exitosa.

## `POST /api/v1/clasificar`

```json
{"nombre":"Ecógrafo portátil","marca":"Samsung","ubicacion":"Imagenología"}
```

`nombre` es obligatorio; marca, ubicación y `cmms_equipment_id` son opcionales. Responde con categoría, confianza, código EMDN terminal verificado o estado pendiente, clase MDR, criticidad, código interno y `semaforo`. Sus niveles son verde (≥ 0.90), amarillo (≥ 0.70) y rojo (< 0.70); amarillo y rojo requieren revisión.

## `POST /api/v1/recalcular`

Recibe los campos de `/clasificar` y `categoria_forzada`, que debe ser una de las 25 categorías disponibles. Fuerza esa categoría y vuelve a calcular EMDN, clase MDR y criticidad. El método se devuelve como `CORRECCION_MANUAL`. La confianza no es una probabilidad NLP: es un puntaje de coherencia basado en (1) que el EMDN sea terminal y tenga un prefijo asociado a la categoría, (2) que la clase MDR esté a no más de un nivel de la predeterminada y (3) que la criticidad esté dentro de ±1 de los valores de la categoría y su índice/nivel sean consistentes. Tres comprobaciones aprobadas producen `0.95`/`VALIDADA_AUTOMATICAMENTE`, dos producen `0.75`/`PENDIENTE_REVISION` y menos de dos producen `0.30`/`RECHAZADA`. Además, el término EMDN se contrasta semánticamente con el nombre del equipo; si no hay coherencia semántica, la corrección se rechaza con confianza `0.0`, aunque pase las comprobaciones estructurales. La respuesta incluye las tres comprobaciones estructurales y `semantica_valida` en `validacion_correccion.validaciones`.

La respuesta incluye `validacion_correccion` con las tres banderas y el mensaje. Estas comprobaciones son una validación estructural y no sustituyen la revisión clínica experta.

```json
{"nombre":"TENS para fisioterapia","marca":"Enraf Nonius","ubicacion":"Fisioterapia","categoria_forzada":"TER-01","cmms_equipment_id":"ACT-1042"}
```

## `POST /api/v1/registrar-correccion`

Guarda una corrección en estado `PENDIENTE` en la base SQLite local. Recibe `entrada_original`, `categoria_correcta`, `resultado_corregido` y opcionalmente `usuario`. La categoría del resultado debe coincidir con la categoría validada.

```json
{
  "entrada_original": {
    "nombre":"ENS para fisioterapia",
    "marca":"Enraf Nonius",
    "ubicacion":"Fisioterapia",
    "categoria_original":"ANE-01",
    "confidence_original":0.2,
    "cmms_equipment_id":"ACT-1042"
  },
  "categoria_correcta":"TER-01",
  "resultado_corregido":{"categoria_propia":"TER-01","confidence":0.95},
  "usuario":"biomedico"
}
```

Solo se guardan correcciones cuyo puntaje recalculado por el servidor sea al menos `0.75` (dos de tres comprobaciones y coherencia semántica). El servidor ignora la confianza enviada como evidencia y vuelve a calcular EMDN, MDR, criticidad y puntaje. Todas las correcciones quedan pendientes de revisión administrativa, incluso las validadas automáticamente; no se usan para entrenamiento hasta su aprobación explícita. El resultado `VALIDADA_AUTOMATICAMENTE` representa coherencia de datos, no aprobación clínica.

## Revisión administrativa

Configura `ADMIN_API_KEY` en `.env`. Cada ruta administrativa exige los encabezados `X-Admin-Key` y `X-Admin-User`; las claves vacías o incorrectas no autorizan el acceso.

- `GET /api/v1/correcciones/pendientes-revision`: lista las correcciones pendientes.
- `GET /api/v1/correcciones/revisadas`: lista las aprobadas y rechazadas.
- `POST /api/v1/correcciones/{id}/aprobar`: aprueba y agrega el ejemplo con `source: "USER_CORRECTION"` al conjunto elegible para entrenamiento.
- `POST /api/v1/correcciones/{id}/rechazar`: rechaza con `{"motivo_rechazo":"..."}`.
- `POST /api/v1/correcciones/{id}/solicitar-informacion`: agrega una nota con `{"nota":"..."}` y conserva el estado pendiente.
- `GET /api/v1/audit-log`: consulta la auditoría.

Las acciones de revisión solo se permiten para elementos `PENDIENTE`; las acciones repetidas responden `409`. Las revisiones registran administrador, fecha y motivo/nota.

Reentrenar calcula accuracy por validación cruzada estratificada, crea artefactos con el nombre solicitado y activa esa versión en el proceso en ejecución. La respuesta incluye `accuracy`, `nuevos_totales` y `modelo_activo`. Accuracy se informa como métrica medida; no se garantiza que mejore respecto a la versión previa.

Solicitud:

```json
{"validar_correcciones":true,"nueva_version":"v2"}
```

Con `curl`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/reentrenar \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: $ADMIN_API_KEY" \
  -H "X-Admin-User: administrador" \
  -d '{"validar_correcciones":true,"nueva_version":"v2"}'
```

Con PowerShell:

```powershell
$body = @{
    validar_correcciones = $true
    nueva_version = "v2"
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/reentrenar" `
    -Method Post `
    -ContentType "application/json" `
    -Headers @{ "X-Admin-Key" = $env:ADMIN_API_KEY; "X-Admin-User" = "administrador" } `
    -Body $body
```

La nueva versión debe ser un identificador `vN` cuyos artefactos aún no existan; el endpoint devuelve `409` si la versión ya está ocupada. La activación en memoria no sobrevive al reinicio: para mantenerla, configura `MODEL_VERSION=v2` en `.env` y reinicia FastAPI. `validar_correcciones` debe permanecer en `true`; el servidor no permite reentrenar con validación desactivada.

## `GET /api/v1/correcciones/{correction_id}`

Consulta el estado y los campos de auditoría de una corrección registrada. Devuelve `404` si el identificador no existe. El identificador se obtiene de la respuesta de `/registrar-correccion`.

## `POST /api/v1/batch-clasificar`

```json
{"equipos":[{"nombre":"Ecógrafo portátil"},{"nombre":"Ventilador mecánico","ubicacion":"UCI"}]}
```

Devuelve `{"total":2,"resultados":[...]}`. El tamaño máximo está limitado por `BATCH_MAX_SIZE` (100 por defecto).

## `POST /api/v1/validar-emdn`

```json
{"emdn_code":"Z11040103"}
```

Devuelve `exists`, `emdn_code`, `name`, `term`, `parent` y `level`. Un código inexistente devuelve `exists: false`. La ruta histórica `POST /api/v1/validar` permanece disponible como alias.

## `POST /api/v1/buscar-emdn`

```json
{"keyword":"portable ultrasound"}
```

Devuelve una lista de coincidencias terminales con `code`, `name` y `score`; una búsqueda sin resultados devuelve `[]`.

## `GET /api/v1/categorias`

Devuelve las 25 categorías propias, su nombre, clase MDR predeterminada y valores de criticidad.

## `GET /api/v1/metricas`

Devuelve el JSON de métricas de la versión configurada. Si el archivo aún no existe, responde `503` y explica que se ejecute el pipeline.

## `GET /api/v1/health`

Devuelve el estado, las versiones configuradas, la disponibilidad del Excel EMDN y la cantidad local de ejemplos validados.

## `POST /api/v1/reentrenar`

Requiere los encabezados administrativos. Acepta `validar_correcciones` (debe ser `true`) y `nueva_version` (`vN`, opcional). Los ejemplos de entrenamiento se obtienen exclusivamente de correcciones aprobadas; no se aceptan ejemplos enviados por el cliente. Se necesitan al menos 10 aprobaciones. El sistema calcula accuracy mediante validación cruzada y entrena/activa la nueva versión en el proceso en ejecución. Responde con `status`, `version`, `modelo_activo`, `nuevos_totales`, `correcciones_validadas` y `accuracy`. No se promete que la accuracy mejore; revisa la métrica y valida el modelo antes del uso clínico. Ver ejemplos curl y PowerShell arriba.

Si hay menos de 10 correcciones aprobadas, responde `400` e informa el umbral y el total aprobado.

## CORS y límites

CORS permite orígenes enumerados en `CORS_ORIGINS`, métodos GET/POST y encabezados Content-Type/Authorization/X-Admin-Key/X-Admin-User. El límite predeterminado es 120 solicitudes por IP por minuto; ambos valores son configurables. El limitador en memoria es por proceso, no un control distribuido.
