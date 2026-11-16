# Metodología del Sistema Clasificador de Equipos Médicos EMDN
## Tesis de Maestría en Ingeniería Biomédica — 2026
### Autor: Raúl Alejandro Quispe Larico

**Programa:** Maestría en Ingeniería Biomédica  
**Módulo:** Tecnologías Emergentes Aplicadas a Ingeniería Biomédica  
**Contexto de aplicación propuesto:** Bolivia y Latinoamérica, en clínicas, importadores y hospitales pequeños (menos de 100 camas).

> **Estado del documento:** metodología de un prototipo de apoyo a la clasificación. Los resultados aquí informados describen la versión y los archivos disponibles en el repositorio a la fecha de ejecución; no constituyen una validación clínica ni una evaluación externa.

---

## 1. Filosofía de clasificación (regla de oro)

El sistema adopta una postura conservadora y trazable frente a la nomenclatura EMDN v2026:

> Clasificar al nivel EMDN más bajo posible únicamente cuando la información disponible lo permite. Si el nombre del equipo no contiene información suficiente para distinguir entre varias hojas terminales, se debe utilizar el último nodo común válido y marcarlo explícitamente como pendiente de desambiguación.

Una hoja terminal representa una categoría sin subdivisiones adicionales en la versión consultada del catálogo. La validez sintáctica de un código no demuestra, por sí sola, que ese código describa correctamente el equipo; la selección también requiere concordancia clínica y técnica.

### 1.1 Ejemplo: tomógrafo computarizado

Los siguientes códigos y niveles se verificaron contra el libro EMDN 2026 incluido en `data/raw/emdn_codes_2026.xlsx`.

| Información disponible | Propuesta | Nivel en el Excel | Interpretación |
|---|---|---:|---|
| «Tomógrafo computarizado», sin especificación técnica | `Z110306` | 4, no terminal | Nodo común; requiere desambiguación |
| Tomógrafo con hasta 2 cortes/capas | `Z11030601` | 5, terminal | Hoja correspondiente al intervalo |
| Tomógrafo con más de 2 y menos de 16 cortes/capas | `Z11030602` | 5, terminal | Hoja correspondiente al intervalo |
| Tomógrafo con 16 o más y menos de 64 cortes/capas | `Z11030603` | 5, terminal | Hoja correspondiente al intervalo |
| Tomógrafo con 64 o más y menos de 128 cortes/capas | `Z11030605` | 5, terminal | Hoja correspondiente al intervalo |
| Tomógrafo con 128 o más y menos de 256 cortes/capas | `Z11030606` | 5, terminal | Hoja correspondiente al intervalo |
| Tomógrafo con 256 o más cortes/capas | `Z11030607` | 5, terminal | Hoja correspondiente al intervalo |

El nombre comercial por sí solo no se toma como prueba de una característica técnica. Por ejemplo, una propuesta de 128 cortes debe confirmarse con la ficha técnica del fabricante antes de asignar `Z11030606`. La nomenclatura oficial describe estos rangos en términos de “layers”; en el uso clínico hispanohablante suele expresarse como cortes, pero la equivalencia del equipo concreto debe verificarse.

### 1.2 Algoritmo de decisión EMDN

1. Identificar la función prevista del equipo y el contexto clínico/técnico disponible.
2. Buscar candidatos en el catálogo oficial y comprobar que el código exista.
3. Si una única hoja terminal representa la función y las especificaciones disponibles, proponer esa hoja.
4. Si varias hojas terminales siguen siendo posibles, no escoger una arbitrariamente: proponer el último ancestro común válido y activar `requiere_desambiguacion`.
5. Si no se encuentra una correspondencia sustentada, dejar el código sin asignar y solicitar revisión manual.

La revisión del nodo padre debe considerar también el indicador oficial `TERMINAL LEVEL`: un nodo padre válido puede ser no terminal. No se convierte en hoja terminal por ser un código existente.

---

## 2. Arquitectura híbrida y responsabilidades

