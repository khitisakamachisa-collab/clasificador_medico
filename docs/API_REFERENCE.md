# Referencia de la API

Base local: `http://127.0.0.1:8000`. La documentación OpenAPI interactiva está en `/docs`.

Las entradas inválidas reciben `400` con detalle de validación. Se devuelve `429` al superar el límite configurado y `Retry-After` indica cuándo reintentar. Errores internos se mantienen como errores HTTP; no se presentan como una clasificación exitosa.

## `POST /api/v1/clasificar`

```json
{"nombre":"Ecógrafo portátil","marca":"Samsung","ubicacion":"Imagenología"}
```

`nombre` es obligatorio; marca y ubicación son opcionales. Responde con categoría, confianza, código EMDN terminal verificado o estado pendiente, clase MDR, criticidad y código interno. Confianza inferior a 0.50 o un error NLP incluye `advertencia`.

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

Acepta `{"nuevos_ejemplos":[...]}` y crea una nueva versión local del modelo. El proceso no cambia automáticamente el modelo activo. Responde con el estado, número de versión y total de ejemplos; no informa métricas no calculadas.

## CORS y límites

CORS permite orígenes enumerados en `CORS_ORIGINS`, métodos GET/POST y encabezados Content-Type/Authorization. El límite predeterminado es 120 solicitudes por IP por minuto; ambos valores son configurables. El limitador en memoria es por proceso, no un control distribuido.
