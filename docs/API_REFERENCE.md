# Referencia de la API

Base local: `http://127.0.0.1:8000`. La documentación OpenAPI interactiva está en `/docs`.

Las entradas inválidas reciben `400` con detalle de validación. Se devuelve `429` al superar el límite configurado y `Retry-After` indica cuándo reintentar. Errores internos se mantienen como errores HTTP; no se presentan como una clasificación exitosa.

## `POST /api/v1/clasificar`

```json
{"nombre":"Ecógrafo portátil","marca":"Samsung","ubicacion":"Imagenología"}
```

`nombre` es obligatorio; marca, ubicación y `cmms_equipment_id` son opcionales. Responde con categoría, confianza, código EMDN terminal verificado o estado pendiente, clase MDR, criticidad, código interno y `semaforo`. Sus niveles son verde (≥ 0.90), amarillo (≥ 0.70) y rojo (< 0.70); amarillo y rojo requieren revisión.

Las reglas maestras configuradas en `data/rules/reglas_maestras.json` se aplican antes del modelo NLP. Un código definido por una regla se devuelve directamente solo si el catálogo EMDN local lo reconoce como terminal; los códigos no terminales nunca se devuelven como verificados.

## `POST /api/v1/recalcular`

Recibe los campos de `/clasificar` y `categoria_forzada`, que debe ser una de las 25 categorías disponibles. Fuerza esa categoría y vuelve a calcular EMDN, clase MDR y criticidad. La decisión humana se devuelve con `metodo: "CORRECCION_MANUAL"`, `confidence: 0.95` y semáforo verde (`nivel: "ALTA"`, mensaje `Validado manualmente`), con independencia del puntaje de las comprobaciones técnicas. Estas comprobaciones siguen disponibles en `validacion_correccion` para aportar contexto y no sustituyen la revisión clínica experta.

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

El servidor vuelve a calcular EMDN, MDR, criticidad y comprobaciones técnicas. Una decisión manual con `metodo: "CORRECCION_MANUAL"` y confianza `0.95` se conserva como decisión humana aunque las comprobaciones técnicas no coincidan; las demás solicitudes deben alcanzar el umbral automático de `0.75`. Todas las correcciones quedan pendientes de revisión administrativa y no se usan para entrenamiento hasta su aprobación explícita.

## Revisión administrativa

Configura `ADMIN_API_KEY` en `.env`. Las rutas administrativas validan `X-Admin-Key`; normalmente también exigen `X-Admin-User` para la auditoría. La ruta MTBF admite opcionalmente la identidad en su JSON y, si no se proporciona en el cuerpo ni en `X-Admin-User`, registra `SISTEMA`. Las claves vacías o incorrectas no autorizan el acceso. La interfaz solicita la clave en un único modal reutilizado por las acciones administrativas.

- `POST /api/v1/admin/auth`: valida la clave y la identidad de auditoría con el mismo control que las operaciones protegidas. No almacena credenciales en `localStorage`.

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

## `GET /api/v1/buscar`

Busca términos del catálogo EMDN por texto difuso, prefijo de código o categoría propia. El índice se carga en memoria al iniciar la API. `q` acepta entre 1 y 100 caracteres; `limit` es opcional, vale 10 por defecto y admite valores entre 1 y 50.

```text
GET /api/v1/buscar?q=ventilador&limit=10
```

La respuesta es una lista con `codigo_emdn`, `termino_emdn`, `categoria_propia`, `clase_mdr`, `nivel_terminal` y `similitud`. Las búsquedas de código devuelven códigos que empiezan por el prefijo indicado; una consulta sin coincidencias devuelve `[]`.

```json
[
  {
    "codigo_emdn": "Z1203010502",
    "termino_emdn": "ADULT PULMONARY VENTILATORS",
    "categoria_propia": "RES-01",
    "clase_mdr": "IIb",
    "nivel_terminal": true,
    "similitud": 0.8571
  }
]
```

## `GET /api/v1/categorias`

Devuelve las 25 categorías propias, su nombre, clase MDR predeterminada y valores de criticidad.

## Criticidad por equipo

Los equipos se identifican con `cmms_equipment_id` cuando se envía al clasificador; si no, la respuesta devuelve `equipo_id` con el código interno generado. La criticidad conserva sus campos previos y añade origen, estado de ajuste, perfil de referencia, contribuciones al índice y datos para el radar. Los perfiles se guardan en la base SQLite local; no se requiere conexión con un CMMS.

- `GET /api/v1/criticidad/{equipo_id}`: valores efectivos, referencia de categoría e historial.
- `GET /api/v1/criticidad/{equipo_id}/auditoria`: auditoría del equipo; requiere `X-Admin-Key` y `X-Admin-User`.
- `POST /api/v1/criticidad/ajustar`: ajuste administrativo. Si cambió algún criterio, exige justificación de al menos 15 caracteres.

```json
{
  "equipo_id": "ACT-1042",
  "valores": {
    "impacto_clinico": 5,
    "redundancia": 3,
    "frecuencia_uso": 5,
    "historial_fallas": 3,
    "costo_tiempo": 3
  },
  "usuario": "biomedico",
  "justificacion": "La evaluación clínica confirma exposición asistencial alta."
}
```

## MTBF y reportes de criticidad

- `POST /api/v1/criticidad/mtbf`: actualización administrativa externa, individual (`equipo_id`, `mtbf_dias`) o por lote (`equipos`). `administrador` es opcional; si se omite, se usa `X-Admin-User` cuando está presente y, en caso contrario, `SISTEMA`. Responde con totales actualizados/omitidos y detalle. Un ajuste manual reciente de `historial_fallas` prevalece durante 90 días.
- `GET /api/v1/criticidad/reportes/distribucion`: total evaluado, distribución por nivel y categoría y top 10.
- `GET /api/v1/criticidad/reportes/auditoria`: ajustes administrativos, con filtros opcionales `usuario`, `fecha_inicio`, `fecha_fin` y `equipo_id`; requiere encabezados administrativos.

Todos los endpoints conservan errores HTTP explícitos para entradas inválidas o equipos no registrados.

## `GET /api/v1/metricas`

Devuelve el JSON de métricas de la versión configurada. Si el archivo aún no existe, responde `503` y explica que se ejecute el pipeline.

## `GET /api/v1/health`

Devuelve el estado, las versiones configuradas, la disponibilidad del Excel EMDN y la cantidad local de ejemplos validados.

## `POST /api/v1/reentrenar`

Requiere los encabezados administrativos. Acepta `validar_correcciones` (debe ser `true`) y `nueva_version` (`vN`, opcional). Los ejemplos de entrenamiento se obtienen exclusivamente de correcciones aprobadas; no se aceptan ejemplos enviados por el cliente. Se necesitan al menos 10 aprobaciones. El sistema calcula accuracy mediante validación cruzada y entrena/activa la nueva versión en el proceso en ejecución. Responde con `status`, `version`, `modelo_activo`, `nuevos_totales`, `correcciones_validadas` y `accuracy`. No se promete que la accuracy mejore; revisa la métrica y valida el modelo antes del uso clínico. Ver ejemplos curl y PowerShell arriba.

Si hay menos de 10 correcciones aprobadas, responde `400` e informa el umbral y el total aprobado.

## CORS y límites

CORS permite orígenes enumerados en `CORS_ORIGINS`, métodos GET/POST y encabezados Content-Type/Authorization/X-Admin-Key/X-Admin-User. El límite predeterminado es 120 solicitudes por IP por minuto; ambos valores son configurables. El limitador en memoria es por proceso, no un control distribuido.