El sistema es una herramienta de apoyo que combina reglas deterministas, clasificación de categoría, consulta EMDN local y controles humanos. Las capas representan responsabilidades del flujo, no componentes con exactitud individual demostrada.

| Etapa | Implementación | Responsabilidad | Evidencia cuantitativa disponible |
|---|---|---|---|
| Reglas | `src/rules_dictionary.py`, `src/classifier.py` | Resolver términos y patrones explícitos antes de invocar NLP | No existe evaluación independiente de accuracy de esta etapa |
| Categoría NLP | TF-IDF y regresión logística, cargados por `src/classifier.py` | Proponer una categoría funcional cuando no coincide una regla | Evaluación interna de categoría: 75,27 % de accuracy media en la búsqueda CV reportada abajo |
| Catálogo y validación | `src/emdn_importer.py`, `src/validator.py` | Buscar términos del Excel, restringir candidatos por familia y comprobar existencia/terminalidad; el validador de sugerencias también contrasta categoría | La validez estructural se comprueba por código; no se ha medido exactitud clínica del mapeo EMDN |
| Revisión humana | Rutas administrativas de correcciones y revisión de propuestas | Aprobar, rechazar o solicitar información adicional para correcciones | No equivale a 100 % de exactitud; la concordancia entre revisores no ha sido medida |

En tiempo de clasificación, el código busca primero una regla; si no encuentra coincidencia, predice la categoría con el modelo NLP. Luego consulta los candidatos EMDN terminales de la familia asociada y valida que el código seleccionado sea terminal en el índice local. Si no hay un candidato admisible, el sistema devuelve `PENDIENTE_DE_VALIDACION` en vez de fabricar un código. El panel administrativo permite gestionar correcciones, pero no se afirma que toda salida ambigua se bloquee automáticamente hasta ser revisada.

No se dispone de una evaluación por capa que justifique “>95 %” para reglas, “>90 %” para búsqueda o “100 %” para revisión humana. Tampoco se calculó la accuracy global extremo a extremo del pipeline. Por tanto, no es defendible afirmar una precisión global superior al 90 % con la evidencia actual. La accuracy del NLP mide la predicción de la **categoría funcional interna**, no la exactitud de asignación de códigos EMDN.

---

## 3. Datos, procedencia y control de errores

### 3.1 Fuentes y unidad de análisis

La unidad de análisis es un registro de equipo descrito principalmente por su nombre; cuando están disponibles, también pueden utilizarse marca y ubicación. El proyecto emplea:

- `data/raw/emdn_codes_2026.xlsx`: catálogo EMDN local, con encabezados en la segunda fila. El importador reconoce código, término y nivel terminal.
- `data/processed/equipos_validados_masivo.json`: registros aceptados por el proceso de validación.
- `data/processed/discrepancias_masivo.json`: registros que el proceso masivo no pudo validar.
- Correcciones revisadas y guardadas por la aplicación, que pueden incorporarse al entrenamiento.
- `data/processed/equipos_entrenamiento_final.json`, cuando existe, como conjunto base preferido por el entrenador.

Los registros procesados no deben interpretarse automáticamente como una muestra aleatoria de todos los equipos médicos de Bolivia. No se documenta un muestreo probabilístico por hospital, fabricante o región; la representatividad y la ausencia de duplicados entre instituciones requieren estudio adicional.

### 3.2 Generación de sugerencias y prevención de códigos inventados

En el flujo de generación masiva, el modelo local puede sugerir la categoría funcional, mientras que la búsqueda y validación de códigos corresponde a Python y al catálogo EMDN local. El validador de sugerencias rechaza un registro cuando el código está ausente del Excel, no está marcado `YES` en `TERMINAL LEVEL`, o no concuerda con la familia/categoría verificada por el proyecto. El proceso separa los registros aceptados de las discrepancias; no corrige silenciosamente la respuesta del modelo.

