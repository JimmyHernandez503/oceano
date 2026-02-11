#!/bin/bash
# Script de verificación para la versión de producción

set -e

echo "============================================================"
echo "Verificación de Versión de Producción"
echo "============================================================"
echo ""

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# Función para verificar archivo
check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✓${NC} $1"
    else
        echo -e "${RED}✗${NC} $1 - FALTA"
        ERRORS=$((ERRORS + 1))
    fi
}

# Función para verificar directorio
check_dir() {
    if [ -d "$1" ]; then
        echo -e "${GREEN}✓${NC} $1/"
    else
        echo -e "${RED}✗${NC} $1/ - FALTA"
        ERRORS=$((ERRORS + 1))
    fi
}

# Función para verificar ejecutable
check_executable() {
    if [ -x "$1" ]; then
        echo -e "${GREEN}✓${NC} $1 (ejecutable)"
    else
        echo -e "${YELLOW}⚠${NC} $1 (no ejecutable)"
        chmod +x "$1" 2>/dev/null && echo -e "  ${GREEN}→${NC} Permisos corregidos"
    fi
}

echo "Verificando estructura de archivos..."
echo ""

# Documentación
echo "Documentación:"
check_file "README.md"
check_file "INSTALL.md"
check_file "FAQ.md"
check_file "CHANGELOG.md"
check_file "STRUCTURE.md"
check_file "RELEASE_NOTES.md"
check_file "GITHUB_READY.md"
check_file "LICENSE"
echo ""

# Infraestructura
echo "Infraestructura:"
check_file "Dockerfile"
check_file "docker-compose.yml"
check_file "entrypoint.sh"
check_file "quick-start.sh"
check_file "verify-release.sh"
echo ""

# Configuración
echo "Configuración:"
check_file ".gitignore"
check_file ".env.example"
echo ""

# Directorios
echo "Directorios:"
check_dir "app"
check_dir "app/app"
check_dir "app/app/static"
check_dir "app/app/templates"
check_dir "logs"
check_dir "state"
echo ""

# Código fuente
echo "Código fuente:"
check_file "app/requirements.txt"
check_file "app/app/__init__.py"
check_file "app/app/main.py"
check_file "app/app/embeddings.py"
check_file "app/app/ingest.py"
check_file "app/app/metrics.py"
check_file "app/app/templates/index.html"
check_file "app/app/static/style.css"
echo ""

# Verificar permisos de scripts
echo "Permisos de scripts:"
check_executable "entrypoint.sh"
check_executable "quick-start.sh"
check_executable "verify-release.sh"
echo ""

# Verificar que NO existan archivos de test
echo "Verificando ausencia de archivos de test..."
if ls test_*.py 2>/dev/null | grep -q .; then
    echo -e "${RED}✗${NC} Encontrados archivos test_*.py (deben eliminarse)"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✓${NC} Sin archivos de test"
fi
echo ""

# Verificar nombres de contenedores en docker-compose.yml
echo "Verificando nombres de contenedores..."
if grep -q "oceano-api" docker-compose.yml && \
   grep -q "oceano-qdrant" docker-compose.yml; then
    echo -e "${GREEN}✓${NC} Nombres de contenedores correctos"
else
    echo -e "${RED}✗${NC} Nombres de contenedores incorrectos"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Verificar que no haya referencias a 'infierno'
echo "Verificando referencias a nombres antiguos..."
if grep -r "infierno" . --exclude-dir=.git 2>/dev/null | grep -v "verify-release.sh" | grep -q .; then
    echo -e "${RED}✗${NC} Encontradas referencias a 'infierno'"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✓${NC} Sin referencias a nombres antiguos"
fi
echo ""

# Resumen
echo "============================================================"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ VERIFICACIÓN EXITOSA${NC}"
    echo "La versión está lista para GitHub"
else
    echo -e "${RED}❌ VERIFICACIÓN FALLIDA${NC}"
    echo "Encontrados $ERRORS errores"
    exit 1
fi
echo "============================================================"
