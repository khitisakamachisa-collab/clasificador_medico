# Arquitectura

## Componentes

```text
CLI / Cliente CMMS
       |
       v
FastAPI (api/main.py, api/routes.py, api/schemas.py)
       |
       +--> src/classifier.py --> reglas --> categoría propia
       |                    \--> TF-IDF / LogisticRegression (respaldo)
       +--> src/emdn_importer.py --> Excel EMDN local --> terminales verificados
       +--> src/criticality.py --> pesos configurables --> criticidad
       +--> src/code_generator.py --> secuencia persistente por categoría
```

## Flujo de clasificación

1. Pydantic valida y normaliza la entrada.
2. El clasificador busca primero una palabra o frase completa en `rules_dictionary.py`.
3. Si no hay regla, usa el modelo TF-IDF/LogisticRegression local. El vectorizador y el modelo se cargan una sola vez por proceso.
4. Se buscan sugerencias en los códigos EMDN terminales importados del Excel local. Las sugerencias se filtran por prefijo de categoría y se validan contra el índice oficial.
5. Si no existe un código terminal compatible o no se cargó el Excel, se devuelve `PENDIENTE_DE_VALIDACION`; no se inventa un código.
6. Los valores de criticidad por defecto se ajustan según MDR y se ponderan con `CRITICALITY_WEIGHTS_JSON`.
7. Se genera un código interno secuencial, persistido en `data/processed/internal_code_sequences.json`.

## Decisiones y límites

- El sistema híbrido prioriza reglas legibles y reproducibles para términos conocidos; NLP cubre nombres no contemplados.
- El Excel EMDN incluido es la única fuente de códigos oficiales. La aplicación no consulta servicios externos en tiempo de ejecución.
- El índice EMDN y los artefactos del modelo se mantienen en memoria/localmente. La caché de búsqueda se limita a 512 consultas y se invalida al cambiar la fecha de modificación del Excel.
- Los límites de tasa están en memoria por proceso; para despliegues con varios workers se necesita un limitador compartido en el proxy o infraestructura.
- La API permite CORS solo desde `CORS_ORIGINS` y aplica un límite de lote configurable.
- El modelo de ejemplo de `src/validator.py` se genera sintéticamente. Sus métricas no sustituyen una validación clínica ni una evaluación con datos representativos de una institución.
- Una caída del modelo NLP devuelve una categoría provisional `OTR-01`, confianza cero y una advertencia para revisión manual. Una regla conocida sigue funcionando sin NLP.

## Preparación y ejecución

Consulte [README.md](../README.md) para instalación, CLI, API y tests. `scripts/setup.ps1` prepara dependencias y descarga el modelo spaCy de manera explícita; el servidor no intenta acceder a Internet en segundo plano.
