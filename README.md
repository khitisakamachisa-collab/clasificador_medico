# Clasificador médico

Clasificador de equipos médicos para CMMS. Usa nombre, marca y ubicación para obtener una categoría propia, sugerir un código EMDN terminal verificado, asignar clase MDR y calcular criticidad. Incluye reglas bilingües para equipos conocidos y un modelo NLP como respaldo.

## Requisitos

- Python 3.10 o superior.
- Pip.
- El Excel oficial `emdn_codes_2026.xlsx` en `data/raw/` para devolver códigos EMDN verificados. El archivo incluido es la fuente de verdad; no se descargan códigos desde servicios externos.
- Conexión temporal a Internet para instalar dependencias y, opcionalmente, descargar `es_core_news_sm`. El servidor no descarga paquetes ni consulta servicios externos durante la clasificación.

## Instalación

Desde PowerShell, en la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m spacy download es_core_news_sm
```

El último comando solo es necesario si quieres usar el respaldo NLP y el modelo aún no está instalado. Como alternativa, el script de preparación comprueba el modelo y lo descarga solo si hace falta:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

La opción `Bypass` se aplica únicamente a ese proceso de PowerShell, no cambia la política del equipo. Si una política institucional impide ejecutarla, usa los comandos directos anteriores; no hace falta activar el entorno.

También se puede activar el entorno con `.\.venv\Scripts\Activate.ps1` y usar `python -m ...`. En Linux/macOS, activar con `source .venv/bin/activate`.

La configuración está documentada en [.env.example](./.env.example). Copia ese archivo a `.env` antes de iniciar la aplicación. Para habilitar el panel administrativo, configura `ADMIN_API_KEY` con una clave aleatoria fuerte en `.env`; sin ella, las rutas de administración quedan deshabilitadas. No compartas ni publiques `.env`.

Comprueba que el Excel esté en esta ruta:

```text
data/raw/emdn_codes_2026.xlsx
```

El importador espera los encabezados del libro en la segunda fila y reconoce `CODE`, `TERM EMDN`, `LEVEL` y `TERMINAL LEVEL`. Solo incorpora filas marcadas `YES` como terminales.

## Formas de uso

### API REST

Inicia FastAPI desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload
```

Este comando usa directamente el entorno virtual del proyecto, así que no hace falta activar `.venv` primero. Si ya lo activaste, también puedes ejecutar `python -m uvicorn api.main:app --reload`.

Al iniciar, la aplicación carga el Excel y prepara el índice local. Abre `http://127.0.0.1:8000/docs` para probar los endpoints desde Swagger. La ruta `/` también redirige a esa documentación.

Ejemplo de clasificación desde PowerShell:

```powershell
$body = @{
    nombre = "Resonador magnético Siemens"
    marca = "Siemens Healthineers"
    ubicacion = "Imagenología"
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/api/v1/clasificar" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

La solicitud requiere `nombre`; `marca` y `ubicacion` son opcionales. Ejemplo equivalente con `curl`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/clasificar \
  -H "Content-Type: application/json" \
  -d '{"nombre":"Tomógrafo Siemens","marca":"Siemens","ubicacion":"Imagenología"}'
```

Ejemplo real de respuesta. El valor de `codigo_interno` variará según la secuencia persistida de esa categoría:

```json
{
  "categoria_propia": "IMG-02",
  "emdn_code": "Z11050104",
  "emdn_term": "CLOSED MAGNET MRI SCANNERS WITH MAGNETIC FIELD LESS THAN OR EQUAL TO 2T",
  "emdn_verified": true,
  "emdn_candidates": [
    {
      "emdn_code": "Z11050104",
      "emdn_term": "CLOSED MAGNET MRI SCANNERS WITH MAGNETIC FIELD LESS THAN OR EQUAL TO 2T",
      "score": 1.0
    },
    {
      "emdn_code": "Z11050102",
      "emdn_term": "OPEN MAGNET MRI SCANNERS WITH MAGNETIC FIELD INTENSITY LESS THAN OR EQUAL TO 0.5T",
      "score": 0.95
    },
    {
      "emdn_code": "Z11050103",
      "emdn_term": "OPEN MAGNET MRI SCANNERS WITH MAGNETIC FIELD INTENSITY GREATER THAN 0.5T",
      "score": 0.95
    }
  ],
  "mdr_class": "IIb",
  "confidence": 0.96,
  "metodo": "REGLAS",
  "codigo_interno": "IMG02-005",
  "criticidad": {
    "indice": 4.3,
    "nivel": "ALTA"
  }
}
```

