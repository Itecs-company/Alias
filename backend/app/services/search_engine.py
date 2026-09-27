"""Совместимость со старыми импортами.

Логика поиска перенесена в :mod:`app.services.optimized_search_engine`,
справочник производителей — в :mod:`app.services.manufacturers`.
"""
from __future__ import annotations

from app.services.manufacturer_service import ManufacturerInfo, ManufacturerInfoExtractor, ManufacturerResolver
from app.services.manufacturers import (
    DOMAIN_MANUFACTURER_HINTS,
    KNOWN_MANUFACTURERS,
    normalize_manufacturer_name,
)
from app.services.optimized_search_engine import OptimizedPartSearchEngine, PartSearchEngine

__all__ = [
    "DOMAIN_MANUFACTURER_HINTS",
    "KNOWN_MANUFACTURERS",
    "ManufacturerInfo",
    "ManufacturerInfoExtractor",
    "ManufacturerResolver",
    "OptimizedPartSearchEngine",
    "PartSearchEngine",
    "normalize_manufacturer_name",
]
