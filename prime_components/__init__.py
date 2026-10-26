"""Small, dependency-free reference model for reusable capability modules."""
from .core import MAX_MODULES, ValidationError, choose_modules, compute_time, validate_catalog, validate_compute

__all__ = ["MAX_MODULES", "ValidationError", "choose_modules", "compute_time", "validate_catalog", "validate_compute"]
