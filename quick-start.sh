#!/bin/bash
# Script de inicio rápido para el sistema de reconocimiento facial

set -e

echo "============================================================"
echo "Oceano - Sistema de Reconocimiento Facial"
echo "============================================================"
echo ""

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verificar Docker
echo "Verificando Docker..."
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker no está instalado${NC}"
    echo "Por favor instala Docker: https://docs.docker.com/get-docker/"
    exit 1
fi
echo -e "${GREEN}✓ Docker instalado${NC}"

# Verificar Docker Compose
echo "Verificando Docker Compose..."
if ! docker compose version &> /dev/null; then
    echo -e "${RED}✗ Docker Compose no está instalado${NC}"
    echo "Por favor instala Docker Compose"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose instalado${NC}"

# Verificar NVIDIA GPU
echo "Verificando GPU NVIDIA..."
if ! command -v nvidia-smi &> /dev/null; then
    echo -e "${YELLOW}⚠ nvidia-smi no encontrado${NC}"
    echo "El sistema funcionará pero sin aceleración GPU"
else
    echo -e "${GREEN}✓ GPU NVIDIA detectada${NC}"
    nvidia-smi --query-gpu=name --format=csv,noheader
fi

# Crear directorios necesarios
echo ""
echo "Creando directorios..."
mkdir -p logs state thumbs models qdrant_storage
echo -e "${GREEN}✓ Directorios creados${NC}"

# Verificar si ya hay contenedores corriendo
if docker ps | grep -q "oceano"; then
    echo ""
    echo -e "${YELLOW}⚠ Contenedores ya están corriendo${NC}"
    read -p "¿Deseas reiniciarlos? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Deteniendo contenedores..."
        docker compose down
    else
        echo "Manteniendo contenedores actuales"
        exit 0
    fi
fi

# Construir e iniciar
echo ""
echo "Construyendo imágenes Docker..."
docker compose build

echo ""
echo "Iniciando servicios..."
docker compose up -d

echo ""
echo "Esperando a que los servicios estén listos..."
echo "(Esto puede tomar ~30 segundos mientras se carga el modelo)"

# Esperar a que la API esté lista
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s http://localhost:9100/health > /dev/null 2>&1; then
        HEALTH=$(curl -s http://localhost:9100/health | grep -o '"ready":true' || echo "")
        if [ ! -z "$HEALTH" ]; then
            echo -e "${GREEN}✓ API lista${NC}"
            break
        fi
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo -n "."
    sleep 1
done

echo ""

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo -e "${RED}✗ Timeout esperando a que la API esté lista${NC}"
    echo "Revisa los logs: docker compose logs api"
    exit 1
fi

# Verificar Qdrant
echo "Verificando Qdrant..."
if curl -s http://localhost:9101/collections > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Qdrant listo${NC}"
else
    echo -e "${RED}✗ Qdrant no responde${NC}"
    exit 1
fi

# Resumen
echo ""
echo "============================================================"
echo -e "${GREEN}✅ Sistema iniciado correctamente${NC}"
echo "============================================================"
echo ""
echo "URLs disponibles:"
echo "  - Interfaz Web:  http://localhost:9100"
echo "  - API Health:    http://localhost:9100/health"
echo "  - API Status:    http://localhost:9100/status"
echo "  - Qdrant UI:     http://localhost:9101/dashboard"
echo ""
echo "Comandos útiles:"
echo "  - Ver logs:      docker compose logs -f"
echo "  - Detener:       docker compose down"
echo "  - Reiniciar:     docker compose restart"
echo ""
echo "Para ingestar imágenes:"
echo "  docker exec oceano-api python3 -m app.ingest \\"
echo "    --folder /ruta/a/imagenes \\"
echo "    --collection faces \\"
echo "    --batch-size 100"
echo ""
echo "============================================================"
