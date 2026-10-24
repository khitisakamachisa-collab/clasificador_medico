# Mapeo de categorías a familias EMDN

Los prefijos limitan la búsqueda de candidatos; **no son códigos EMDN terminales**. El código que devuelve el clasificador se toma del Excel oficial local y debe estar marcado `TERMINAL LEVEL = YES`.

| Categoría propia | Nombre | Prefijo EMDN de búsqueda |
|---|---|---|
| ANE-01 | Anestesia | `Z12030101` |
| CAR-01 | Cardiología Diagnóstica | `Z1205` |
| CAR-02 | Cardiología Terapéutica | `J01` |
| CIR-01 | Quirófano General | `Z1201` |
| CIR-02 | Electrocirugía | `Z120109` |
| DEN-01 | Odontología | `Z1211` |
| DIA-01 | Diálisis | `Z1209` |
| END-01 | Endoscopía | `Z1202` |
| EST-01 | Esterilización | `Z120113` |
| GAS-01 | Gases Medicinales | `Z120309` |
| IMG-01 | Imagenología Rayos X | `Z1103` |
| IMG-02 | Tomografía/Resonancia | `Z110306` |
| IMG-03 | Ultrasonido | `Z1104` |
| LAB-01 | Laboratorio Análisis | `W0201` |
| LAB-02 | Banco de Sangre | `Z1217` |
| MON-01 | Monitoreo Vital | `Z120302` |
| NEO-01 | Neonatología | `Z120804` |
| OFI-01 | Oficina/General | `V08` |
| RES-01 | Respiratorio | `Z120301` |
| TER-01 | Terapia Física | `Z1206` |
| URG-01 | Emergencia | `Z120305` |
| INF-01 | Infusión | `Z120303` |
| FRM-01 | Farmacia | `V08` |
| MOB-01 | Mobiliario Clínico | `V0806` |
| OTR-01 | Otros Equipos | `Z12` |

Los subprefijos contextuales (por ejemplo, CT/MRI/PET, ventilación hospitalaria o domiciliaria, tipo de autoclave) están definidos en `src/rules_dictionary.py`. La búsqueda sigue verificando la terminalidad contra el catálogo, y un prefijo sin coincidencia nunca se convierte por sí mismo en una respuesta EMDN.

## Referencia y actualización

La fuente instalada es `data/raw/emdn_codes_2026.xlsx`. La importación toma las columnas `CODE`, `TERM EMDN`, `LEVEL` y `TERMINAL LEVEL`; los encabezados están en la segunda fila. Revisa el catálogo oficial y ejecuta el pipeline y los tests antes de actualizar prefijos a otra edición.
