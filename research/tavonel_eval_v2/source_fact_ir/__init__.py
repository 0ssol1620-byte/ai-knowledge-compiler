"""SOURCE_FACT_IR_V1.

A real package, because the modules here are loaded two ways and both are
legitimate. Tests and tools in this namespace put directories on `sys.path` and
import flatly (`import ir`); anything walking the tree imports package-qualified
(`source_fact_ir.ir`). Without an `__init__.py` the second style half-works: the
submodule loads, its own `import ir` fails, and the failure surfaces as "no
extractor produces REFERENCE_TARGET" — an absence, not an error.

That is the exact failure mode this package exists to prevent, arriving through
the import system instead of through a parser. So the modules below import each
other package-relative first and flat second, and this file exists so the
package-relative half has a package to be relative to.
"""

from __future__ import annotations
