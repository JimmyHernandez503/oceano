# Guía de Instalación Detallada

## Requisitos Previos

### 1. Instalar Docker

#### Ubuntu/Debian
```bash
# Actualizar paquetes
sudo apt-get update

# Instalar dependencias
sudo apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Agregar repositorio de Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Instalar Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Agregar usuario al grupo docker
sudo usermod -aG docker $USER

# Reiniciar sesión para aplicar cambios
```

### 2. Instalar NVIDIA Container Toolkit

```bash
# Agregar repositorio
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# Instalar
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Reiniciar Docker
sudo systemctl restart docker

# Verificar instalación
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

## Instalación del Sistema

### 1. Clonar Repositorio

```bash
git clone https://github.com/tu-usuario/oceano.git
cd oceano
```

### 2. Crear Directorios

```bash
mkdir -p logs state thumbs models qdrant_storage
```

### 3. Configurar Permisos

```bash
chmod -R 755 logs state thumbs models qdrant_storage
```

### 4. Configurar Variables de Entorno (Opcional)

Crea un archivo `.env` si necesitas personalizar la configuración:

```bash
cat > .env << 'EOF'
# Puertos
API_PORT=9100
QDRANT_PORT=9101
QDRANT_GRPC_PORT=9102

# Colección
COLLECTION_NAME=faces

# Modelo
MODEL_NAME=antelopev2
DET_SIZE=640,640

# Búsqueda
TOP_K=10
HNSW_EF=512
EOF
```

### 5. Construir e Iniciar

```bash
# Construir imágenes
docker compose build

# Iniciar servicios
docker compose up -d

# Ver logs
docker compose logs -f
```

### 6. Verificar Instalación

```bash
# Esperar ~30 segundos para que cargue el modelo
sleep 30

# Health check
curl http://localhost:9100/health

# Debería responder:
# {
#   "status": "healthy",
#   "ready": true,
#   "checks": {
#     "model_loaded": true,
#     "qdrant_healthy": true,
#     "shutdown_initiated": false
#   }
# }
```

## Configuración Inicial

### 1. Crear Colección en Qdrant

La colección se crea automáticamente en la primera ingesta. Alternativamente, créala manualmente:

```bash
curl -X PUT http://localhost:9101/collections/faces \
  -H 'Content-Type: application/json' \
  -d '{
    "vectors": {
      "size": 512,
      "distance": "Cosine"
    },
    "optimizers_config": {
      "indexing_threshold": 10000
    },
    "hnsw_config": {
      "m": 16,
      "ef_construct": 100
    },
    "quantization_config": {
      "scalar": {
        "type": "int8",
        "quantile": 0.99,
        "always_ram": true
      }
    }
  }'
```

### 2. Ingestar Imágenes

```bash
# Preparar imágenes
mkdir -p imagenes
# Copiar tus imágenes a la carpeta imagenes/

# Ingestar
docker exec oceano-api python3 -m app.ingest \
  --folder /app/imagenes \
  --collection faces \
  --batch-size 100 \
  --workers 4
```

### 3. Verificar Ingesta

```bash
# Ver estado
curl http://localhost:9100/status

# Debería mostrar el número de vectores ingresados
```

## Actualización

### Actualizar el Sistema

```bash
# Detener servicios
docker compose down

# Actualizar código
git pull

# Reconstruir
docker compose build

# Reiniciar
docker compose up -d
```

### Actualizar Solo la API

```bash
docker compose up -d --build api
```

### Actualizar Solo Qdrant

```bash
docker compose up -d --build qdrant
```

## Backup y Restauración

### Backup de Qdrant

```bash
# Detener Qdrant
docker compose stop qdrant

# Hacer backup
tar -czf qdrant_backup_$(date +%Y%m%d).tar.gz qdrant_storage/

# Reiniciar Qdrant
docker compose start qdrant
```

### Restaurar Qdrant

```bash
# Detener Qdrant
docker compose stop qdrant

# Restaurar
tar -xzf qdrant_backup_YYYYMMDD.tar.gz

# Reiniciar Qdrant
docker compose start qdrant
```

### Backup de Base de Datos SQLite

```bash
cp state/ingestion.db state/ingestion_backup_$(date +%Y%m%d).db
```

## Desinstalación

### Detener y Eliminar Contenedores

```bash
docker compose down
```

### Eliminar Volúmenes (CUIDADO: Elimina todos los datos)

```bash
docker compose down -v
rm -rf logs state thumbs models qdrant_storage
```

### Eliminar Imágenes Docker

```bash
docker rmi oceano-api
docker rmi qdrant/qdrant:v1.12.0
```

## Solución de Problemas Comunes

### Error: "Cannot connect to Docker daemon"

```bash
# Verificar que Docker esté corriendo
sudo systemctl status docker

# Iniciar Docker si está detenido
sudo systemctl start docker

# Verificar permisos
sudo usermod -aG docker $USER
# Cerrar sesión y volver a iniciar
```

### Error: "nvidia-smi not found"

```bash
# Instalar drivers NVIDIA
sudo ubuntu-drivers autoinstall
sudo reboot

# Verificar instalación
nvidia-smi
```

### Error: "CUDA out of memory"

Reduce el batch size en la ingesta:

```bash
docker exec oceano-api python3 -m app.ingest \
  --folder /app/imagenes \
  --batch-size 50  # Reducido de 100 a 50
```

### Puerto ya en uso

Cambia los puertos en `docker-compose.yml`:

```yaml
ports:
  - "9200:7860"  # Cambiar 9100 a 9200
```

## Monitoreo

### Ver Logs en Tiempo Real

```bash
# Todos los servicios
docker compose logs -f

# Solo API
docker compose logs -f api

# Solo Qdrant
docker compose logs -f qdrant
```

### Monitorear Recursos

```bash
# CPU y memoria
docker stats

# GPU
nvidia-smi -l 1
```

### Métricas de Qdrant

```bash
# Métricas Prometheus
curl http://localhost:9101/metrics

# Telemetría
curl http://localhost:9101/telemetry
```

## Soporte

Si encuentras problemas durante la instalación:

1. Revisa los logs: `docker compose logs`
2. Verifica requisitos: GPU, Docker, NVIDIA Toolkit
3. Consulta la documentación: `README.md`
4. Abre un issue en GitHub con los logs completos
