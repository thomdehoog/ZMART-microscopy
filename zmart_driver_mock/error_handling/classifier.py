"""Sorting MockScope's errors into the shared kinds.

This is the only microscope-specific piece of error handling. For LAS X the
classifier reads the command echo text; for ZEN it reads gRPC status codes.
For MockScope it reads the vendor's error code.

One rule matters more than any other here: **an error we do not recognise
counts as permanent.** Trying again after an error we do not understand
could repeat something harmful, so the driver stops instead.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from ..vendor_interface import VendorError
from .rules import Kind

# MockScope's error codes, sorted into kinds. Codes not listed here (such as
# 999, "Internal error") are unknown and therefore permanent.
_CODES: dict[int, Kind] = {
    100: Kind.TEMPORARY,  # system busy
    200: Kind.BAD_REQUEST,  # unknown command: a bug in this driver
    201: Kind.BAD_REQUEST,  # value out of range of the hardware's end stops
    202: Kind.BAD_REQUEST,  # unknown setting
    203: Kind.BAD_REQUEST,  # missing argument
    204: Kind.BAD_REQUEST,  # unknown argument
    205: Kind.BAD_REQUEST,  # invalid value
    206: Kind.BAD_REQUEST,  # folder does not exist
    300: Kind.PERMANENT,  # hardware fault
    401: Kind.PERMANENT,  # access denied
    402: Kind.CONNECTION_LOST,  # the session is gone
}


def classify(error: BaseException) -> Kind:
    """Return the kind of problem ``error`` represents."""
    if isinstance(error, VendorError):
        return _CODES.get(error.code, Kind.PERMANENT)
    if isinstance(error, TimeoutError):
        # The reply was lost. The command may or may not have happened, which
        # is why the set dispatcher reads back before deciding anything.
        return Kind.TEMPORARY
    if isinstance(error, ConnectionError):
        return Kind.CONNECTION_LOST
    return Kind.PERMANENT
