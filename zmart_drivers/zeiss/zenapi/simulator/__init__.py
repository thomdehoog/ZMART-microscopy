"""
A fake ZEN API gateway, for working without a microscope.
=========================================================
``python -m zenapi.simulator`` starts a small server that speaks the real ZEN
API protocol (gRPC over TLS, the same service definitions from ZEISS's
``zen_api`` wheel, the same control-token check) but drives an imaginary
microscope instead of ZEN. Point the driver's ``config.ini`` at it and every
call in this package works as it would against ZEN, minus the physics.

Use it to try the driver, to develop a workflow before microscope time, and
to run the protocol-level tests in ``tests/gateway``. When ZEISS's simulator
or a real microscope becomes available, only the ``config.ini`` changes.

See :mod:`zenapi.simulator.fake_gateway` for what is simulated and what is not.
"""

from .fake_gateway import FakeGateway, FakeZen

__all__ = ["FakeGateway", "FakeZen"]
