"""
Módulo de métricas para el sistema Oceano.

Este módulo proporciona clases para registrar y exportar métricas de rendimiento
del sistema de reconocimiento facial, incluyendo métricas de ingesta y búsqueda.

Valida: Requisitos 7.1, 7.2, 7.3, 7.4
"""

import json
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class IngestMetrics:
    """
    Métricas de ingesta masiva de imágenes.
    
    Attributes:
        total_images: Número total de imágenes procesadas
        successful: Número de imágenes procesadas exitosamente
        failed: Número de imágenes que fallaron
        throughput: Throughput en imágenes por segundo
        avg_io_time: Tiempo promedio de I/O en milisegundos
        avg_embedding_time: Tiempo promedio de generación de embeddings en milisegundos
        avg_upsert_time: Tiempo promedio de inserción en Qdrant en milisegundos
        gpu_utilization: Utilización de GPU en porcentaje (0-100)
    
    Valida: Requisitos 7.1, 7.4
    """
    total_images: int
    successful: int
    failed: int
    throughput: float  # imgs/sec
    avg_io_time: float  # ms
    avg_embedding_time: float  # ms
    avg_upsert_time: float  # ms
    gpu_utilization: float  # % (0-100)
    
    def to_dict(self) -> Dict:
        """
        Serializa las métricas a un diccionario.
        
        Returns:
            Diccionario con todas las métricas de ingesta
        """
        return {
            "total_images": self.total_images,
            "successful": self.successful,
            "failed": self.failed,
            "throughput_imgs_per_sec": self.throughput,
            "avg_io_time_ms": self.avg_io_time,
            "avg_embedding_time_ms": self.avg_embedding_time,
            "avg_upsert_time_ms": self.avg_upsert_time,
            "gpu_utilization_percent": self.gpu_utilization
        }


@dataclass
class SearchMetrics:
    """
    Métricas de búsqueda facial.
    
    Attributes:
        total_latency: Latencia total de la búsqueda en milisegundos
        embedding_latency: Latencia de generación de embedding en milisegundos
        qdrant_latency: Latencia de búsqueda en Qdrant en milisegundos
        num_results: Número de resultados retornados
    
    Valida: Requisitos 7.2
    """
    total_latency: float  # ms
    embedding_latency: float  # ms
    qdrant_latency: float  # ms
    num_results: int
    
    def to_dict(self) -> Dict:
        """
        Serializa las métricas a un diccionario.
        
        Returns:
            Diccionario con todas las métricas de búsqueda
        """
        return {
            "total_latency_ms": self.total_latency,
            "embedding_latency_ms": self.embedding_latency,
            "qdrant_latency_ms": self.qdrant_latency,
            "num_results": self.num_results
        }


class MetricsCollector:
    """
    Colector de métricas del sistema.
    
    Esta clase mantiene un registro de todas las métricas de ingesta y búsqueda,
    y proporciona métodos para exportarlas a diferentes formatos.
    
    Valida: Requisitos 7.1, 7.2, 7.3, 7.4
    """
    
    def __init__(self):
        """Inicializa el colector de métricas con listas vacías."""
        self.ingest_metrics: List[IngestMetrics] = []
        self.search_metrics: List[SearchMetrics] = []
    
    def record_ingest(self, metrics: IngestMetrics):
        """
        Registra métricas de una operación de ingesta.
        
        Args:
            metrics: Objeto IngestMetrics con las métricas a registrar
        """
        self.ingest_metrics.append(metrics)
    
    def record_search(self, metrics: SearchMetrics):
        """
        Registra métricas de una operación de búsqueda.
        
        Args:
            metrics: Objeto SearchMetrics con las métricas a registrar
        """
        self.search_metrics.append(metrics)
    
    def export_json(self, path: str):
        """
        Exporta todas las métricas a un archivo JSON.
        
        Args:
            path: Ruta del archivo JSON donde exportar las métricas
        
        El formato del JSON es:
        {
            "ingest": [lista de métricas de ingesta],
            "search": [lista de métricas de búsqueda]
        }
        """
        data = {
            "ingest": [m.to_dict() for m in self.ingest_metrics],
            "search": [m.to_dict() for m in self.search_metrics]
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
