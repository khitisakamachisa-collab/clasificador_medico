# Roadmap del Proyecto: Clasificador Médico EMDN

Este documento rastrea las observaciones, tareas pendientes y la evolución planificada del sistema.

## 🟢 Fase 1: Estabilización y Reglas (COMPLETADA)

- [x] Corrección del bug de confianza 0% en correcciones manuales.
- [x] Implementación de validación semántica para evitar asignaciones ilógicas.
- [x] Refinamiento del diccionario de reglas (bisturí armónico, lámpara de exploración, monitor secuencial, entre otros).
- [x] Implementación de la matriz de criticidad con ajustes manuales y auditoría.
- [x] Creación de `CHANGELOG.md`.

## 🟡 Fase 2: Mejora del NLP y Dataset (PENDIENTE / EN PLANIFICACIÓN)

*Objetivo: reducir la dependencia de las reglas manuales y mejorar la precisión del NLP a ≥ 80 %, con un conjunto de evaluación representativo y claramente documentado.*

- [ ] **Generación de dataset base:** crear una lista de 200+ nombres de equipos médicos (`equipos_ejemplo.json`).
- [ ] **Clasificación paralela y consenso:** evaluar el uso de 2-3 sistemas de IA para preclasificar, utilizando únicamente el Excel EMDN 2026 como fuente de verdad para los códigos.
- [ ] **Validador automático (`validator.py`):** comparar las salidas y validarlas contra la base de datos EMDN local, separando coincidencias (`equipos_validos.json`) de discrepancias (`discrepancias.json`) para revisión experta.
- [ ] **Knowledge distillation (opcional/avanzado):** evaluar un modelo preentrenado (por ejemplo, BERT médico en español) como modelo maestro para proponer etiquetas que luego se revisen y sirvan para reentrenar el modelo NLP ligero.

## 🟠 Fase 3: Experiencia de Usuario (UX) (PENDIENTE)

*Objetivo: facilitar la corrección manual y reducir errores de escritura.*

- [ ] **Buscador estilo EUDAMATE:** implementar en el frontend un componente de autocompletado que muestre códigos EMDN terminales, términos oficiales y clase MDR, permitiendo seleccionar en lugar de escribir la categoría manualmente.

## 🔴 Fase 4: Integración con CMMS (PENDIENTE)

*Objetivo: desplegar el clasificador como un servicio integrado con el sistema de gestión de mantenimiento.*

- [ ] Desarrollar el cliente API o webhook en el proyecto Django del CMMS.
- [ ] **Pruebas de integración de extremo a extremo (E2E):** registrar un equipo en el CMMS, obtener EMDN y criticidad del clasificador y verificar que el CMMS guarde el resultado.

## 📝 Observaciones y Notas Técnicas

- **Fuente de verdad:** `data/raw/emdn_codes_2026.xlsx` es el catálogo local utilizado para validar los códigos EMDN. Ningún código sugerido por reglas, NLP o herramientas externas debe considerarse verificado si no existe como terminal en ese catálogo.
- **Evaluación:** el objetivo de precisión ≥ 80 % de la Fase 2 requiere un conjunto de prueba representativo, etiquetas revisadas por expertos y métricas reproducibles; el dataset sintético actual no basta para demostrarlo.
- **Rendimiento:** la arquitectura de reglas en memoria y NLP ligero está diseñada para respuestas rápidas. No se fija aquí un umbral de latencia: debe medirse con un benchmark reproducible antes de afirmar un tiempo objetivo.
- **Trazabilidad:** conservar la procedencia de las etiquetas, la versión del catálogo y del modelo y las decisiones de corrección permitirá reproducir y evaluar los resultados en el contexto de la tesis.
