# Integración con un CMMS

La API local base es `http://localhost:8000`. Inicia el servidor FastAPI y habilita el origen del CMMS en `CORS_ORIGINS` si la interfaz web se abre desde otro dominio. El ejemplo de desarrollo predeterminado permite `http://localhost:3000`.

## Clasificar un activo

El CMMS puede enviar el nombre, la marca, la ubicación y su identificador estable:

```http
POST /api/v1/clasificar
Content-Type: application/json
```

```json
{
  "nombre": "Ecógrafo portátil",
  "marca": "Samsung",
  "ubicacion": "Imagenología",
  "cmms_equipment_id": "ACT-1042"
}
```

La respuesta conserva `cmms_equipment_id`. Lea `semaforo.color` para mostrar el estado al usuario:

| `semaforo.color` | Confianza | Presentación sugerida |
| --- | --- | --- |
| `verde` | ≥ 0.90 | Clasificación confiable |
| `amarillo` | ≥ 0.70 y < 0.90 | Verificar si es correcto |
| `rojo` | < 0.70 | Requiere revisión manual |

El semáforo es una señal de apoyo, no una validación clínica. La clase MDR, los códigos EMDN y las recomendaciones deben verificarse por personal responsable.

## Abrir la interfaz de corrección

Sirve la interfaz desde un origen permitido y ábrela en una pestaña nueva o en un `iframe` del CMMS:

```html
<iframe
  src="http://localhost:3000/"
  title="Clasificador de equipos médicos"
  width="100%"
  height="800"
></iframe>
```

Para vincular una corrección con el activo, completa el campo opcional **ID de equipo CMMS** con el mismo `cmms_equipment_id`. En una integración embebida en producción, aloja la página en HTTPS bajo un origen institucional permitido en CORS y configura las políticas de `frame-ancestors` del servidor web según el dominio del CMMS.

## Aplicar y consultar una corrección

La interfaz llama a `POST /api/v1/recalcular` para forzar la categoría elegida y recalcular el término EMDN, la clase MDR y la criticidad. Si el biomédico activa el guardado, `POST /api/v1/registrar-correccion` registra la auditoría y un ejemplo de entrenamiento con `source: "USER_CORRECTION"`. La respuesta incluye un `correction_id` que el CMMS puede consultar mediante polling:

```http
GET /api/v1/correcciones/{correction_id}
```

La respuesta de registro es síncrona, por lo que un cliente también puede procesar directamente su `correction_id` como callback HTTP de la solicitud. No se inicia un callback saliente desde el clasificador. Las correcciones se incorporan al conjunto al invocar `/api/v1/reentrenar`; esta operación crea una nueva versión local que debe evaluarse y activarse explícitamente con `MODEL_VERSION` antes de usarla en producción.

## Auditoría y datos

Los registros se guardan localmente en `data/corrections.db` (SQLite) e incluyen marca temporal, campos originales, categorías, confianzas, usuario opcional e identificador CMMS. Protege el servidor y el archivo de base de datos según las políticas de privacidad y acceso de la institución. La API de ejemplo no incorpora autenticación por usuario; no la expongas a redes públicas sin una capa de autenticación y autorización.
