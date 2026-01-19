import logging
import sys
from typing import List, Optional

import onnxruntime as ort

logger = logging.getLogger(__name__)

# Приоритет провайдеров ONNX Runtime для NPU и GPU
PROVIDER_PRIORITY = [
    "OpenVINOExecutionProvider",  # Intel NPU/GPU
    "DmlExecutionProvider",       # Windows DirectML (NPU/GPU)
    "QNNExecutionProvider",       # Qualcomm NPU
    "CoreMLExecutionProvider",    # Apple Neural Engine
    "CUDAExecutionProvider",      # NVIDIA GPU
    "ROCMExecutionProvider",      # AMD GPU
    "CPUExecutionProvider",       # Fallback
]

def detect_available_providers() -> List[str]:
    """Возвращает список доступных провайдеров ONNX Runtime."""
    available = ort.get_available_providers()

    # Фильтруем и сортируем согласно нашему приоритету
    supported = [p for p in PROVIDER_PRIORITY if p in available]

    # Добавляем остальные, если они есть
    for p in available:
        if p not in supported:
            supported.append(p)

    return supported

def get_best_provider(mode: str = "auto") -> str:
    """
    Возвращает лучший доступный провайдер.
    mode: "auto", "npu", "gpu", "cpu"
    """
    available = detect_available_providers()

    if mode == "cpu":
        return "CPUExecutionProvider"

    if mode == "npu":
        npu_providers = [
            "OpenVINOExecutionProvider",
            "QNNExecutionProvider",
            "CoreMLExecutionProvider"
        ]
        for p in npu_providers:
            if p in available:
                return p
        # Fallback to DML as it might use NPU
        if "DmlExecutionProvider" in available:
            return "DmlExecutionProvider"

    if mode == "gpu":
        gpu_providers = [
            "CUDAExecutionProvider",
            "ROCMExecutionProvider",
            "DmlExecutionProvider",
            "OpenVINOExecutionProvider"
        ]
        for p in gpu_providers:
            if p in available:
                return p

    # Auto mode or fallback
    for p in PROVIDER_PRIORITY:
        if p in available:
            return p

    return "CPUExecutionProvider"

def has_npu() -> bool:
    """Проверяет наличие NPU через доступные провайдеры."""
    available = detect_available_providers()
    npu_providers = [
        "OpenVINOExecutionProvider",
        "QNNExecutionProvider",
        "CoreMLExecutionProvider"
    ]
    return any(p in available for p in npu_providers)

def get_provider_options(provider: str) -> dict:
    """Возвращает настройки для конкретного провайдера."""
    options = {}
    if provider == "OpenVINOExecutionProvider":
        # Предпочитаем NPU для OpenVINO если доступен
        options = {
            "device_type": "NPU",
            "precision": "FP16"
        }
    elif provider == "DmlExecutionProvider":
        options = {
            "device_id": 0
        }
    return options



