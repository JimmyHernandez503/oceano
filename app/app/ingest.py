import os
import time
import sqlite3
import argparse
import uuid
from pathlib import Path
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from threading import Thread

from PIL import Image
from rich import print as rprint
from tqdm import tqdm

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    VectorParams,
    Distance,
    PointStruct,
    OptimizersConfigDiff,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    HnswConfigDiff,
)

from .embeddings import read_image, best_face_embedding, embed_path_fast, get_face_app

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("COLLECTION_NAME", "faces")
SQLITE_DB = os.getenv("SQLITE_DB", "/state/ingestion.db")
THUMBS_DIR = os.getenv("THUMBS_DIR", "/data/thumbs")
QUANTIZATION = os.getenv("QUANTIZATION", "none").lower()  # none | scalar

# CSV para registrar errores de ingesta (ruta completa + causa)
ERROR_CSV = os.getenv(
    "ERROR_CSV",
    str(Path(SQLITE_DB).parent / "ingest_errors.csv"),
)


def ensure_sqlite():
    Path(SQLITE_DB).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_DB)
    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS files (
      path TEXT PRIMARY KEY,
      mtime REAL NOT NULL,
      status TEXT NOT NULL,
      point_id TEXT,
      error TEXT
    )
    """
    )
    conn.commit()
    return conn


def append_error_csv(path: str, cause: str):
    """Guarda en un CSV la ruta completa de la imagen con error y la causa.

    Formato: timestamp, path, cause
    """
    try:
        csv_path = Path(ERROR_CSV)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not csv_path.exists()
        with csv_path.open("a", newline="", encoding="utf-8") as f:
            import csv

            writer = csv.writer(f)
            if new_file:
                writer.writerow(["timestamp", "path", "cause"])
            writer.writerow(
                [time.strftime("%Y-%m-%d %H:%M:%S"), path, cause]
            )
    except Exception as e:
        # No abortar la ingesta por errores al escribir el CSV
        rprint(f"[red]No pude escribir en CSV de errores para {path}: {e}[/red]")


def sha1_of(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def is_image(p: Path) -> bool:
    return p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def get_dui_from_name(p: Path) -> Optional[str]:
    # Por defecto usa el nombre de archivo (sin extensión) como DUI
    # Puedes adaptar este helper si tus nombres de archivo tienen otro patrón.
    return p.name.rsplit(".", 1)[0]


def ensure_collection(client: QdrantClient):
    if not client.collection_exists(collection_name=COLLECTION):
        rprint(f"[yellow]Creando colección '{COLLECTION}' en Qdrant…[/yellow]")

        # ============================================================================
        # CONFIGURACIÓN OPTIMIZADA PARA MILLONES DE VECTORES
        # ============================================================================
        # Esta configuración está diseñada para manejar millones de rostros en
        # hardware de alto rendimiento (RTX 4090, i9-13900K, 128GB RAM).
        # Los parámetros balancean velocidad de búsqueda, precisión (recall),
        # uso de memoria y throughput de ingesta.
        # ============================================================================

        # Configuración de Quantization (opcional, activada con QUANTIZATION=scalar)
        # ---------------------------------------------------------------------------
        # Scalar Quantization INT8 reduce el uso de memoria en ~4x al comprimir
        # vectores float32 (4 bytes) a int8 (1 byte) con pérdida mínima de precisión.
        # 
        # Parámetros:
        # - type=INT8: Compresión de 32 bits a 8 bits por componente
        # - quantile=0.99: Usa percentil 99 para calcular rangos de cuantización,
        #   preservando valores extremos y minimizando error de cuantización
        # - always_ram=False: Permite que vectores cuantizados se almacenen en disco
        #   cuando sea necesario, crucial para millones de vectores
        #
        # Justificación: Con millones de rostros (512-D float32 = 2KB por vector),
        # la memoria se agota rápidamente. INT8 permite 4x más vectores en RAM
        # con degradación de recall típicamente < 1%.
        quant_cfg = None
        if QUANTIZATION == "scalar":
            quant_cfg = ScalarQuantization(
                scalar=ScalarQuantizationConfig(
                    type=ScalarType.INT8,
                    quantile=0.99,
                    always_ram=False,
                )
            )

        client.recreate_collection(
            collection_name=COLLECTION,
            # Configuración de Vectores
            # -------------------------
            # - size=512: Dimensionalidad de embeddings de InsightFace (buffalo_l/antelopev2)
            # - distance=COSINE: Métrica de similitud estándar para embeddings faciales
            #   (equivalente a dot product con vectores normalizados)
            # - on_disk=True: CRÍTICO para millones de vectores. Usa memory-mapped files
            #   para almacenar vectores en disco y cargarlos bajo demanda. Sin esto,
            #   millones de vectores saturarían los 128GB de RAM disponibles.
            #
            # Justificación on_disk=True:
            # - 1M vectores × 512 dims × 4 bytes = 2GB (manejable en RAM)
            # - 10M vectores × 512 dims × 4 bytes = 20GB (aún manejable)
            # - 50M+ vectores × 512 dims × 4 bytes = 100GB+ (requiere disco)
            # Con on_disk=True, Qdrant usa memmap para acceso eficiente sin saturar RAM.
            vectors_config=VectorParams(
                size=512,
                distance=Distance.COSINE,
                on_disk=True,
            ),
            # Configuración de Optimizadores
            # -------------------------------
            # Controla cuándo Qdrant activa optimizaciones de memoria y construcción de índice.
            #
            # memmap_threshold=20000:
            # - Activa memory-mapped files cuando la colección supera 20,000 vectores
            # - Antes de este umbral, vectores se mantienen en RAM para máxima velocidad
            # - Después, se usa memmap para balance memoria/velocidad
            # - Justificación: 20K vectores = ~40MB, manejable en RAM. Más allá de esto,
            #   memmap previene saturación de memoria sin sacrificar mucho rendimiento.
            #
            # indexing_threshold=20000:
            # - Construye el índice HNSW después de acumular 20,000 vectores
            # - Antes de este umbral, usa búsqueda por fuerza bruta (más rápida para pocos vectores)
            # - Después, construye HNSW para búsquedas eficientes en millones de vectores
            # - Justificación: Construcción de HNSW es costosa. Para < 20K vectores,
            #   fuerza bruta es más rápida. Para > 20K, HNSW es esencial (O(log N) vs O(N)).
            optimizers_config=OptimizersConfigDiff(
                memmap_threshold=20000,
                indexing_threshold=20000,
            ),
            # Configuración HNSW (Hierarchical Navigable Small World)
            # ---------------------------------------------------------
            # HNSW es el algoritmo de indexación que permite búsquedas rápidas en
            # millones de vectores. Estos parámetros controlan el trade-off entre
            # velocidad de búsqueda, precisión (recall) y uso de memoria.
            #
            # m=32:
            # - Número de conexiones bidireccionales por nodo en el grafo HNSW
            # - Rango típico: 16-64. Valores más altos = mejor recall, más memoria
            # - m=32 es un balance óptimo para la mayoría de casos de uso
            # - Memoria por vector: ~m × 2 × 4 bytes = 256 bytes de overhead
            # - Para 10M vectores: 10M × 256 bytes = 2.5GB de overhead del grafo
            # - Justificación: m=16 es muy rápido pero recall puede degradarse en
            #   colecciones grandes. m=64 mejora recall marginalmente pero duplica
            #   memoria. m=32 ofrece excelente recall (>95%) con uso razonable de memoria.
            #
            # ef_construct=256:
            # - Tamaño de la lista de candidatos durante construcción del índice
            # - Rango típico: 100-500. Valores más altos = mejor calidad del grafo, construcción más lenta
            # - ef_construct=256 construye un grafo de alta calidad sin ser excesivamente lento
            # - Tiempo de construcción: ~2-3x más lento que ef_construct=100, pero grafo mucho mejor
            # - Justificación: La construcción del índice es un proceso de una sola vez (o incremental).
            #   Invertir más tiempo en construcción (ef_construct=256) resulta en búsquedas más
            #   rápidas y precisas durante toda la vida del índice. Para millones de vectores,
            #   la calidad del grafo es crítica para mantener recall alto.
            #
            # on_disk=False:
            # - CRÍTICO: Con 125GB RAM disponibles, mantener índice HNSW en RAM para máxima velocidad
            # - Para 6.3M vectores: ~1.6GB de overhead del grafo HNSW (manejable en RAM)
            # - Beneficio: Latencia de búsqueda ~2-3x más rápida que on_disk=True
            # - Trade-off: Usa más RAM pero tenemos 90GB disponibles (suficiente margen)
            # - Si la colección crece a 50M+ vectores, considerar on_disk=True
            #
            # Nota sobre hnsw_ef (parámetro de búsqueda):
            # - hnsw_ef NO se configura aquí (es parámetro de búsqueda, no de construcción)
            # - Se configura en docker-compose.yml como HNSW_EF=256
            # - hnsw_ef controla el trade-off velocidad/recall en cada búsqueda individual
            # - Valores típicos: 128-512. Más alto = mejor recall, búsquedas más lentas
            # - hnsw_ef=256 ofrece excelente recall (>98%) con latencia aceptable en RTX 4090
            hnsw_config=HnswConfigDiff(
                m=32,
                ef_construct=256,
                on_disk=False,  # Mantener en RAM para mínima latencia (tenemos 90GB disponibles)
            ),
            # on_disk_payload=True:
            # - Almacena payloads (metadata: dui, path, thumb_id) en disco
            # - Reduce uso de RAM, especialmente importante con millones de vectores
            # - Payloads se cargan bajo demanda cuando se retornan resultados
            # - Justificación: Payloads pueden ser grandes (paths largos, metadata adicional).
            #   Con millones de vectores, mantener payloads en RAM es innecesario ya que
            #   solo se acceden para los top-K resultados de cada búsqueda.
            on_disk_payload=True,
            quantization_config=quant_cfg,
        )
        rprint("[green]Colección creada.[/green]")
    else:
        rprint(f"[green]Colección '{COLLECTION}' OK.[/green]")
        # Si la colección ya existe pero activas QUANTIZATION=scalar más tarde,
        # actualizamos la config de quantization.
        if QUANTIZATION == "scalar":
            rprint("[yellow]Actualizando quantization de la colección a Scalar INT8…[/yellow]")
            client.update_collection(
                collection_name=COLLECTION,
                quantization_config=ScalarQuantization(
                    scalar=ScalarQuantizationConfig(
                        type=ScalarType.INT8,
                        quantile=0.99,
                        always_ram=False,
                    )
                ),
            )


def make_thumb(src_path: str, dst_path: str):
    try:
        im = Image.open(src_path).convert("RGB")
        im.thumbnail((160, 160))
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        im.save(dst_path, "JPEG", quality=85)
    except Exception:
        # No abortar ingesta por errores de thumbnail
        pass


def batch_upsert(
    client: QdrantClient, batch: List[Tuple[str, str, str, np.ndarray]]
):
    # batch: [(uuid_str, thumb_id, path, emb), ...]
    points = []
    for uid, thumb_id, path, emb in batch:
        dui = get_dui_from_name(Path(path)) or ""
        payload = {
            "dui": dui,
            "path": path,
            "thumb_id": thumb_id,
        }
        points.append(
            PointStruct(id=uid, vector=emb.tolist(), payload=payload)
        )
    client.upsert(collection_name=COLLECTION, points=points)


def process_image_worker(path: str) -> Optional[Tuple[str, np.ndarray]]:
    """
    Worker function: lee y procesa imagen con fallbacks para maximizar detección.
    Usa el modelo global compartido (un solo modelo en GPU).
    
    Args:
        path: Ruta de la imagen
    
    Returns:
        Tupla de (path, embedding) o None si falla
    """
    try:
        # Usar versión con fallbacks para maximizar detección
        img = read_image(path)
        if img is None:
            return None
        
        # Procesar con fallbacks (padding, crop)
        result = best_face_embedding(img)
        if result is None:
            return None
        
        emb, _ = result
        return (path, emb)
    except Exception:
        return None


def process_batch_parallel(
    paths: List[Path],
    conn: sqlite3.Connection,
    batch_size: int = 1024,
    num_workers: int = 32,
    resume: bool = True,
    pbar = None
) -> List[Tuple[str, str, str, np.ndarray]]:
    """
    Procesa un batch de imágenes con I/O paralelo + GPU secuencial optimizado.
    
    Optimizaciones:
    - ThreadPoolExecutor para I/O paralelo
    - Versión con fallbacks para maximizar detección
    - Commits de SQLite en batch (no por imagen)
    - Modelo global compartido (un solo modelo en GPU)
    - Actualización de progreso en tiempo real
    
    Args:
        paths: Lista de rutas de imágenes a procesar
        conn: Conexión SQLite para tracking de estado
        batch_size: Tamaño del batch
        num_workers: Número de threads para I/O paralelo
        resume: Si True, salta archivos ya procesados
        pbar: Barra de progreso tqdm (opcional)
    
    Returns:
        Lista de (uuid, thumb_id, path, embedding) para imágenes exitosas
    """
    cur = conn.cursor()
    
    # Preparar información de paths y filtrar ya procesados
    paths_to_process = []
    path_metadata = {}  # path -> (mtime, thumb_id, uid)
    
    for p in paths:
        path = str(p)
        mtime = p.stat().st_mtime
        thumb_id = sha1_of(f"{path}:{mtime}")
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path}:{mtime}"))
        
        # Si resume está activo, verificar si ya fue procesado
        if resume:
            row = cur.execute(
                "SELECT status FROM files WHERE path=?", (path,)
            ).fetchone()
            if row and row[0] == "done":
                if pbar:
                    pbar.update(1)
                continue
        
        paths_to_process.append(path)
        path_metadata[path] = (mtime, thumb_id, uid)
    
    if not paths_to_process:
        return []
    
    # Procesar en paralelo con ThreadPoolExecutor
    successful_batch = []
    errors_batch = []  # Acumular errores para commit en batch
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Enviar todas las tareas al pool de threads
        future_to_path = {
            executor.submit(process_image_worker, path): path
            for path in paths_to_process
        }
        
        # Recolectar resultados y actualizar progreso en tiempo real
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            
            try:
                result = future.result()
                
                if result is None:
                    # Error o no_face - acumular para batch insert
                    mtime, thumb_id, uid = path_metadata[path]
                    errors_batch.append((path, mtime, "no_face_or_error"))
                    append_error_csv(path, "no_face_or_error")
                else:
                    # Éxito
                    path_result, emb = result
                    mtime, thumb_id, uid = path_metadata[path_result]
                    
                    successful_batch.append((uid, thumb_id, path_result, emb))
                    
                    # Crear thumbnail si no existe (no bloquea)
                    thumb_path = os.path.join(THUMBS_DIR, f"{thumb_id}.jpg")
                    if not os.path.exists(thumb_path):
                        make_thumb(path_result, thumb_path)
                    
            except Exception as e:
                # Error inesperado - acumular para batch insert
                mtime, thumb_id, uid = path_metadata[path]
                cause = f"exception:{type(e).__name__}"
                errors_batch.append((path, mtime, cause))
                append_error_csv(path, cause)
            
            # Actualizar progreso en tiempo real
            if pbar:
                pbar.update(1)
    
    # Batch insert de errores (un solo commit)
    if errors_batch:
        cur.executemany(
            "REPLACE INTO files(path, mtime, status, point_id, error) VALUES (?,?,?,?,?)",
            [(path, mtime, "error", None, cause) for path, mtime, cause in errors_batch]
        )
    
    # Batch insert de éxitos como "pending" (un solo commit)
    if successful_batch:
        cur.executemany(
            "REPLACE INTO files(path, mtime, status, point_id, error) VALUES (?,?,?,?,?)",
            [(path, mtime, "pending", uid, None) for uid, _, path, _ in successful_batch]
        )
    
    conn.commit()
    return successful_batch


def scan_paths(root: str) -> List[Path]:
    p = Path(root)
    if p.is_file() and is_image(p):
        return [p]
    return [pp for pp in p.rglob("*") if pp.is_file() and is_image(pp)]


def process(root: str, batch_size: int = 1024, resume: bool = True, num_workers: Optional[int] = None):
    """
    Ingesta principal con procesamiento paralelo optimizado.
    
    Pipeline eficiente:
    - ThreadPoolExecutor para I/O paralelo (lectura/decodificación de imágenes)
    - GPU procesa secuencialmente con modelo global compartido (sin duplicación)
    - Mientras GPU procesa imagen N, threads preparan N+1, N+2, etc.
    
    Args:
        root: Directorio o archivo de imágenes
        batch_size: Tamaño del batch para upsert a Qdrant
        resume: Si True, continúa desde último punto
        num_workers: Número de threads para I/O paralelo (default: desde env o 16)
    
    Optimizaciones:
        - I/O paralelo con threads (no bloquea GPU)
        - Un solo modelo en GPU (eficiente en memoria)
        - Pipeline: I/O y GPU trabajan en paralelo
        - Batch upsert a Qdrant para maximizar throughput
    """
    # CRÍTICO: Inicializar modelo ANTES de crear threads
    # Esto asegura que solo se crea UNA instancia del modelo en GPU
    from .embeddings import get_face_app
    rprint("[yellow]Inicializando modelo en GPU...[/yellow]")
    get_face_app()  # Carga el modelo global _MODEL
    rprint("[green]Modelo cargado en GPU.[/green]")
    
    # Configurar num_workers desde variable de entorno si no se especifica
    # Usar más threads porque son para I/O (no CPU/GPU bound)
    if num_workers is None:
        num_workers = int(os.getenv("INGEST_NUM_WORKERS", "32"))
    
    client = QdrantClient(url=QDRANT_URL, timeout=600)
    ensure_collection(client)
    conn = ensure_sqlite()

    paths = scan_paths(root)
    rprint(f"[cyan]Archivos de imagen detectados en '{root}': {len(paths)}[/cyan]")
    rprint(f"[cyan]Usando {num_workers} threads para I/O paralelo (modelo único en GPU)[/cyan]")

    # Procesar en chunks para pipeline GPU/CPU
    # Threads manejan I/O en paralelo, GPU procesa secuencialmente
    total_processed = 0
    
    with tqdm(total=len(paths), desc="Ingestando", unit="img") as pbar:
        # Dividir paths en chunks del tamaño de batch
        for i in range(0, len(paths), batch_size):
            chunk = paths[i:i + batch_size]
            
            # Procesar chunk con threading (I/O paralelo + GPU secuencial)
            # Pasar pbar para actualización en tiempo real
            batch = process_batch_parallel(
                chunk, 
                conn, 
                batch_size=batch_size,
                num_workers=num_workers,
                resume=resume,
                pbar=pbar
            )
            
            # Upsert a Qdrant (GPU/red)
            if batch:
                batch_upsert(client, batch)
                
                # Marcar como done en SQLite
                cur = conn.cursor()
                for _, _, path_i, _ in batch:
                    cur.execute(
                        "UPDATE files SET status='done' WHERE path=?", (path_i,)
                    )
                conn.commit()
                
                total_processed += len(batch)

    rprint(f"[green]Ingesta finalizada. Procesadas exitosamente: {total_processed}/{len(paths)}[/green]")


def main():
    ap = argparse.ArgumentParser(
        description="Ingesta incremental (GPU embeddings + Qdrant, UUID IDs) con procesamiento paralelo"
    )
    ap.add_argument(
        "--path", required=True, help="Directorio o archivo de imágenes (recursivo)"
    )
    ap.add_argument(
        "--batch", type=int, default=1024, help="Tamaño de lote para upsert"
    )
    ap.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignorar estado y reprocesar todo",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Número de threads para I/O paralelo (default: INGEST_NUM_WORKERS env o 32)",
    )
    args = ap.parse_args()
    process(
        root=args.path, 
        batch_size=args.batch, 
        resume=(not args.no_resume),
        num_workers=args.workers
    )


if __name__ == "__main__":
    main()