Este diseño reduce la posibilidad de aceptar códigos inexistentes o de otras nomenclaturas, pero no demuestra una tasa de alucinación igual a cero ni garantiza que cada código terminal sea semánticamente correcto para el equipo. La revisión de la descripción y del uso previsto sigue siendo necesaria. El repositorio registra un lote de 200 filas procesadas como 163 registros validados y 37 discrepancias en los archivos masivos disponibles; esos conteos describen ese lote, no un rendimiento generalizable. Las cifras históricas “0 validados de 200” y ejemplos de códigos atribuidos a otras nomenclaturas no se reproducen como resultados experimentales porque no se encontró un informe versionado que permita auditarlos.

---

## 4. Preparación del conjunto de entrenamiento

El entrenador fusiona los equipos del archivo base con correcciones aprobadas y elimina duplicados priorizando la corrección aprobada cuando coincide la identidad del equipo. Las etiquetas utilizadas son las categorías internas del proyecto (`ANE-01`, `IMG-03`, entre otras), no códigos EMDN.

Antes del ajuste se cuentan los ejemplos por categoría. La configuración actual excluye del entrenamiento las categorías con menos de tres ejemplos. En la ejecución reflejada por `data/models/metrics_final.json`:

| Etapa | Registros |
|---|---:|
| Dataset deduplicado antes de limpieza | 198 |
| Dataset tras excluir categorías con menos de 3 ejemplos | 195 |
| Ejemplos excluidos por esa regla | 3 |
| Categorías excluidas por esa regla | 2: `FRM-01`, `LAB-02` |

Después de esa limpieza, 13 ejemplos de cuatro categorías con solo 3–4 observaciones se conservaron dentro de los conjuntos de entrenamiento de cada pliegue, pero se excluyeron de las particiones de prueba. En consecuencia, las métricas CV se calcularon sobre 182 ejemplos de 19 categorías. Esta decisión permite que los registros poco frecuentes contribuyan al modelo final sin presentar como evaluables categorías que no pueden distribuirse de forma representativa entre cinco pliegues.

Si la limpieza deja menos de dos categorías entrenables, el código activa un fallback al dataset original para poder ajustar un modelo, informa que la evaluación CV no está disponible y no publica métricas de accuracy fabricadas. El caso límite de una sola categoría utiliza un clasificador de clase mayoritaria; no debe interpretarse como evidencia de desempeño multiclase.

---

## 5. Representación textual y modelo

El texto de entrada se construye con nombre, marca y ubicación. El preprocesamiento del proyecto convierte el texto a minúsculas, filtra signos y números según las reglas implementadas y tokeniza con spaCy en español; si el modelo lingüístico no está instalado, se usa un tokenizador en blanco. La configuración del entorno debe documentarse al replicar el experimento porque puede afectar la lematización.

La búsqueda evalúa una canalización de vectorización TF-IDF y regresión logística. Las familias de características consideradas son:

1. TF-IDF de palabras: unigramas o unigramas/bigramas, `min_df` 1 o 2, `max_df` 0,75 o 1,0.
2. TF-IDF de caracteres (`char_wb`): n-gramas de caracteres (2,4), (2,5) o (3,5), `min_df` 1 o 2.
3. Unión de características de palabras y caracteres.

La grilla prueba `C` ∈ {0,1; 1; 10} para regresión logística, con ponderación balanceada de clases. Se selecciona la combinación con mayor accuracy media (`refit="accuracy"`); F1 macro se registra como métrica secundaria. El vectorizador se ajusta dentro del pipeline de cada fold, evitando ajustar el vocabulario con el pliegue de prueba.

---

## 6. Protocolo de evaluación

Se utiliza `StratifiedKFold` de cinco pliegues con barajado y semilla `42`, integrado con `GridSearchCV`. Para permitir cinco pliegues estratificados, solo las categorías con al menos cinco ejemplos se distribuyen entre los conjuntos de prueba. Los registros de categorías con menos de cinco ejemplos se agregan únicamente a los índices de entrenamiento en cada split.

