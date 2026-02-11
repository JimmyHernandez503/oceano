# Oceano - Sistema de Reconocimiento Facial

Sistema de reconocimiento facial de alto rendimiento basado en InsightFace (modelo antelopev2) y Qdrant para búsqueda vectorial. Optimizado para producción con arquitectura robusta y estable.

## 🎯 Características

- **Reconocimiento facial preciso** usando InsightFace antelopev2
- **Búsqueda vectorial rápida** con Qdrant y cuantización escalar
- **API REST** con FastAPI
- **Interfaz web** para búsquedas interactivas
- **Ingesta masiva** de imágenes con procesamiento paralelo
- **Arquitectura robusta** con retry logic y manejo de errores
- **Optimizado para GPU** NVIDIA con CUDA
- **Dockerizado** para fácil despliegue

## 📋 Requisitos

### Hardware
- GPU NVIDIA con soporte CUDA (recomendado: RTX 3090/4090 o superior)
- 16GB+ RAM
- 50GB+ espacio en disco

### Software
- Docker y Docker Compose
- NVIDIA Container Toolkit (para soporte GPU)
- Linux (Ubuntu 20.04+ recomendado)

## 🚀 Instalación Rápida

### 1. Clonar el Repositorio

```bash
git clone https://github.com/tu-usuario/oceano.git
cd oceano
```

### 2. Configurar Volúmenes

Edita `docker-compose.yml` y ajusta las rutas de los volúmenes:

```yaml
volumes:
  - ./logs:/logs
  - ./state:/state
  - /ruta/a/tus/thumbs:/data/thumbs      # Miniaturas de imágenes
  - /ruta/a/tus/models:/models           # Modelos de InsightFace
```

### 3. Descargar Modelos

Los modelos de InsightFace se descargan automáticamente en el primer inicio. Alternativamente, descárgalos manualmente:

```bash
# El modelo antelopev2 se descargará automáticamente en /models
# O descarga manualmente desde: https://github.com/deepinsight/insightface/releases
```

### 4. Iniciar el Sistema

```bash
docker compose up -d
```

### 5. Verificar Estado

```bash
# Health check
curl http://localhost:9100/health

# Debería responder:
# {
#   "status": "healthy",
#   "ready": true,
#   "checks": {
#     "model_loaded": true,
#     "qdrant_healthy": true
#   }
# }
```

## 📖 Uso

### Interfaz Web

Abre tu navegador en: `http://localhost:9100`

1. Sube una imagen con un rostro
2. El sistema buscará rostros similares en la base de datos
3. Verás los resultados ordenados por similitud

### API REST

#### Búsqueda de Rostros

```bash
curl -X POST -F "file=@imagen.jpg" http://localhost:9100/search
```

#### Health Check

```bash
curl http://localhost:9100/health
```

#### Estado de la Colección

```bash
curl http://localhost:9100/status
```

## 🗄️ Ingesta de Imágenes

Para agregar imágenes a la base de datos:

```bash
# Ingesta desde una carpeta
docker exec oceano-api python3 -m app.ingest \
  --path /ruta/a/imagenes \
  --batch 100
```

### Opciones de Ingesta

```bash
# Opciones disponibles
--path       Directorio o archivo de imágenes (requerido)
--batch      Tamaño de lote para upsert (default: 1024)
--no-resume  Ignorar estado y reprocesar todo
--workers    Número de threads para I/O paralelo (default: 32)
```

## ⚙️ Configuración

### Variables de Entorno

Edita `docker-compose.yml` para ajustar la configuración:

```yaml
environment:
  # Workers (IMPORTANTE: mantener en 1 para evitar race conditions)
  - UVICORN_WORKERS=1
  - UVICORN_WORKERS_GPU_MAX=1
  
  # Concurrencia
  - UVICORN_LIMIT_CONCURRENCY=256
  - UVICORN_BACKLOG=16384
  - GPU_CONCURRENCY=1
  
  # Timeouts
  - REQUEST_TIMEOUT=30
  - GPU_ACQUIRE_TIMEOUT=5.0
  
  # Qdrant
  - QDRANT_URL=http://qdrant:6333
  - COLLECTION_NAME=faces
  
  # Modelo InsightFace
  - MODEL_NAME=antelopev2
  - DET_SIZE=640,640
  
  # Búsqueda
  - TOP_K=10
  - SIM_THRESHOLD=0.0
  - HNSW_EF=512
```

### Optimización de Qdrant

Para colecciones grandes (millones de vectores), ajusta los parámetros de Qdrant en `docker-compose.yml`:

