# Changelog

Todos los cambios notables en este proyecto serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/),
y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/).

## [No publicado]

### Corregido
- Bug crítico: Confianza 0% en correcciones manuales. Ahora devuelve 95% con semáforo VERDE y el mensaje "Validado manualmente por experto biomédico".
- "Bisturí armónico (Harmonic)" ahora clasifica correctamente como CIR-02 / K0202010201 (ULTRASONIC OPEN SURGERY HANDPIECES) en lugar de CIR-01 / L010101.
- "Lámpara exploración móvil" ahora clasifica correctamente como CIR-01 / Z129004 (LIGHT SOURCES) con 95% de confianza.
- "Monitor secuencial" ahora clasifica correctamente como MON-01 / Z1203020201 (MULTI-PARAMETER PATIENT BEDSIDE MONITORS) con 95% de confianza.

### Agregado
- Modelo de criticidad ponderada por equipo con perfiles externos por categoría, modificadores contextuales de creación, auditoría de ajustes y actualización externa por MTBF; incluye simulador de datos de prueba.
- Endpoints administrativos para ajustar criticidad y actualizar MTBF, consulta de auditoría y reporte de distribución.
- Autenticación administrativa unificada: un único modal reutilizable valida `ADMIN_API_KEY` para reentrenamiento, ajustes de criticidad y acceso a revisiones.
- Radar comparativo equipo/categoría, panel de ajuste justificado y reportes de criticidad en la página principal.
- Documentación del modelo y validador del catálogo de valores por defecto.
- Reglas específicas para equipos de electrocirugía ultrasónica (Harmonic).
- Reglas específicas para lámparas de exploración.
- Reglas específicas para monitores multiparámetro secuenciales.

## [1.2.4] - 2026-11-08

### Corregido (Fixed)
- **UX Ubicación:** Se reemplazó el `<datalist>` por un `<select>` nativo en el formulario de clasificación. Esto elimina el "círculo vicioso" de auto-filtrado y permite cambiar la ubicación seleccionada con un solo clic.
- **Panel de Administración:** Se eliminó el título "Panel de administración" y el botón "Volver al inicio" duplicados en la parte superior de la vista de admin, dejando solo los controles de acción inferiores.

### Mejorado (Improved)
- Flujo de navegación en la vista de Administración más limpio y directo.

## [1.2.0] - 2026-11-05

### Agregado
- Buscador con autocompletado estilo EUDAMATE en el frontend.
- Endpoint `GET /api/v1/buscar` para búsqueda difusa de términos y códigos EMDN.
- Diccionario de sinónimos médicos en `data/rules/sinonimos_medico.json`.
- Normalización de texto en la búsqueda difusa (tildes, mayúsculas y palabras vacías).
- Priorización de reglas maestras sobre el LLM en la generación del dataset.

### Mejorado
- Accuracy del modelo NLP de 67.8 % a 77.1 % (v3).
- Recuperación de 27 equipos adicionales del conjunto de discrepancias.
- Umbral de similitud ajustado de 0.40 a 0.30 para términos español-inglés.

### Corregido
- Importación relativa en `trainer.py` para su ejecución como módulo.
- Campo `administrador` opcional en el endpoint de MTBF.

### Documentación
- README actualizado con métricas y estado actual.
- ROADMAP actualizado con fases completadas y pendientes.

## [1.0.0] - 2026-10-26

### Agregado
- Clasificador médico independiente con sistema híbrido (reglas + NLP).
- Validación cruzada contra Excel EMDN 2026 oficial.
- API REST con FastAPI.
- Frontend web con semáforo visual (verde/amarillo/rojo).
- Sistema de corrección manual con validación en 2 niveles.
- Exportación de historial de clasificaciones.
- Gráfico de radar para criticidad.
- Autenticación de administrador.
- Licencia Apache 2.0.
- 107 tests unitarios con 85% de cobertura.
