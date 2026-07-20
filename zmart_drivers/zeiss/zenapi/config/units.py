"""
Unit conversion: the driver's public unit contract.
===================================================
The driver speaks micrometers publicly; the ZEN API speaks SI meters on the
wire. Conversion happens ONLY at the request builder (:mod:`zenapi.commands`)
and the reader parser (:mod:`zenapi.readers`), through the helpers here, so no
other module ever has to know which unit it is holding.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

M_PER_UM = 1e-6
_UNIT_TO_UM = {"um": 1.0, "µm": 1.0, "μm": 1.0, "mm": 1000.0, "m": 1e6}


def to_um(value: float, unit: str = "um") -> float:
    """Convert a length in the given unit ('um'|'mm'|'m') to micrometers."""
    try:
        return float(value) * _UNIT_TO_UM[unit]
    except KeyError as exc:
        raise ValueError(f"Unknown unit '{unit}'. Use: 'um', 'mm', or 'm'") from exc


def um_to_m(um: float) -> float:
    """Micrometers -> meters (the on-the-wire unit)."""
    return float(um) * M_PER_UM


def m_to_um(m: float) -> float:
    """Meters (on the wire) -> micrometers (public unit)."""
    return float(m) * 1e6
