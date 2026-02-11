# Preguntas Frecuentes (FAQ)

## General

### ¿Qué es este sistema?

Es un sistema de reconocimiento facial que permite buscar rostros similares en una base de datos de imágenes. Utiliza InsightFace para extraer características faciales y Qdrant para búsqueda vectorial rápida.

### ¿Es gratuito?

Sí, el código es open source bajo licencia MIT. Puedes usarlo, modificarlo y distribuirlo libremente.

### ¿Necesito GPU?

Sí, se recomienda una GPU NVIDIA con soporte CUDA para buen rendimiento. El sistema puede funcionar en CPU pero será mucho más lento.

## Instalación

### ¿Qué GPU necesito?

Recomendamos:
- Mínimo: GTX 1080 Ti (11GB VRAM)
- Recomendado: RTX 3090 (24GB VRAM) o RTX 4090 (24GB VRAM)
- Para producción: A100 (40GB/80GB VRAM)

### ¿Funciona en Windows?

El sistema está diseñado para Linux. Para Windows, recomendamos usar WSL2 (Windows Subsystem for Linux) con soporte GPU.

### ¿Funciona en macOS?

macOS no tiene soporte CUDA, por lo que el rendimiento será limitado. Puedes ejecutarlo en CPU pero será lento.

### ¿Cuánto espacio en disco necesito?

- Sistema base: ~10 GB
- Modelos: ~500 MB
- Por cada millón de vectores: ~2-3 GB (con cuantización)
- Imágenes originales: depende de tu colección

## Uso

### ¿Cómo agrego imágenes?

```bash
docker exec oceano-api python3 -m app.ingest \
  --folder /ruta/a/imagenes \
  --collection faces \
  --batch-size 100
```

### ¿Qué formatos de imagen soporta?

JPG, JPEG, PNG, BMP, TIFF. El sistema redimensiona automáticamente imágenes grandes.

### ¿Cuántas imágenes puedo procesar?

El sistema ha sido probado con millones de imágenes. El límite depende de tu hardware:
- RAM: ~2-3 GB por millón de vectores
- Disco: ~2-3 GB por millón de vectores (con cuantización)

### ¿Qué tan rápido es?

- Ingesta: ~5-10 imágenes/segundo (depende de GPU)
- Búsqueda: ~15-27 requests/segundo
- Latencia: 1-7 segundos (depende de concurrencia)

### ¿Puedo buscar múltiples rostros en una imagen?

Actualmente el sistema busca el rostro más grande en la imagen. Para múltiples rostros, necesitarías modificar el código.

## Performance

### ¿Por qué solo 1 worker?

El modelo InsightFace NO es thread-safe entre procesos. Múltiples workers causan race conditions y corrupción de memoria. 1 worker con alta concurrencia asíncrona es más estable y confiable.

### ¿Cómo mejoro el rendimiento?

1. Usa una GPU más potente
2. Aumenta `UVICORN_LIMIT_CONCURRENCY` (default: 256)
3. Ajusta `HNSW_EF` (menor = más rápido, mayor = más preciso)
4. Usa cuantización escalar (ya habilitada por defecto)

### ¿Por qué las búsquedas son lentas?

Posibles causas:
- GPU no está siendo usada (verifica con `nvidia-smi`)
- `HNSW_EF` muy alto (reduce a 256 o 128)
- Colección muy grande sin optimizar
- Múltiples requests concurrentes

### ¿Cómo optimizo para millones de vectores?

1. Habilita cuantización escalar (ya habilitada)
2. Ajusta `indexing_threshold` en Qdrant
3. Aumenta RAM disponible para Qdrant
4. Usa SSD rápido para almacenamiento

## Problemas Comunes

### Error: "Integer overflow" o "Failed to allocate memory"

Esto indica que tienes múltiples workers. Verifica que `UVICORN_WORKERS=1` en `docker-compose.yml`.

### Error: "CUDA out of memory"

Reduce el batch size en ingesta:
```bash
--batch-size 50  # En lugar de 100
```

### Las búsquedas no devuelven resultados

Posibles causas:
1. Base de datos vacía - Ingesta imágenes primero
2. `SIM_THRESHOLD` muy alto - Reduce a 0.0
3. Imagen de búsqueda sin rostro - Verifica que tenga un rostro claro

### El contenedor se reinicia constantemente

Revisa los logs:
```bash
docker compose logs api
```

Causas comunes:
- GPU no disponible
- Memoria insuficiente
- Modelo no se puede descargar

### ¿Cómo veo los logs?

```bash
# Todos los servicios
docker compose logs -f

# Solo API
docker compose logs -f api

# Solo Qdrant
docker compose logs -f qdrant
```

## Seguridad

### ¿Es seguro para producción?

El código es seguro, pero debes:
1. Usar HTTPS (reverse proxy con SSL)
2. Agregar autenticación
3. Implementar rate limiting
4. Restringir acceso por IP
5. Mantener Docker actualizado

### ¿Cómo agrego autenticación?

Puedes usar:
- API Keys en headers
- OAuth2 con FastAPI
- Reverse proxy con autenticación (nginx, traefik)

### ¿Los datos están encriptados?

Los vectores en Qdrant no están encriptados por defecto. Para encriptar:
1. Usa volúmenes encriptados
2. Encripta el disco completo
3. Usa Qdrant Cloud con encriptación

## Desarrollo

### ¿Cómo contribuyo?

1. Fork el repositorio
2. Crea una rama para tu feature
3. Haz commit de tus cambios
4. Crea un Pull Request

### ¿Cómo reporto un bug?

Abre un issue en GitHub con:
- Descripción del problema
- Pasos para reproducir
- Logs relevantes
- Versión del sistema

### ¿Puedo usar otro modelo de reconocimiento facial?

Sí, pero necesitarás modificar `app/embeddings.py`. InsightFace soporta varios modelos.

### ¿Puedo usar otra base de datos vectorial?

Sí, pero necesitarás modificar `app/main.py`. Alternativas: Milvus, Weaviate, Pinecone.

## Licencia

### ¿Puedo usar esto comercialmente?

Sí, la licencia MIT permite uso comercial.

### ¿Debo dar crédito?

No es obligatorio, pero es apreciado. Incluye un enlace al repositorio original.

### ¿Puedo vender este software?

Sí, puedes vender software basado en este código bajo los términos de la licencia MIT.

## Soporte

### ¿Dónde obtengo ayuda?

1. Lee la documentación: `README.md`, `INSTALL.md`
2. Revisa las FAQ (este archivo)
3. Busca en issues cerrados de GitHub
4. Abre un nuevo issue en GitHub

### ¿Ofrecen soporte comercial?

Este es un proyecto open source sin soporte comercial oficial. Para soporte profesional, considera contratar a un desarrollador.

### ¿Hay una comunidad?

Puedes interactuar a través de:
- GitHub Issues
- GitHub Discussions (si está habilitado)
- Pull Requests

---

¿No encuentras tu pregunta? Abre un issue en GitHub.
