"""
FV4000 RDK client (spike).
==========================
A minimal synchronous TCP client for the Evident/Olympus RDK protocol, targeting
the FLUOVIEW FV4000. It connects to the RDK server, logs in, and sends
``VERB= args`` commands / queries, parsing the ``VERB= +`` / ``VERB= v1,v2`` /
``VERB= -`` replies. This is the seed of the eventual
``drivers/evident/fv4000/rdk/connection`` layer.

    ⚠ The device verbs (MVSTG, CHOB, …) are OLS5000-derived PLACEHOLDERS. The real
    FV4000 RDK vocabulary (acquire/scan, laser, detector, …) is behind Evident's
    developer program and must replace these. The transport below is what the
    spike proves; the vocabulary is quarantined to the convenience methods.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import socket

from rdk_protocol import Message, TERMINATOR, encode, frame, parse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 50100  # OLS5000 RDK default; confirm the FV4000 RDK port


class RdkError(RuntimeError):
    """A command returned a NAK (``VERB= -``) or an unexpected reply."""


class RdkClient:
    """Blocking TCP client speaking the RDK ``VERB= args`` protocol."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0):
        self._addr = (host, port)
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""

    def __enter__(self) -> "RdkClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- session --------------------------------------------------------------

    def connect(self, *, login=("user", "olympus")) -> None:
        """Open the socket, send CONNECT, and (optionally) log in."""
        self._sock = socket.create_connection(self._addr, timeout=self._timeout)
        self._require_ok(self.command("CONNECT", 0))
        if login is not None:
            self._require_ok(self.command("INITNRML", *login))

    def close(self) -> None:
        if self._sock is not None:
            try:
                self.command("DISCONNECT", 0)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

    # -- transport ------------------------------------------------------------

    def _send_line(self, line: str) -> None:
        assert self._sock is not None, "not connected"
        self._sock.sendall(frame(line))

    def _read_line(self) -> str:
        assert self._sock is not None, "not connected"
        term = TERMINATOR.encode("ascii")
        while term not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("RDK server closed the connection")
            self._buf += chunk
        raw, _, self._buf = self._buf.partition(term)
        return raw.decode("ascii", "replace")

    def command(self, verb: str, *args) -> Message:
        """Send ``verb= args`` and return the parsed reply."""
        self._send_line(encode(verb, *args))
        return parse(self._read_line())

    @staticmethod
    def _require_ok(msg: Message) -> Message:
        if not msg.ok:
            raise RdkError(f"{msg.verb} not acknowledged: {msg.raw!r}")
        return msg

    # -- device convenience (PLACEHOLDER verbs) -------------------------------

    def move_stage(self, x_um: float, y_um: float) -> None:
        self._require_ok(self.command("MVSTG", x_um, y_um))

    def read_stage(self) -> tuple[float, float]:
        m = self.command("RDSTG", 0)
        return float(m.args[0]), float(m.args[1])

    def move_z(self, z_um: float) -> None:
        self._require_ok(self.command("MVZ", z_um))

    def read_z(self) -> float:
        return float(self.command("RDZ", 0).args[0])

    def set_objective(self, index: int) -> None:
        self._require_ok(self.command("CHOB", index))

    def read_objective(self) -> int:
        return int(self.command("RDOB", 0).args[0])
