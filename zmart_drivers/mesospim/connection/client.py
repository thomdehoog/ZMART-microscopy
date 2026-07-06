"""
mesoSPIM remote-scripting client.
=================================
The external **MIT** client that drives mesoSPIM-control through its **Remote
Scripting** server (the upstream PR under ``pull_request/``). It is a
process-boundary transport that keeps ZMART MIT while mesoSPIM-control stays GPL
behind the socket.

A "command" is a named call on the wire -- a single-key JSON object
``{"<method>": {args}}`` (data, not code) -- which the server dispatches against a
fixed allowlist (:mod:`mesospim.connection.command_api`). The client frames the
call, reads back the reply, and extracts the structured ``{ok, data, error}``
result (see :mod:`mesospim.protocol`).

The public surface -- ``connect`` / ``request`` / ``try_request`` / ``close`` and
the ``Reply`` shape -- is unchanged from the previous transport, so the driver's
dispatch, readers, commands, and controller layers are agnostic to how the wire
works. All retry/confirm policy lives one layer up in ``commands.dispatch``.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Any

from ..protocol import Reply, encode_call, frame, parse_result

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42000  # mesoSPIM Remote Scripting default (configurable per profile)


class MesospimError(RuntimeError):
    """A command failed (the server reported an error for the call) or the
    server refused/garbled the exchange."""


class MesospimClient:
    """Blocking TCP client speaking the mesoSPIM Remote Scripting protocol.

    One request/reply pair at a time, guarded by a lock so the driver's readers
    and command wrappers can share a single client without interleaving frames
    on the socket. The Remote Scripting server is single-client by design (it
    lives in the Qt event loop).
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        timeout: float = 10.0,
        token: str | None = None,
    ) -> None:
        self._addr = (host, port)
        self._timeout = timeout
        self._token = token
        self._sock: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()
        # Filled from a ``hello`` script so callers can report server identity.
        self.server_info: dict[str, Any] = {}

    # -- identity / introspection --------------------------------------------

    @property
    def host(self) -> str:
        return self._addr[0]

    @property
    def port(self) -> int:
        return self._addr[1]

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> MesospimClient:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def connect(self) -> dict[str, Any]:
        """Open the socket, authenticate if a token is set, and read server info.

        Raises ``ConnectionError`` if the socket cannot open, and
        :class:`MesospimError` if authentication fails or the first script does
        not round-trip (e.g. the Remote Scripting server is not running).
        """
        if self._sock is not None:
            return self.server_info
        try:
            self._sock = socket.create_connection(self._addr, timeout=self._timeout)
        except OSError as exc:
            raise ConnectionError(
                f"cannot reach the mesoSPIM Remote Scripting server at "
                f"{self._addr[0]}:{self._addr[1]} -- is mesoSPIM running with "
                f"Tools -> Remote Scripting started? ({exc})"
            ) from exc
        self._sock.settimeout(self._timeout)
        try:
            if self._token is not None:
                with self._lock:
                    self._send_frame(self._token)
                    ack = self._read_frame().strip()
                if ack != "OK":
                    raise MesospimError(f"authentication failed (server said {ack!r})")
            reply = self.request("hello")
        except BaseException:
            self._drop_socket()
            raise
        self.server_info = dict(reply.data)
        log.info(
            "connected to mesoSPIM Remote Scripting %s:%d (%s)",
            self._addr[0],
            self._addr[1],
            self.server_info.get("app", "unknown"),
        )
        return self.server_info

    def close(self) -> None:
        """Close the socket. Idempotent. The Remote Scripting server needs no
        teardown message -- closing the TCP connection is enough."""
        with self._lock:
            self._drop_socket()

    def _drop_socket(self) -> None:
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._sock = None
        self._buf = b""

    # -- request/reply -------------------------------------------------------

    def request(self, cmd: str, *, read_timeout: float | None = None, **args: Any) -> Reply:
        """Send the named call ``cmd`` with ``args`` and return the result.

        Raises :class:`MesospimError` if the server reported an error; use
        :meth:`try_request` when a failure is an expected, inspectable outcome.
        ``read_timeout`` overrides the socket deadline for this one call (used for
        long-running commands like ``acquire``); the base timeout is restored after.
        """
        reply = self.try_request(cmd, read_timeout=read_timeout, **args)
        if not reply.ok:
            raise MesospimError(f"{cmd} failed: {reply.error or '(no message)'}")
        return reply

    def try_request(self, cmd: str, *, read_timeout: float | None = None, **args: Any) -> Reply:
        """Send the named call ``cmd`` and return the result without raising.

        ``read_timeout`` (seconds) overrides the socket deadline for this call
        only -- acquisitions can run far longer than the default. It is
        keyword-only so it is never sent as a command argument.
        """
        if self._sock is None:
            raise ConnectionError("not connected; call connect() first")
        payload = encode_call(cmd, dict(args))
        with self._lock:
            if read_timeout is not None:
                self._sock.settimeout(read_timeout)
            try:
                self._send_frame(payload)
                console = self._read_frame()
            except OSError:
                # Transport failure (dropped link / timeout mid-frame): invalidate
                # the connection so ``connected`` is truthful and stale bytes can't
                # splice onto the next reply. dispatch treats this as transient.
                self._drop_socket()
                raise
            finally:
                if read_timeout is not None and self._sock is not None:
                    self._sock.settimeout(self._timeout)
        return parse_result(console)

    # -- transport (length-framed) -------------------------------------------

    def _send_frame(self, payload: str) -> None:
        assert self._sock is not None, "not connected"
        self._sock.sendall(frame(payload))

    def _read_frame(self) -> str:
        assert self._sock is not None, "not connected"
        while b"\n" not in self._buf:
            self._fill()
        head, _, rest = self._buf.partition(b"\n")
        try:
            length = int(head)
        except ValueError as exc:
            raise MesospimError(f"framing error: expected a byte count, got {head!r}") from exc
        while len(rest) < length:
            self._buf = rest
            self._fill()
            rest = self._buf
        self._buf = rest[length:]
        return rest[:length].decode("utf-8", "replace")

    def _fill(self) -> None:
        chunk = self._sock.recv(4096)
        if not chunk:
            raise ConnectionError("mesoSPIM Remote Scripting server closed the connection")
        self._buf += chunk
