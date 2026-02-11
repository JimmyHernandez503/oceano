import os
import asyncio
import time
import signal
import sys
from pathlib import Path
from typing import List, Dict, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from .embeddings import best_face_embedding, get_face_app

# -----------------------
# Configuración por entorno
# -----------------------

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("COLLECTION_NAME", "faces")
THUMBS_DIR = os.getenv("THUMBS_DIR", "/data/thumbs")

TOP_K = int(os.getenv("TOP_K", "10"))
SIM_THRESHOLD = float(os.getenv("SIM_THRESHOLD", "0.0"))
HNSW_EF = int(os.getenv("HNSW_EF", "512"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

# -----------------------
# Backpressure (evitar saturación GPU)
# -----------------------
GPU_CONCURRENCY = int(os.getenv("GPU_CONCURRENCY", "1"))  # 1 para evitar race conditions
GPU_ACQUIRE_TIMEOUT = float(os.getenv("GPU_ACQUIRE_TIMEOUT", "5.0"))
GPU_SEM = asyncio.Semaphore(GPU_CONCURRENCY)

# -----------------------
# Retry configuration
# -----------------------
MAX_EMBEDDING_RETRIES = 3
MAX_QDRANT_RETRIES = 3
RETRY_BASE_DELAY = 0.1  # 100ms base delay

# -----------------------
# Estado global
# -----------------------
_shutdown_event = asyncio.Event()
_model_loaded = False
_qdrant_healthy = False

async def _try_acquire_gpu(timeout: float = None) -> bool:
    """
    Intenta adquirir el semáforo de GPU con timeout.
    Si timeout es None, usa GPU_ACQUIRE_TIMEOUT del entorno.
    """
    if timeout is None:
        timeout = GPU_ACQUIRE_TIMEOUT
    try:
        await asyncio.wait_for(GPU_SEM.acquire(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False


# -----------------------
# App, estáticos y plantillas
# -----------------------

app = FastAPI(
    title="Oceano4 - Reconocimiento facial",
    description="API de reconocimiento facial con InsightFace + Qdrant",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Path(THUMBS_DIR).mkdir(parents=True, exist_ok=True)

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/thumbs", StaticFiles(directory=THUMBS_DIR), name="thumbs")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_client = QdrantClient(url=QDRANT_URL, timeout=600)


# -----------------------
# Startup & Shutdown Events
# -----------------------

@app.on_event("startup")
async def startup_event():
    """
    Pre-carga el modelo de InsightFace al iniciar el worker.
    Esto elimina cold starts y race conditions.
    """
    global _model_loaded, _qdrant_healthy
    
    print("=" * 80)
    print("🚀 INICIANDO WORKER")
    print("=" * 80)
    
    # 1. Pre-cargar modelo de InsightFace
    print("📦 Cargando modelo InsightFace...")
    try:
        start = time.perf_counter()
        model = get_face_app()
        elapsed = time.perf_counter() - start
        _model_loaded = True
        print(f"✅ Modelo cargado en {elapsed:.2f}s")
    except Exception as e:
        print(f"❌ Error cargando modelo: {e}")
        _model_loaded = False
    
    # 2. Verificar conexión con Qdrant
    print("🔌 Verificando conexión con Qdrant...")
    try:
        info = _client.get_collection(COLLECTION)
        count = _client.count(COLLECTION, exact=False).count
        _qdrant_healthy = True
        print(f"✅ Qdrant conectado: {count:,} vectores en colección '{COLLECTION}'")
    except Exception as e:
        print(f"❌ Error conectando a Qdrant: {e}")
        _qdrant_healthy = False
    
    print("=" * 80)
    print(f"✅ WORKER LISTO - Modelo: {_model_loaded} | Qdrant: {_qdrant_healthy}")
    print("=" * 80)
    print()


@app.on_event("shutdown")
async def shutdown_event():
    """
    Graceful shutdown: espera a que terminen las requests en curso.
    """
    global _shutdown_event
    
    print()
    print("=" * 80)
    print("🛑 APAGANDO WORKER")
    print("=" * 80)
    
    _shutdown_event.set()
    
    # Dar tiempo a requests en curso para terminar
    print("⏳ Esperando 5s para que terminen requests en curso...")
    await asyncio.sleep(5)
    
    print("✅ Worker apagado correctamente")
    print("=" * 80)


# Signal handlers para graceful shutdown
def handle_sigterm(signum, frame):
    """Handler para SIGTERM (docker stop)"""
    print("\n⚠️  SIGTERM recibido, iniciando graceful shutdown...")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)


# -----------------------
# Middleware de Timeout
# -----------------------

@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    """
    Middleware que aplica timeout global a todas las requests.
    """
    try:
        return await asyncio.wait_for(
            call_next(request),
            timeout=REQUEST_TIMEOUT
        )
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"error": f"Request timeout después de {REQUEST_TIMEOUT}s"}
        )


# -----------------------
# Endpoints
# -----------------------

@app.get("/healthz")
def healthz():
    """Health check básico - siempre responde OK si el proceso está vivo"""
    return {"ok": True}


@app.get("/health")
def health():
    """
    Health check inteligente - verifica que el worker esté completamente listo.
    Usado por load balancers para saber cuándo enviar tráfico.
    """
    global _model_loaded, _qdrant_healthy
    
    checks = {
        "model_loaded": _model_loaded,
        "qdrant_healthy": _qdrant_healthy,
        "shutdown_initiated": _shutdown_event.is_set()
    }
    
    # Worker está listo si modelo cargado, Qdrant OK, y no está apagándose
    ready = _model_loaded and _qdrant_healthy and not _shutdown_event.is_set()
    
    status_code = 200 if ready else 503
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if ready else "unhealthy",
            "ready": ready,
            "checks": checks
        }
    )


