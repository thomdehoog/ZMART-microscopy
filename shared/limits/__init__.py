"""Function-keyed safety limits shared by every driver.

One JSON file per driver declares, for EVERY mutating operation, either a
bound or an explicit ``null`` ("reviewed, deliberately unlimited") — a
missing entry fails at load, so a new setter can never ship silently
unlimited. See :mod:`shared.limits.spec` for the schema and the rules.

Import convention: ``from shared.limits import FunctionLimits, load, ...``
Requires the repository root on sys.path.
"""

from .spec import (
    SCHEMA_VERSION,
    Constraint,
    FunctionLimits,
    LimitsError,
    LimitViolation,
    load,
    parse,
)

__all__ = [
    "SCHEMA_VERSION",
    "Constraint",
    "FunctionLimits",
    "LimitsError",
    "LimitViolation",
    "load",
    "parse",
]