Los candidatos EMDN contienen hasta tres sugerencias de la familia filtrada. La respuesta real puede incluir más campos dentro de `criticidad` y candidatos según el equipo. Si falta el Excel o no hay coincidencia terminal válida, `emdn_code` vale `PENDIENTE_DE_VALIDACION` y `emdn_verified` es `false`.

### Interfaz web interactiva

La interfaz está en [index.html](./index.html) y se comunica con `http://localhost:8000/api/v1/clasificar`. Con la API iniciada en una terminal, sirve el proyecto desde otra terminal en la raíz para usar el origen CORS predeterminado (`http://localhost:3000`):

```powershell
.\.venv\Scripts\python.exe -m http.server 3000
```

Abre `http://localhost:3000/` en el navegador. Puedes activar **Modo Demo** en el formulario para mostrar datos simulados sin llamar a la API; si no logra conectarse, la interfaz también activa ese modo y lo indica claramente. Chart.js se carga desde CDN, por lo que el gráfico requiere conexión a Internet.

El panel de administración usa la clave `ADMIN_API_KEY` por solicitud y no la guarda en el navegador. Inicia sesión en **Herramientas de administración** para revisar las correcciones pendientes y habilitar el reentrenamiento. Solo las correcciones aprobadas explícitamente se consideran para entrenar; se requieren al menos diez.

### Python

```python
from src.classifier import clasificar_equipo

resultado = clasificar_equipo(
    "Ventilador mecánico Hamilton Medical",
    "Hamilton Medical",
    "Quirófano",
)

print(resultado["categoria_propia"])
print(resultado["emdn_code"], resultado["emdn_term"])
print(resultado["codigo_interno"], resultado["criticidad"]["nivel"])
```

También se conserva el nombre en inglés:

```python
from src.classifier import classify_equipment

resultado = classify_equipment("Ecógrafo portátil Samsung", "Samsung", "Imagenología")
```

Las reglas maestras de `data/rules/reglas_maestras.json` se priorizan sobre las demás reglas. Cuando ninguna regla coincide, se usa el clasificador TF-IDF/LogisticRegression con el texto de nombre, marca y ubicación. `metodo` indica `REGLAS` o `NLP`; `confidence` es la confianza de la categoría propia, no una probabilidad de que el EMDN sea clínicamente correcto. Se devuelven códigos maestros solo cuando figuran como terminales en el catálogo local; de lo contrario, se usa un candidato terminal o se marca como pendiente.

### CLI interactiva

```powershell
.\.venv\Scripts\python.exe scripts/interactive_classify.py
```

Escribe el nombre del equipo y luego su marca y ubicación. Para salir, escribe `q`, `quit` o `salir` en la pregunta del nombre.

### Pipeline de preparación

```powershell
.\.venv\Scripts\python.exe scripts/run_pipeline.py
```

El pipeline importa el Excel, valida el dataset de ejemplo, entrena el modelo NLP, calcula métricas y clasifica cinco equipos de muestra. Puede tardar más que una consulta normal porque entrena y valida datos.

## Endpoints

| Método | Ruta | Uso |
| --- | --- | --- |
| `POST` | `/api/v1/clasificar` | Clasifica nombre, marca y ubicación; devuelve semáforo y acepta `cmms_equipment_id`. |
| `POST` | `/api/v1/recalcular` | Recalcula clasificación, EMDN, MDR y criticidad con `categoria_forzada`. |
| `POST` | `/api/v1/registrar-correccion` | Persiste auditoría y ejemplo `USER_CORRECTION` en SQLite. |
| `GET` | `/api/v1/correcciones/{correction_id}` | Consulta una corrección registrada para polling desde un CMMS. |
| `POST` | `/api/v1/batch-clasificar` | Clasifica un lote de hasta 100 equipos por defecto. |
| `POST` | `/api/v1/validar-emdn` | Comprueba si un `emdn_code` existe en el índice terminal. |
| `POST` | `/api/v1/validar` | Alias histórico de `/validar-emdn`. |
| `POST` | `/api/v1/buscar-emdn` | Busca términos en los terminales oficiales. |
| `GET` | `/api/v1/categorias` | Devuelve las categorías propias y sus valores MDR por defecto. |
| `GET` | `/api/v1/metricas` | Devuelve métricas del modelo o `503` si todavía no se generaron. |
| `POST` | `/api/v1/reentrenar` | Añade ejemplos y crea una nueva versión del modelo. |
| `GET` | `/api/v1/health` | Comprueba el estado de la API. |

