# Estructura del Proyecto

```
oceano/
├── app/
│   ├── app/
│   │   ├── __init__.py           # Inicialización del paquete
│   │   ├── main.py               # API FastAPI principal
│   │   ├── embeddings.py         # Lógica de InsightFace
│   │   ├── ingest.py             # Script de ingesta de imágenes
│   │   ├── metrics.py            # Métricas y monitoreo
│   │   ├── static/
│   │   │   └── style.css         # Estilos CSS
│   │   └── templates/
│   │       └── index.html        # Interfaz web
│   └── requirements.txt          # Dependencias Python
│
├── logs/                         # Logs de la aplicación
├── state/                        # Base de datos SQLite
├── thumbs/                       # Miniaturas de imágenes
├── models/                       # Modelos de InsightFace
├── qdrant_storage/               # Datos de Qdrant
│
├── Dockerfile                    # Imagen Docker de la API
├── docker-compose.yml            # Orquestación de servicios
├── entrypoint.sh                 # Script de inicio del contenedor
│
├── README.md                     # Documentación principal
├── INSTALL.md                    # Guía de instalación
├── FAQ.md                        # Preguntas frecuentes
├── CHANGELOG.md                  # Historial de cambios
├── LICENSE                       # Licencia MIT
├── STRUCTURE.md                  # Este archivo
│
├── .gitignore                    # Archivos ignorados por Git
├── .env.example                  # Ejemplo de configuración
└── quick-start.sh                # Script de inicio rápido
```

## Descripción de Componentes

### Aplicación (`app/`)

#### `main.py`
- API REST con FastAPI
- Endpoints de búsqueda y health checks
- Manejo de requests con retry logic
- Integración con Qdrant

#### `embeddings.py`
- Carga y gestión del modelo InsightFace
- Extracción de embeddings faciales
- Detección de corrupción del modelo
- Fallbacks para imágenes difíciles

#### `ingest.py`
- Ingesta masiva de imágenes
- Procesamiento paralelo
- Integración con Qdrant
- Tracking de progreso en SQLite

#### `metrics.py`
- Métricas de performance
- Monitoreo de recursos
- Estadísticas de uso

### Infraestructura

#### `Dockerfile`
- Imagen base: NVIDIA CUDA 11.8
- Python 3 con dependencias
- Configuración de GPU

#### `docker-compose.yml`
- Servicio API (FastAPI + InsightFace)
- Servicio Qdrant (base de datos vectorial)
- Configuración de red y volúmenes
- Variables de entorno

#### `entrypoint.sh`
- Script de inicio del contenedor
- Configuración de workers
- Validación de GPU

### Datos

#### `logs/`
- Logs de la aplicación
- Logs de errores
- Logs de acceso

#### `state/`
- Base de datos SQLite
- Estado de ingesta
- Metadatos

#### `thumbs/`
- Miniaturas de imágenes procesadas
- Usadas en resultados de búsqueda

#### `models/`
- Modelos de InsightFace
- Descargados automáticamente

#### `qdrant_storage/`
- Datos de Qdrant
- Índices HNSW
- Vectores cuantizados

### Documentación

#### `README.md`
- Documentación principal
- Guía de uso rápido
- Ejemplos de API

#### `INSTALL.md`
- Guía de instalación detallada
- Requisitos del sistema
- Solución de problemas

#### `FAQ.md`
- Preguntas frecuentes
- Problemas comunes
- Tips de optimización

#### `CHANGELOG.md`
- Historial de versiones
- Cambios y mejoras
- Correcciones de bugs

## Flujo de Datos

### Ingesta
```
Imágenes → embeddings.py → InsightFace → Vectores 512D → Qdrant
                                                        ↓
                                                    SQLite (metadata)
```

### Búsqueda
```
Imagen Query → embeddings.py → InsightFace → Vector 512D
                                                ↓
                                            Qdrant Search
                                                ↓
                                            Top K Results
                                                ↓
                                            FastAPI Response
```

## Puertos

- `9100`: API REST (FastAPI)
- `9101`: Qdrant HTTP
- `9102`: Qdrant gRPC

## Variables de Entorno Importantes

### Workers
- `UVICORN_WORKERS=1` - CRÍTICO: Mantener en 1
- `GPU_CONCURRENCY=1` - Serializar acceso a GPU

### Performance
- `UVICORN_LIMIT_CONCURRENCY=256` - Requests concurrentes
- `HNSW_EF=512` - Precisión de búsqueda

### Modelo
- `MODEL_NAME=antelopev2` - Modelo de InsightFace
- `DET_SIZE=640,640` - Tamaño de detección

## Dependencias Principales

### Python
- FastAPI - Framework web
- InsightFace - Reconocimiento facial
- qdrant-client - Cliente de Qdrant
- OpenCV - Procesamiento de imágenes
- NumPy - Operaciones numéricas

### Sistema
- Docker - Contenedorización
- NVIDIA CUDA - Aceleración GPU
- Qdrant - Base de datos vectorial

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                      Cliente                            │
│                   (Navegador/API)                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                   FastAPI (Puerto 9100)                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Endpoints: /search, /health, /status           │  │
│  │  Middleware: Timeout, CORS                       │  │
│  │  Retry Logic: Exponential backoff                │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
┌─────────────────┐    ┌──────────────────┐
│  InsightFace    │    │     Qdrant       │
│  (antelopev2)   │    │  (Puerto 9101)   │
│                 │    │                  │
│  - GPU CUDA     │    │  - HNSW Index    │
│  - Embeddings   │    │  - Quantization  │
│  - 512D vectors │    │  - 6M+ vectors   │
└─────────────────┘    └──────────────────┘
```

## Escalabilidad

### Vertical (Recomendado)
- GPU más potente
- Más RAM
- SSD más rápido

### Horizontal (Futuro)
- Múltiples instancias de API
- Load balancer
- Qdrant distribuido

**Nota**: Actualmente optimizado para escalado vertical con 1 worker por instancia.
