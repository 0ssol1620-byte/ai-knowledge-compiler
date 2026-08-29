"""TAVONEL Product-to-Core compilation boundary."""

from .compiler import ProductCoreCompiler
from .contracts import (
    PRODUCT_CORE_REQUEST_SCHEMA,
    PRODUCT_CORE_RESPONSE_SCHEMA,
    ProductCoreCompileRequest,
    ProductCoreCompileResponse,
)

__all__ = [
    "PRODUCT_CORE_REQUEST_SCHEMA",
    "PRODUCT_CORE_RESPONSE_SCHEMA",
    "ProductCoreCompileRequest",
    "ProductCoreCompileResponse",
    "ProductCoreCompiler",
]