La confianza incluye un semáforo: verde (≥ 0.90), amarillo (≥ 0.70) y rojo (< 0.70). `/api/v1/recalcular` acepta una corrección humana como decisión autorizada con confianza `0.95` y semáforo verde; las validaciones técnicas se conservan como información complementaria. Las correcciones guardadas quedan en `data/corrections.db`; `/api/v1/reentrenar` las incorpora al conjunto de ejemplos para producir una nueva versión local del modelo, únicamente después de aprobación administrativa. Valida la nueva versión y configura `MODEL_VERSION` con su identificador antes de reiniciar la API para activarla.

La API devuelve `400` para solicitudes no válidas, `429` cuando se supera el límite configurado y `503` si las métricas aún no existen. CORS y el límite de solicitudes se configuran con las variables de [.env.example](./.env.example); el limitador incluido es local a cada proceso.

La preparación de integración con un CMMS, incluida la consulta de correcciones por identificador, está en [docs/CMMS_INTEGRATION.md](./docs/CMMS_INTEGRATION.md).

Ejemplo para validar un código:

```powershell
$body = @{ emdn_code = "Z11050104" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/validar-emdn" -Method Post -ContentType "application/json" -Body $body
```

## Arquitectura, integración y validación

- [Arquitectura y flujo de datos](./docs/ARCHITECTURE.md)
- [Referencia de endpoints](./docs/API_REFERENCE.md)
- [Mapeo de categorías a familias EMDN](./docs/EMDN_MAPPING.md)
- [Guía de integración con un CMMS Django](./docs/THESIS_INTEGRATION.md)

El conjunto de ejemplo que genera el validador es sintético y repite seis patrones; sus métricas no representan validación clínica ni sustituyen una evaluación institucional. Las pruebas de regresión incluidas verifican los ejemplos explícitos del proyecto contra el catálogo EMDN local. No se afirma una precisión clínica del 100 %.

### Casos de regresión automatizados

Los 26 casos de prueba validan categoría, código terminal, confianza de reglas (`>= 0.90`) y cálculo de criticidad:

| # | Equipo | Categoría | EMDN terminal esperado |
|---:|---|---|---|
| 1 | Resonador Siemens | IMG-02 | `Z11050104` |
| 2 | Resonador magnético RM Siemens | IMG-02 | `Z11050104` |
| 3 | Ventilador mecánico Hamilton | RES-01 | `Z1203010502` |
| 4 | Tomógrafo Siemens | IMG-02 | `Z11030601` |
| 5 | Respirador Dräger UCI | RES-01 | `Z1203010502` |
| 6 | Equipo de diálisis Baxter | DIA-01 | `Z12090201` |
| 7 | Concentrador de oxígeno Inogen | GAS-01 | `Z12159004` |
| 8 | Lámpara cialítica Maquet | CIR-01 | `Z12010701` |
| 9 | Autoclave de mesa Tuttnauer | EST-01 | `Z12011305` |
| 10 | Autoclave grande Getinge | EST-01 | `Z12011304` |
| 11 | Autoclave odontológico Woson | EST-01 | `Z12011305` |
| 12 | Lámpara móvil Maquet | CIR-01 | `Z12010702` |
| 13 | Ecógrafo Samsung | IMG-03 | `Z11040103` |
| 14 | Ecógrafo Siemens | IMG-03 | `Z11040103` |
| 15 | Respirador Dräger UCI (variante) | RES-01 | `Z1203010502` |
| 16 | Respirador portátil Hamilton | RES-01 | `Z12030104` |
| 17 | Rayos X Siemens | IMG-01 | `Z11030506` |
| 18 | Tomógrafo Siemens (variante) | IMG-02 | `Z11030601` |
| 19 | Monitor de signos vitales Philips | MON-01 | `Z1203020201` |
| 20 | Bomba de infusión Braun | INF-01 | `Z12030301` |
| 21 | Desfibrilador Zoll | URG-01 | `Z12030502` |
| 22 | Máquina de anestesia Dräger | ANE-01 | `Z1203010101` |
| 23 | Máquina de diálisis peritoneal Baxter | DIA-01 | `Z12090101` |
| 24 | Bomba de jeringa Braun | INF-01 | `Z12030302` |
| 25 | Ecógrafo obstétrico GE | IMG-03 | `Z11040105` |
| 26 | Desfibrilador automático Zoll | URG-01 | `Z12030503` |

## Contribuir

