"""
Socket client for the bridge inside NIS-Elements.
=================================================
:class:`NisClient` opens one TCP connection to the bridge (see
``bridge/nis_bridge.py``) and sends one request at a time, waiting for the
reply before the next. Everything the driver does with the microscope goes
through :meth:`NisClient.request`.

A failure reported by the bridge is raised here as the same kind of exception
(``ValueError`` for a bad request, ``RuntimeError`` when NIS refused or
failed), so callers can treat the bridge like a local function that may raise.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import socket
import threading
from typing import Any

from ..protocol import ENCODING, ProtocolError, decode_reply, encode_request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 54468
DEFAULT_TIMEOUT_S = 30.0


class NisConnectionError(RuntimeError):
    """The bridge could not be reached, or the connection dropped mid-request."""


class NisClient:
    """One connection to the bridge; ``request(op, **args)`` returns the result."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._reader: Any = None
        self._lock = threading.Lock()
        self._next_id = 0

    # -- lifecycle ------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> dict[str, Any]:
        """Open the connection and return the bridge's ``ping`` answer.

        Raises :class:`NisConnectionError` with a plain hint when nothing is
        listening: the usual cause is that ``start_bridge.mac`` has not been run
        in NIS-Elements yet.
        """
        if self._sock is not None:
            return self.request("ping")
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise NisConnectionError(
                f"no bridge at {self.host}:{self.port} ({exc}). Is NIS-Elements running, "
                "and has start_bridge.mac been run in it (Macro > Run Macro From File)?"
            ) from None
        sock.settimeout(self.timeout)
        self._sock = sock
        self._reader = sock.makefile("r", encoding=ENCODING, newline="\n")
        return self.request("ping")

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            self._reader.close()
        finally:
            sock.close()

    def __enter__(self) -> NisClient:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- requests -------------------------------------------------------------

    def request(self, op: str, *, read_timeout: float | None = None, **args: Any) -> Any:
        """Send one operation and return its result (or raise what the bridge raised).

        ``read_timeout`` can lengthen the wait for slow operations such as a
        long capture; the default is the client's timeout.
        """
        if self._sock is None:
            raise NisConnectionError("client is not connected; call connect() first")
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            try:
                self._sock.settimeout(read_timeout or self.timeout)
                self._sock.sendall(encode_request(request_id, op, args).encode(ENCODING))
                line = self._reader.readline()
            except (OSError, ValueError) as exc:
                self.close()
                raise NisConnectionError(
                    f"connection to the bridge failed during {op!r}: {exc}"
                ) from None
            finally:
                if self._sock is not None:
                    self._sock.settimeout(self.timeout)
        if not line:
            self.close()
            raise NisConnectionError(f"the bridge closed the connection during {op!r}")
        reply_id, result = decode_reply(line)
        if reply_id != request_id:
            raise ProtocolError(f"reply id {reply_id} does not match request id {request_id}")
        return result
