import os
from typing import Optional, Tuple
import threading
import time

import cv2
import numpy as np
from insightface.app import FaceAnalysis

# Modelo global cacheado
_MODEL: Optional[FaceAnalysis] = None
_MODEL_LOCK = threading.Lock()  # Lock para inicialización thread-safe
_MODEL_LOAD_TIME: Optional[float] = None
_MODEL_CORRUPTED = False  # Flag para detectar corrupción


def _parse_det_size(val: str) -> Tuple[int, int]:
    """
    Parsea DET_SIZE desde el entorno con formato "ancho,alto".
    """
    try:
        a, b = val.split(",")
        return int(a), int(b)
    except Exception:
        return 640, 640


def get_face_app() -> FaceAnalysis:
    """
    Inicializa y devuelve el objeto FaceAnalysis (InsightFace).
    Thread-safe: usa un lock para evitar inicializaciones concurrentes.

    - Usa MODEL_NAME (por defecto: antelopev2)
    - Usa DET_SIZE (por defecto: 640,640)
    - Usa /models como root por defecto para descargar los packs.
    
    CRÍTICO: Detecta si el modelo está corrupto y lo recarga si es necesario.
    """
    global _MODEL, _MODEL_CORRUPTED, _MODEL_LOAD_TIME
    
    # Si el modelo está corrupto, forzar recarga
    if _MODEL_CORRUPTED:
        print("[WARNING] Modelo detectado como corrupto, forzando recarga...")
        with _MODEL_LOCK:
            _MODEL = None
            _MODEL_CORRUPTED = False
    
    # Fast path: si ya está inicializado, retornar inmediatamente
    if _MODEL is not None:
        return _MODEL
    
    # Slow path: inicializar con lock para evitar race conditions
    with _MODEL_LOCK:
        # Double-check: otro thread pudo haberlo inicializado mientras esperábamos el lock
        if _MODEL is not None:
            return _MODEL
        
        print("[INFO] Inicializando modelo InsightFace...")
        start_time = time.time()
        
        try:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            root = os.environ.get("INSIGHTFACE_MODELS", "/models")
            model_name = os.environ.get("MODEL_NAME", "antelopev2")
            det_size = _parse_det_size(os.environ.get("DET_SIZE", "640,640"))

            app = FaceAnalysis(name=model_name, root=root, providers=providers)
            app.prepare(ctx_id=0, det_size=det_size)
            
            _MODEL = app
            _MODEL_LOAD_TIME = time.time() - start_time
            
            print(f"[SUCCESS] Modelo cargado en {_MODEL_LOAD_TIME:.2f}s")
            return _MODEL
            
        except Exception as e:
            print(f"[ERROR] Fallo al cargar modelo: {e}")
            _MODEL_CORRUPTED = True
            raise


def _get_resize_params() -> Tuple[int, int]:
    """
    Lee MAX_SIDE y DOWNSCALE_TO. Si no están, usa 1600 / 1280.
    """
    try:
        max_side = int(os.environ.get("MAX_SIDE", "1600"))
        down_to = int(os.environ.get("DOWNSCALE_TO", "1280"))
    except Exception:
        max_side = 1600
        down_to = 1280
    return max_side, down_to


def read_image(path: str) -> Optional[np.ndarray]:
    """
    Lee una imagen desde disco (BGR) y la reescala si es muy grande.
    Usa imdecode(np.fromfile(...)) para soportar paths con Unicode.
    """
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        img = None

    if img is None:
        return None

    max_side, down_to = _get_resize_params()
    h, w = img.shape[:2]
    m = max(h, w)
    if m > max_side:
        scale = down_to / float(m)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    return img


def _orig_best_face_embedding(img_bgr: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    Devuelve (embedding_512, bbox) del rostro más grande en la imagen, o None si no hay rostros.
    
    CRÍTICO: Maneja errores de ONNX Runtime y marca el modelo como corrupto si es necesario.
    """
    global _MODEL_CORRUPTED
    
    try:
        app = get_face_app()
        faces = app.get(img_bgr)
        
        if not faces:
            return None

        # Ordenar por área del bounding box (rostro más grande primero)
        faces.sort(
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
            reverse=True,
        )
        f = faces[0]
        emb = f.normed_embedding  # 512-D ya normalizado
        return emb.astype(np.float32), f.bbox
        
    except Exception as e:
        error_msg = str(e)
        
        # Detectar errores críticos de ONNX Runtime que indican corrupción
        if any(keyword in error_msg for keyword in [
            "Integer overflow",
            "Failed to allocate memory",
            "RUNTIME_EXCEPTION",
            "FusedConv"
        ]):
            print(f"[CRITICAL] ONNX Runtime error detectado - marcando modelo como corrupto: {error_msg}")
            _MODEL_CORRUPTED = True
        
        raise


def embed_path(path: str) -> Optional[np.ndarray]:
    """
    Helper para ingesta: lee la imagen de disco, calcula el embedding del mejor rostro
    y devuelve únicamente el vector 512-D (o None si falla).
    """
    img = read_image(path)
    if img is None:
        return None
    out = best_face_embedding(img)
    if out is None:
        return None
    emb, _ = out
    return emb


def embed_path_fast(path: str) -> Optional[np.ndarray]:
    """
    Versión optimizada para ingesta masiva: sin fallbacks, solo un intento.
    Mucho más rápido que embed_path() pero puede fallar en imágenes difíciles.
    """
    img = read_image(path)
    if img is None:
        return None
    
    # Un solo intento, sin fallbacks
    result = _orig_best_face_embedding(img)
    if result is None:
        return None
    
    emb, _ = result
    return emb

def best_face_embedding(img):
    """Wrapper con fallback para recortes muy agresivos.

    Flujo:
      1) Llama a _orig_best_face_embedding(img).
      2) Si no detecta rostro, rellena con bordes negros (canvas más grande) y reintenta.
      3) Si aún así falla, hace un recorte central un poco más grande y reintenta.
    """
    import numpy as np
    import cv2

    # 1) Intento normal con el código original
    emb = _orig_best_face_embedding(img)
    if emb is not None:
        return emb

    # 2) Fallback: rellenar con bordes negros para "des-recortar" un poco
    try:
        h, w = img.shape[:2]
    except Exception:
        return None

    if h < 1 or w < 1:
        return None

    size = max(h, w)
    margin = int(size * 0.35)
    new_h = h + 2 * margin
    new_w = w + 2 * margin

    import numpy as np  # por si acaso
    padded = np.zeros((new_h, new_w, 3), dtype=img.dtype)
    padded[margin:margin + h, margin:margin + w] = img

    emb = _orig_best_face_embedding(padded)
    if emb is not None:
        return emb

    # 3) Último intento: recorte central un poco más grande
    scale = 1.4
    side = int(min(h, w) * scale)
    cy, cx = h // 2, w // 2
    y1 = max(0, cy - side // 2)
    y2 = min(h, cy + side // 2)
    x1 = max(0, cx - side // 2)
    x2 = min(w, cx + side // 2)

    if y2 <= y1 or x2 <= x1:
        return None

    crop = img[y1:y2, x1:x2].copy()
    emb = _orig_best_face_embedding(crop)
    return emb
