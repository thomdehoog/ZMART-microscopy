"""
Mock FV4000 RDK server (offline test double).
=============================================
A fake Evident/Olympus RDK **TCP server** for the FLUOVIEW FV4000 spike. It
speaks the ``VERB= args`` / ``VERB= +`` protocol (see ``rdk_protocol``), holds a
little mutable instrument state (stage µm, focus µm, objective index), and lets
the spike's client be exercised end-to-end with NO Evident software, license, or
microscope.

    ⚠ The command vocabulary here is OLS5000-derived PLACEHOLDER (MVSTG, CHOB, …),
    not the real FV4000 RDK verbs (which are behind Evident's developer program).
    Only the transport/framing is expected to match the real RDK. Swapping in the
    real verbs is a one-file change here and in ``rdk_client``.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import socket
import threading

from rdk_protocol import ACK, NAK, TERMINATOR, parse


class MockRdkServer:
    """One-client-at-a-time fake RDK server for tests.

    Args:
        host, port: bind address; ``port=0`` picks a free ephemeral port
            (read ``.port`` after construction).
        errors: verbs that should reply with a NAK, to exercise error handling.
        require_login: if True, device commands NAK until ``INITNRML`` succeeds.
    """

    def __init__(self, host="127.0.0.1", port=0, *, errors=None, require_login=True):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(1)
        self.host, self.port = self._sock.getsockname()
        self.errors = set(errors or [])
        self.require_login = require_login
        self.state = {"x_um": 0.0, "y_um": 0.0, "z_um": 0.0, "objective": 1, "logged_in": False}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------------

    def __enter__(self) -> "MockRdkServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, name="mock-rdk", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # -- server loop ----------------------------------------------------------

    def _serve(self) -> None:
        self._sock.settimeout(0.3)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                self._handle(conn)

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(0.3)
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return  # client disconnected
            buf += chunk
            while b"\n" in buf:
                raw, _, buf = buf.partition(b"\n")
                reply = self._dispatch(raw.decode("ascii", "replace"))
                conn.sendall((reply + TERMINATOR).encode("ascii"))

    # -- command dispatch -----------------------------------------------------

    def _dispatch(self, line: str) -> str:
        msg = parse(line)
        verb, args = msg.verb, msg.args

        if verb in self.errors:
            return f"{verb}{'= '}{NAK}"

        # Session commands are always allowed.
        if verb == "CONNECT":
            return f"CONNECT= {ACK}"
        if verb == "INITNRML":
            self.state["logged_in"] = len(args) >= 2 and bool(args[0])
            return f"INITNRML= {ACK if self.state['logged_in'] else NAK}"
        if verb == "DISCONNECT":
            self.state["logged_in"] = False
            return f"DISCONNECT= {ACK}"

        if self.require_login and not self.state["logged_in"]:
            return f"{verb}= {NAK}"

        # Device commands (PLACEHOLDER verbs).
        if verb == "MVSTG":
            self.state["x_um"], self.state["y_um"] = float(args[0]), float(args[1])
            return f"MVSTG= {ACK}"
        if verb == "RDSTG":
            return f"RDSTG= {self.state['x_um']:.3f},{self.state['y_um']:.3f}"
        if verb == "MVZ":
            self.state["z_um"] = float(args[0])
            return f"MVZ= {ACK}"
        if verb == "RDZ":
            return f"RDZ= {self.state['z_um']:.3f}"
        if verb == "CHOB":
            self.state["objective"] = int(args[0])
            return f"CHOB= {ACK}"
        if verb == "RDOB":
            return f"RDOB= {self.state['objective']}"

        return f"{verb}= {NAK}"  # unknown verb