Los pliegues de prueba contienen entre 36 y 37 ejemplos. Cada conjunto de entrenamiento contiene entre 158 y 159 registros, incluidos los ejemplos de baja frecuencia retenidos. Se calculan accuracy y F1 macro en cada fold. El F1 macro se calcula sobre las 19 categorías evaluadas y asigna igual peso a cada categoría. El desvío informado es la desviación estándar poblacional (`ddof=0`) de las cinco puntuaciones.

El proceso elige los hiperparámetros y reporta el promedio sobre los mismos cinco pliegues. Por tanto, la estimación está sujeta a sesgo de selección y puede ser optimista: no equivale a una evaluación independiente de un modelo previamente fijado. Para una estimación final de tesis se recomienda validación cruzada anidada o un conjunto de prueba externo, institucional y no utilizado para ajustar hiperparámetros.

Para cada pliegue \(k\), la accuracy se define como \(A_k = \frac{1}{n_k}\sum_{i=1}^{n_k} \mathbf{1}(\hat{y}_i = y_i)\). El F1 macro es \(F_k = \frac{1}{C}\sum_{c=1}^{C} 2\frac{P_{kc}R_{kc}}{P_{kc}+R_{kc}}\), donde \(C=19\) categorías evaluadas y \(P_{kc}\), \(R_{kc}\) son precisión y recall de la categoría \(c\) en el pliegue. El promedio informado es \(\bar{A}=\frac{1}{5}\sum_{k=1}^{5}A_k\), y la desviación estándar informada es poblacional: \(\sigma_A=\sqrt{\frac{1}{5}\sum_{k=1}^{5}(A_k-\bar{A})^2}\). Al promediar folds de tamaños 36–37 con el mismo peso, el resultado no es idéntico a la accuracy agrupada de todas las predicciones.

---

## 7. Resultados reproducibles disponibles

La ejecución registrada en `data/models/metrics_final.json` seleccionó TF-IDF de caracteres con n-gramas `(2, 4)`, `min_df=1` y regresión logística con `C=1.0`.

| Métrica | Resultado |
|---|---:|
| Accuracy media de 5 folds | 0,7527 (75,27 %) |
| Desviación estándar de accuracy | 0,0633 (6,33 puntos porcentuales) |
| F1 macro medio | 0,7369 (73,69 %) |
| Desviación estándar de F1 macro | 0,0724 |
| Ejemplos antes de limpieza | 198 |
| Ejemplos tras limpieza | 195 |
| Ejemplos evaluados en CV | 182 |
| Categorías evaluadas | 19 |
| Pliegues | 5 |

| Fold | Accuracy | F1 macro | Prueba (n) |
|---:|---:|---:|---:|
| 1 | 0,7838 | 0,7837 | 37 |
| 2 | 0,7297 | 0,7754 | 37 |
| 3 | 0,8056 | 0,7890 | 36 |
| 4 | 0,6389 | 0,5962 | 36 |
| 5 | 0,8056 | 0,7404 | 36 |

La accuracy observada es inferior al objetivo exploratorio de 80 %. La variabilidad entre folds tampoco es nula, y el cuarto fold presenta menor rendimiento. No se debe describir el resultado como “>80 %”, como rendimiento clínico, ni como precisión del código EMDN. La matriz de confusión por categoría y un análisis de errores deberían acompañar la versión final de la tesis.

El conjunto de datos y el protocolo cambiaron entre iteraciones; por ello, métricas históricas de otras versiones (incluidos resultados de un split único o de un conjunto sintético) no son directamente comparables con esta búsqueda CV. Los datos sintéticos sirven para pruebas de software, no como evidencia de generalización clínica.

---

## 8. Interpretación para el contexto de Bolivia

La orientación a clínicas, importadores y hospitales pequeños define el contexto previsto, no una validación geográfica ya realizada. La evaluación disponible no permite concluir que el desempeño sea el mismo en hospitales bolivianos, en equipos de fabricantes no representados o en nomenclaturas locales. Antes de uso operativo se recomienda:

1. Construir un conjunto de prueba multicéntrico con equipos reales y autorización institucional.
2. Separar equipos o instituciones completas entre entrenamiento y prueba para medir generalización, no solo nombres parecidos.
3. Hacer revisión independiente por al menos dos profesionales biomédicos y documentar el proceso de adjudicación.
4. Medir exactitud de categoría, exactitud de código EMDN, porcentaje de códigos terminales correctos, tasa de abstención/desambiguación y acuerdo interevaluador por separado.
5. Analizar errores por categoría, frecuencia, fabricante, idioma, tipo de equipo y nivel de especificidad EMDN.
6. Mantener revisión humana antes de incorporar cambios al inventario o a un sistema de gestión de mantenimiento.

No se debe afirmar que el error del NLP “nunca impacta” un inventario: esto depende de controles de implementación, flujos de aprobación y supervisión que deben probarse en cada institución.

---

## 9. Limitaciones, ética y trabajo futuro

- **Tamaño y representatividad:** menos de 200 ejemplos de entrenamiento tras deduplicación, con fuerte desbalance entre categorías. Las clases raras no tienen suficiente soporte para una estimación fiable.
- **Optimismo de selección:** `GridSearchCV` selecciona hiperparámetros y estima rendimiento con los mismos folds. Se requiere validación anidada o externa para una estimación confirmatoria.
- **Etiquetas:** las categorías y códigos aprobados pueden contener errores de origen; la validación estructural de un código no sustituye la adjudicación clínica.
- **Alcance de métricas:** la CV reportada evalúa categorías internas, no la selección EMDN terminal ni el flujo completo de cuatro etapas.
- **Lengua y dominio:** el sistema está principalmente orientado a nombres en español y términos del catálogo en inglés; variaciones regionales, marcas y traducciones pueden reducir el desempeño.
- **Automatización:** un resultado de baja confianza o sin código verificado debe ser revisado. La interfaz administrativa no convierte por sí sola cada predicción en una recomendación aprobada.
- **Seguridad operacional:** el prototipo no reemplaza el juicio del profesional biomédico, la documentación del fabricante ni los procedimientos regulatorios institucionales.

El trabajo futuro debería ampliar y versionar un corpus representativo, medir la concordancia entre expertos, implementar abstención explícita por incertidumbre, calibrar probabilidades, realizar validación externa y evaluar el pipeline completo con métricas de código EMDN y tiempos de revisión.

---

## 10. Reproducibilidad y artefactos

Desde la raíz del repositorio, el entrenamiento actual se ejecuta con:

```powershell
.\.venv\Scripts\python.exe -m src.trainer
```

El comando usa `data/processed/equipos_entrenamiento_final.json` si está disponible; en caso contrario, usa `data/processed/equipos_validados_masivo.json`. Añade correcciones aprobadas persistidas por la aplicación, deduplica, ejecuta la limpieza y la búsqueda de hiperparámetros, y guarda el modelo y métricas bajo `data/models/`.

Para reproducir formalmente el experimento en la tesis, registrar junto con los resultados: revisión del código (commit), fecha de ejecución, versiones de Python y dependencias, configuración de spaCy, hash de los archivos de datos y versión exacta del Excel EMDN. El uso de `random_state=42` controla el barajado de los folds, pero no sustituye el registro de versiones ni garantiza idénticos resultados ante cambios de bibliotecas o datos.

### Referencias internas del proyecto

- [Arquitectura](./ARCHITECTURE.md)
- [Mapeo EMDN](./EMDN_MAPPING.md)
- [README y ejecución](../README.md)
- Código de entrenamiento: `src/trainer.py`
- Clasificador y búsqueda EMDN: `src/classifier.py`, `src/emdn_importer.py`
- Validación de sugerencias: `src/validator.py`
- Métricas archivadas: `data/models/metrics_final.json`
