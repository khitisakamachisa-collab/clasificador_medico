# Integración con el CMMS

El CMMS puede consumir el clasificador por HTTP sin compartir su base de datos. Inicia la API en una red accesible para el CMMS y configura `CORS_ORIGINS` si también habrá un cliente web.

## Cliente Python

El ejemplo usa `requests` en el sistema cliente (`python -m pip install requests`); `requests` no es necesario para ejecutar el servidor.

```python
import requests


class ClasificadorMedicoClient:
    def __init__(self, base_url="http://127.0.0.1:8000", timeout=5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def clasificar(self, nombre, marca=None, ubicacion=None):
        response = requests.post(
            f"{self.base_url}/api/v1/clasificar",
            json={"nombre": nombre, "marca": marca, "ubicacion": ubicacion},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
```

## Uso desde una vista Django

```python
cliente = ClasificadorMedicoClient()
resultado = cliente.clasificar("Ecógrafo", "Samsung", "Imagenología")

if resultado["emdn_verified"]:
    equipo.categoria = resultado["categoria_propia"]
    equipo.emdn_code = resultado["emdn_code"]
    equipo.criticidad = resultado["criticidad"]["indice"]
else:
    # Guardar la categoría como sugerencia y solicitar validación humana del EMDN.
    equipo.categoria_sugerida = resultado["categoria_propia"]
```

No marques un código EMDN como verificado si `emdn_verified` es `false`. Registra `confidence`, `metodo` y la advertencia para auditoría. La criticidad calculada es una sugerencia basada en los valores predeterminados del proyecto y debe validarse frente a la política institucional.

## Rendimiento y resiliencia

- Mantén el proceso API activo; el índice EMDN y los artefactos NLP se cargan/reutilizan en el servidor.
- Usa un timeout de conexión/lectura y trata `requests.Timeout` y `requests.ConnectionError` por separado.
- Ante una caída de la API, conserva el registro del equipo y marca la clasificación como pendiente; no fabriques códigos ni conviertas fallos de red en respuestas positivas.
- Para importaciones numerosas, usa `POST /api/v1/batch-clasificar` con lotes de hasta `BATCH_MAX_SIZE`.
- Protege la API con TLS, autenticación y controles de acceso en la red de despliegue. El límite incluido es por proceso y no sustituye controles distribuidos.
- En producción, prueba el tiempo de respuesta con datos y hardware representativos; el objetivo de 100 ms no está garantizado por los tests unitarios.
