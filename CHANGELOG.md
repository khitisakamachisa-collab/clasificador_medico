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
- Reglas específicas para equipos de electrocirugía ultrasónica (Harmonic).
- Reglas específicas para lámparas de exploración.
- Reglas específicas para monitores multiparámetro secuenciales.

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
