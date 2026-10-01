"""Part 1 of the driver anatomy: the vendor interface.

This is the only part of the driver that knows MockScope Control, the
pretend vendor software. It starts the software, logs in, and offers the
rest of the driver a short list of *primitives*: plain Python functions that
each do one thing, with plain values in micrometers.

It keeps the three promises from the driver anatomy:

1. Plain values: no reply dictionaries or status codes leak out.
2. Every failure can be classified: a refused command raises
   :class:`VendorError` with the vendor's code, a lost reply raises
   ``TimeoutError``, and a closed program raises ``ConnectionError``.
3. It can be swapped: in a real driver, this folder talks to LAS X, ZEN or
   NIS-Elements instead, and nothing above it changes shape.
"""

from .client import MockScopeConnection, VendorError

__all__ = ["MockScopeConnection", "VendorError"]