```yaml
environment:
  - QDRANT__STORAGE__PERFORMANCE__MAX_SEARCH_THREADS=16
  - QDRANT__STORAGE__OPTIMIZERS__MAX_OPTIMIZATION_THREADS=8
  - QDRANT__STORAGE__PERFORMANCE__OPTIMIZER_CPU_BUDGET=8
```

## 🏗️ Arquitectura

```
┌─────────────────┐
│   Cliente Web   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   FastAPI API   │  ← Puerto 9100
│  (1 worker)     │
└────────┬────────┘
         │
         ├──────────────┐
         ▼              ▼
┌─────────────┐  ┌──────────────┐
│ InsightFace │  │   Qdrant     │
│ (antelopev2)│  │  (vectores)  │
│   + GPU     │  │              │
└─────────────┘  └──────────────┘
```

### Componentes

- **FastAPI**: API REST para búsquedas y gestión
- **InsightFace**: Modelo de reconocimiento facial (antelopev2)
- **Qdrant**: Base de datos vectorial para búsqueda de similitud
- **CUDA**: Aceleración GPU para inferencia

## 📊 Performance

### Throughput
- 50 requests concurrentes: ~22 req/s
- 100 requests concurrentes: ~19 req/s
- 200 requests concurrentes: ~27 req/s

### Latencia (P95)
- 50 concurrent: ~2.2s
- 100 concurrent: ~5.0s
- 200 concurrent: ~7.1s

### Estabilidad
- Arquitectura de worker único para evitar race conditions
- Retry logic con exponential backoff
- Detección automática de corrupción del modelo
- Manejo robusto de errores

## 🔧 Solución de Problemas

### El contenedor no inicia

```bash
# Ver logs
docker logs oceano-api

# Verificar GPU
nvidia-smi

# Verificar NVIDIA Container Toolkit
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### Errores de ONNX Runtime

Si ves errores como "Integer overflow" o "Failed to allocate memory":

1. Verifica que `UVICORN_WORKERS=1` (CRÍTICO)
2. Verifica que `GPU_CONCURRENCY=1`
3. Reinicia el contenedor: `docker compose restart api`

### Búsquedas lentas

1. Aumenta `HNSW_EF` para mejor recall (pero más lento)
2. Reduce `HNSW_EF` para más velocidad (pero menos recall)
3. Verifica que la GPU esté siendo usada: `nvidia-smi`

### Base de datos vacía

```bash
# Verificar colección
curl http://localhost:9100/status

# Si vectors=0, necesitas ingestar imágenes
docker exec oceano-api python3 -m app.ingest --folder /ruta/imagenes
```

## 🛡️ Seguridad

### Recomendaciones para Producción

1. **Cambiar puertos**: No expongas el puerto 9100 directamente
2. **Usar HTTPS**: Coloca un reverse proxy (nginx/traefik) con SSL
3. **Autenticación**: Agrega autenticación a la API
4. **Rate limiting**: Limita requests por IP
5. **Firewall**: Restringe acceso a IPs conocidas

### Ejemplo con Nginx

```nginx
server {
    listen 443 ssl;
    server_name tu-dominio.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:9100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 📝 API Endpoints

### GET /
Interfaz web para búsquedas interactivas

### POST /search
Buscar rostros similares

**Request:**
```bash
curl -X POST -F "file=@imagen.jpg" http://localhost:9100/search
```

**Response:** HTML con resultados

### GET /health
Health check del sistema

**Response:**
```json
{
  "status": "healthy",
  "ready": true,
  "checks": {
    "model_loaded": true,
    "qdrant_healthy": true,
    "shutdown_initiated": false
  }
}
```

### GET /status
Estado de la colección Qdrant

**Response:**
```json
{
  "collection": "faces",
  "vectors": 1000000,
  "status": "green"
}
```

## 🤝 Contribuir

Las contribuciones son bienvenidas. Por favor:

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit tus cambios (`git commit -am 'Agregar nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Crea un Pull Request

## 📄 Licencia

Este proyecto está bajo la licencia MIT. Ver archivo `LICENSE` para más detalles.

## 🙏 Agradecimientos

- [InsightFace](https://github.com/deepinsight/insightface) - Modelo de reconocimiento facial
- [Qdrant](https://qdrant.tech/) - Base de datos vectorial
- [FastAPI](https://fastapi.tiangolo.com/) - Framework web

## 📧 Contacto

Para preguntas o soporte, abre un issue en GitHub.

---

**Nota:** Este sistema ha sido optimizado y validado exhaustivamente para entornos de producción con arquitectura robusta y manejo de errores.