@app.get("/warmup")
def warmup():
    """
    Endpoint legacy para compatibilidad.
    El modelo ahora se pre-carga en startup, no es necesario llamar esto.
    """
    return {
        "status": "warm" if _model_loaded else "cold",
        "model": "antelopev2",
        "loaded": _model_loaded,
        "note": "Model is now pre-loaded on startup"
    }


@app.get("/status")
def status():
    try:
        c = _client.get_collection(COLLECTION)
        count = _client.count(COLLECTION, exact=False).count
        return {"collection": COLLECTION, "vectors": count, "status": c.status.value}
    except Exception as e:
        return {"error": str(e)}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "items": [],
            "error": None,
        },
    )


@app.post("/search", response_class=HTMLResponse)
async def search(request: Request, file: UploadFile = File(...)):
    data = await file.read()
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img is None:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "items": [],
                "error": "No se pudo decodificar la imagen.",
            },
        )

    # Embedding de la consulta con retry logic robusto
    t0 = time.perf_counter()
    
    # Adquirir GPU con timeout
    ok = await _try_acquire_gpu(timeout=GPU_ACQUIRE_TIMEOUT)
    if not ok:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "items": [], "error": "Servidor ocupado (GPU saturada). Reintenta en unos segundos."},
        )
    
    # Retry logic para embedding con exponential backoff
    out = None
    last_error = None
    
    for attempt in range(MAX_EMBEDDING_RETRIES):
        try:
            out = await asyncio.to_thread(best_face_embedding, img)
            break  # Éxito, salir del loop
        except Exception as e:
            last_error = e
            error_msg = str(e)
            print(f"[ERROR] Face embedding attempt {attempt + 1}/{MAX_EMBEDDING_RETRIES} failed: {error_msg}")
            
            # Si es un error de ONNX Runtime, esperar más tiempo antes de reintentar
            if any(keyword in error_msg for keyword in ["Integer overflow", "Failed to allocate", "RUNTIME_EXCEPTION"]):
                if attempt < MAX_EMBEDDING_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)  # Exponential backoff
                    print(f"[RETRY] Esperando {delay:.2f}s antes de reintentar...")
                    await asyncio.sleep(delay)
            else:
                # Para otros errores, fallar inmediatamente
                break
    
    GPU_SEM.release()

    if out is None:
        error_detail = f"Error procesando imagen: {str(last_error)}" if last_error else "No se detectó rostro en la imagen cargada."
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "items": [],
                "error": error_detail,
            },
        )

    emb, _bbox = out

    # Búsqueda en Qdrant con retry logic
    res = None
    
    for attempt in range(MAX_QDRANT_RETRIES):
        try:
            res = await asyncio.to_thread(_client.search,
                collection_name=COLLECTION,
                query_vector=emb.tolist(),
                limit=TOP_K,
                with_payload=["dui", "path", "thumb_id"],
                search_params=qmodels.SearchParams(
                    hnsw_ef=HNSW_EF,
                    exact=False,
                ),
            )
            break  # Éxito, salir del loop
        except Exception as e:
            print(f"[ERROR] Qdrant search attempt {attempt + 1}/{MAX_QDRANT_RETRIES} failed: {e}")
            if attempt < MAX_QDRANT_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)
            else:
                return templates.TemplateResponse(
                    "index.html",
                    {
                        "request": request,
                        "items": [],
                        "error": f"Error consultando Qdrant después de {MAX_QDRANT_RETRIES} intentos: {e}",
                    },
                )

    items: List[Dict] = []
    for p in res:
        score = float(p.score)

        # SIM_THRESHOLD=0.0 => siempre pasa, pero lo dejamos por si luego quieres usarlo
        if score < SIM_THRESHOLD:
            continue

        pid = str(p.id)
        payload = p.payload or {}
        dui = payload.get("dui", "")
        path = payload.get("path", "")
        thumb_id = payload.get("thumb_id", pid)

        percent = round(score * 100.0, 2)
        thumb_path = Path(THUMBS_DIR, f"{thumb_id}.jpg")
        thumb: Optional[str] = None
        if thumb_path.exists():
            thumb = f"/thumbs/{thumb_id}.jpg"

        items.append(
            {
                "percent": percent,
                "dui": dui,
                "path": path,
                "pid": pid,
                "thumb": thumb,
            }
        )

    elapsed = time.perf_counter() - t0
    print(f"[search] dt={elapsed:.3f}s hits={len(items)}")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "items": items,
            "error": None,
        },
    )