Ejecuta `.\.venv\Scripts\python.exe -m pytest --cov=src --cov=api --cov-fail-under=80 -q` antes de proponer cambios. Para modificar reglas o prefijos, agrega casos verificables y comprueba que los códigos sugeridos sean terminales en el Excel oficial. Revisa la política institucional antes de desplegar resultados o asignar criticidad automáticamente.

## Licencia

Este proyecto se distribuye bajo la licencia Apache-2.0. Consulta [LICENSE](./LICENSE).

## Archivos de datos generados

- `data/processed/emdn_database.json`: términos terminales e índice por prefijo creados desde el Excel oficial.
- `data/processed/discrepancias_report.json`: códigos de entrada que no se validaron y sus resultados de búsqueda, para revisión.
- `data/processed/equipos_validados.json`: ejemplos corregidos cuando se encuentra un terminal oficial. Los códigos sin coincidencia no se conservan como válidos.
- `data/models/`: vectorizador, modelo NLP y métricas generadas por el pipeline.
- `data/processed/internal_code_sequences.json`: secuencias persistentes para generar códigos internos únicos por categoría.

## Historial de acciones que funcionaron

1. **Usar el Excel como única fuente de códigos.** El importador lee las filas con `TERMINAL LEVEL = YES` y descarta las demás. Funcionó porque impide que un código genérico o una muestra inventada llegue a la respuesta.
2. **Filtrar por prefijo antes de puntuar términos.** La búsqueda primero restringe candidatos a la familia EMDN de la categoría; después compara términos. Esto evita que coincidencias léxicas como “X-RAY” en accesorios de otra familia compitan con equipos de radiología.
3. **Separar reglas de los códigos terminales.** `src/rules_dictionary.py` contiene categorías, palabras clave, prefijos y subprefijos; `data/rules/reglas_maestras.json` contiene las asignaciones explícitas prioritarias. `emdn_verified` indica si el catálogo local confirma el código configurado.
4. **Añadir reglas para términos clínicos y siglas.** Variantes como “resonador”, “RM”, “MRI”, “tomógrafo”, “respirador” y “ecógrafo” elevan la categoría correcta a `REGLAS` con confianza alta, en vez de dejar esos nombres ambiguos al modelo NLP.
5. **Refinar subfamilias con la ubicación y el tipo de equipo.** “UCI”, “UTI”, “hospital” y “quirófano” seleccionan ventilación hospitalaria; “domicilio” selecciona la rama no hospitalaria. MRI, CT y PET también se separan antes de buscar.
6. **Tratar la ausencia del Excel como estado pendiente.** La clasificación propia sigue disponible, pero se devuelve `PENDIENTE_DE_VALIDACION`; no se fabrica un reemplazo. Esto permite operar sin confundir una categoría predicha con un EMDN verificado.
7. **Persistir el índice y las secuencias internas.** El índice por prefijo evita reconstruir búsquedas desde cero en cada petición, y el contador persistente evita repetir códigos internos tras reiniciar la aplicación.
8. **Probar ejemplos reales contra el libro.** Las pruebas cubren resonancia, tomografía, radiología, ventiladores hospitalarios/portátiles, ultrasonido, monitores, infusión y desfibrilación; además verifican terminalidad y prefijo.

## Actualizar el catálogo EMDN

1. Sustituye `data/raw/emdn_codes_2026.xlsx` por la versión oficial nueva y conserva el nombre esperado por la aplicación, o actualiza la ruta del importador.
2. Verifica que las columnas de código, término y terminalidad se puedan identificar y que las filas finales estén marcadas `YES`.
3. Actualiza `EMDN_PREFIXES` y `EMDN_SUBCATEGORY_PREFIXES` en `src/rules_dictionary.py` consultando la columna `CODE` del nuevo libro. Un prefijo puede tener varias ramas; valida cada una por categoría y no asumas que un prefijo de otra versión sigue siendo válido.
4. Ejecuta `.\.venv\Scripts\python.exe scripts\run_pipeline.py` para reconstruir el índice y revisar el informe de discrepancias.
5. Ejecuta la instrucción de pruebas de la sección siguiente antes de desplegar.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=src --cov=api --cov-report=term-missing --cov-fail-under=80 -q
```

La suite incluye 26 ejemplos de regresión con categoría, código EMDN terminal y criticidad esperados, además de pruebas API, importador, reglas y fallos de dependencias. La clasificación usa el libro local y no necesita APIs externas. La instalación inicial de paquetes y del modelo spaCy sí requiere que esos componentes estén disponibles localmente o se descarguen previamente.
