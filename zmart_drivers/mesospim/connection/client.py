"""
mesoSPIM command-server client.
===============================
A minimal, blocking, line-oriented TCP client for the mesoSPIM command-server
protocol (see :mod:`mesospim.protocol`). It is the external **MIT** client that
connects to the resident command-server script running inside mesoSPIM-control,
sends one JSON request per line, and reads one JSON reply per line.

This is the ZMART analog of the Leica CAM client / Nikon ``NkSocket`` client: a
process-boundary transport that keeps ZMART MIT while mesoSPIM-control stays GPL
behind the socket (see the driver ``README.md`` -> Licensing).

The client is deliberately dumb: it frames lines, matches replies, and raises on
a NAK. All retry/confirm policy lives one layer up in ``commands.dispatch``; all
vocabulary lives in ``commands`` / ``readers``.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Any

from ..protocol import (
    PROTOCOL_VERSION,
    TERMINATOR,
    Reply,
    encode_request,
    frame,
    parse_reply,
)

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 42000  # mesoSPIM command-server default (configurable per profile)


class MesospimError(RuntimeError):
    """A command returned a NAK (``ok=false``) or an unexpected reply."""


class MesospimClient:
    """Blocking TCP client speaking the mesoSPIM JSON-lines protocol.

    One request/reply pair at a time, guarded by a lock so the driver's readers
    and command wrappers can share a single client without interleaving frames
    on the socket. Not a connection pool -- mesoSPIM's command server is
    single-client by design (it lives in the Qt event loop).
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        timeout: float = 10.0,
    ) -> None:
        self._addr = (host, port)
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()
        self._next_id = 0
        # Filled from the ``hello`` handshake so readers can report identity.
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
        """Open the socket and perform the ``hello`` handshake.

        Returns the server's ``hello`` payload (protocol version, app name,
        current state). Raises ``ConnectionError`` if the socket cannot open,
        :class:`MesospimError` if the handshake is refused, and
        :class:`MesospimError` if the server speaks a protocol version this
        client does not know.
        """
        if self._sock is not None:
            return self.server_info
        try:
            self._sock = socket.create_connection(self._addr, timeout=self._timeout)
        except OSError as exc:
            raise ConnectionError(
                f"cannot reach the mesoSPIM command server at "
                f"{self._addr[0]}:{self._addr[1]} -- is mesoSPIM running with the "
                f"resident command-server script loaded? ({exc})"
            ) from exc
        self._sock.settimeout(self._timeout)
        # A failed handshake must not leave a half-open socket that reports
        # ``connected`` with empty ``server_info``; tear it down and re-raise.
        try:
            reply = self.request("hello")
        except BaseException:
            self._drop_socket()
            raise
        info = dict(reply.data)
        version = info.get("protocol")
        if version is not None:
            try:
                server_version = int(version)
            except (TypeError, ValueError):
                self._drop_socket()
                raise MesospimError(
                    f"server reported an unparseable protocol version {version!r}"
                ) from None
            if server_version != PROTOCOL_VERSION:
                self._drop_socket()
                raise MesospimError(
                    f"server speaks protocol version {version}, but this client only "
                    f"knows version {PROTOCOL_VERSION}"
                )
        else:
            log.warning("server did not report a protocol version; assuming compatibility")
        self.server_info = info
        log.info(
            "connected to mesoSPIM command server %s:%d (%s)",
            self._addr[0],
            self._addr[1],
            self.server_info.get("app", "unknown"),
        )
        return self.server_info

    def close(self) -> None:
        """Say ``bye`` (best effort) and close the socket. Idempotent.

        Takes the same lock as :meth:`request` so a concurrent in-flight command
        cannot interleave its frame with the ``bye`` or race on the buffer/id.
        """
        with self._lock:
            sock = self._sock
            if sock is None:
                return
            try:
                self._send_line(encode_request("bye", id=self._take_id()))
                sock.settimeout(1.0)
                self._read_line()
            except OSError:
                pass
            finally:
                try:
                    sock.close()
                finally:
                    self._sock = None
                    self._buf = b""

    def _drop_socket(self) -> None:
        """Hard-close the socket without a ``bye`` (used on handshake failure)."""
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._sock = None
        self._buf = b""

    # -- request/reply -------------------------------------------------------

    def request(self, cmd: str, **args: Any) -> Reply:
        """Send ``cmd`` with keyword ``args`` and return the parsed reply.

        Raises :class:`MesospimError` if the reply is a NAK (``ok=false``); use
        :meth:`try_request` when a NAK is an expected, inspectable outcome.
        """
        reply = self.try_request(cmd, **args)
        if not reply.ok:
            raise MesospimError(f"{cmd} rejected: {reply.error or '(no message)'}")
        return reply

    def try_request(self, cmd: str, **args: Any) -> Reply:
        """Send ``cmd`` and return the reply without raising on a NAK."""
        if self._sock is None:
            raise ConnectionError("not connected; call connect() first")
        with self._lock:
            req_id = self._take_id()
            try:
                self._send_line(encode_request(cmd, args=args or None, id=req_id))
                reply = parse_reply(self._read_line())
            except OSError:
                # Transport failure (dropped link, or a timeout that left a
                # half-read frame in the buffer): invalidate the connection so
                # ``connected`` is truthful and stale partial bytes can't splice
                # onto the next reply and desync the stream. dispatch treats this
                # as a transient error; there is no auto-reconnect.
                self._drop_socket()
                raise
            if reply.id is not None and reply.id != req_id:
                # A single-in-flight protocol should never desync; surface it
                # loudly rather than returning a mismatched reply.
                raise MesospimError(
                    f"reply id {reply.id} does not match request id {req_id} for {cmd!r}"
                )
            return reply

    # -- transport -----------------------------------------------------------

    def _take_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _send_line(self, line: str) -> None:
        assert self._sock is not None, "not connected"
        self._sock.sendall(frame(line))

    def _read_line(self) -> str:
        assert self._sock is not None, "not connected"
        term = TERMINATOR.encode("utf-8")
        while term not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("mesoSPIM command server closed the connection")
            self._buf += chunk
        raw, _, self._buf = self._buf.partition(term)
        return raw.decode("utf-8", "replace")
