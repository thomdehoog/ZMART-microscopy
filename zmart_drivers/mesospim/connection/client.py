"""
mesoSPIM Remote Control client.
===============================
The external **MIT** client that drives mesoSPIM-control through its **Remote
Control** TCP server (mesoSPIM-control pull request #106). The server offers a
fixed list of named calls and validates every argument before anything touches
the microscope; nothing ZMART-specific runs inside mesoSPIM. That process
boundary is also what keeps ZMART MIT while mesoSPIM-control stays GPL.

Three things happen on this socket, in order:

1. **The password.** The first frame a client sends is the Remote Control
   password; the server answers ``OK`` or ``AUTH-FAILED`` and closes. A client
   that has not sent it within ten seconds is dropped.
2. **The greeting.** The client then asks ``hello`` and remembers what the
   server said (application, version, protocol version) as ``server_info``.
3. **Calls.** One JSON call per frame, one reply per call. Reads answer with
   their data. A change is *accepted* first and finishes later; the client
   polls ``get_progress`` for it (see :meth:`MesospimClient.perform`).

The public surface -- ``connect`` / ``request`` / ``try_request`` / ``perform``
/ ``close`` and the :class:`~mesospim.protocol.Reply` shape -- is what the
driver's dispatch, readers, commands, and controller layers build on. All
retry/confirm policy lives one layer up in ``commands.dispatch``.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any

from ..config.profiles import CONNECTION
from ..protocol import (
    ENCODING,
    FAILED,
    PROTOCOL_VERSION,
    Reply,
    encode_call,
    frame,
    frame_length,
    is_active,
    operation_of,
    parse_reply,
)

log = logging.getLogger(__name__)

DEFAULT_HOST = CONNECTION.host
DEFAULT_PORT = CONNECTION.port


class MesospimError(RuntimeError):
    """A call was refused, an accepted change failed, or the server garbled the exchange.

    ``code`` carries the server's reason when there is one: ``validation``,
    ``busy``, ``unknown_command`` or ``execution``. An accepted change that
    later reports ``failed`` carries the code ``operation``.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class MesospimClient:
    """Blocking TCP client speaking the mesoSPIM Remote Control protocol.

    One request/reply pair at a time, guarded by a lock so the driver's readers
    and command wrappers can share a single client without interleaving frames
    on the socket.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        timeout: float = CONNECTION.timeout_s,
        token: str | None = None,
        operation_poll_s: float = CONNECTION.operation_poll_s,
        operation_timeout_s: float = CONNECTION.operation_timeout_s,
    ) -> None:
        self._addr = (host, port)
        self._timeout = timeout
        # The server never serves a client without a password. mesoSPIM's own
        # public placeholder is the default; it only works on the local machine.
        self._token = token if token is not None else CONNECTION.token
        self._poll_s = operation_poll_s
        self._operation_timeout_s = operation_timeout_s
        self._sock: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()
        # Filled from ``hello`` so callers can report the server's identity.
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
        """Open the socket, send the password, and read the server's greeting.

        Raises ``ConnectionError`` when nothing answers at the address, and
        :class:`MesospimError` when the password is refused or the greeting
        does not round-trip (for example the server speaks another protocol
        version).
        """
        if self._sock is not None:
            return self.server_info
        try:
            self._sock = socket.create_connection(self._addr, timeout=self._timeout)
        except OSError as exc:
            raise ConnectionError(
                f"cannot reach the mesoSPIM Remote Control server at "
                f"{self._addr[0]}:{self._addr[1]} -- is mesoSPIM running with the "
                f"Remote Control tab's TCP transport started? ({exc})"
            ) from exc
        self._sock.settimeout(self._timeout)
        try:
            with self._lock:
                self._send_frame(self._token)
                ack = self._read_frame().strip()
            if ack != "OK":
                raise MesospimError(
                    f"the Remote Control password was refused (server said {ack!r}); "
                    "use the password shown in mesoSPIM's Remote Control tab"
                )
            reply = self.request("hello")
        except BaseException:
            self._drop_socket()
            raise
        protocol = reply.data.get("protocol")
        if protocol is not None and int(protocol) != PROTOCOL_VERSION:
            self._drop_socket()
            raise MesospimError(
                f"the server speaks Remote Control protocol {protocol}, this driver "
                f"speaks {PROTOCOL_VERSION}; update one of them"
            )
        self.server_info = dict(reply.data)
        log.info(
            "connected to mesoSPIM Remote Control %s:%d (%s %s)",
            self._addr[0],
            self._addr[1],
            self.server_info.get("app", "unknown"),
            self.server_info.get("version") or "",
        )
        return self.server_info

    def close(self) -> None:
        """Close the socket. Idempotent; the server needs no goodbye message."""
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
        """Make one call and return its reply; raise when the server refused it.

        Raises :class:`MesospimError` (with the server's ``code``) on a refused
        call. Use :meth:`try_request` when a refusal is an expected, inspectable
        outcome. ``read_timeout`` overrides the socket deadline for this one
        call; the base timeout is restored after.
        """
        reply = self.try_request(cmd, read_timeout=read_timeout, **args)
        if not reply.ok:
            raise MesospimError(f"{cmd} refused: {reply.error or '(no message)'}", code=reply.code)
        return reply

    def try_request(self, cmd: str, *, read_timeout: float | None = None, **args: Any) -> Reply:
        """Make one call and return its reply without raising on a refusal.

        ``read_timeout`` (seconds) overrides the socket deadline for this call
        only. It is keyword-only so it is never sent as a call argument.
        """
        if self._sock is None:
            raise ConnectionError("not connected; call connect() first")
        text = encode_call(cmd, args)
        with self._lock:
            if read_timeout is not None:
                self._sock.settimeout(read_timeout)
            try:
                self._send_frame(text)
                answer = self._read_frame()
            except OSError:
                # Transport failure (dropped link / timeout mid-frame): invalidate
                # the connection so ``connected`` is truthful and stale bytes can't
                # splice onto the next reply. dispatch treats this as transient.
                self._drop_socket()
                raise
            finally:
                if read_timeout is not None and self._sock is not None:
                    self._sock.settimeout(self._timeout)
        return parse_reply(answer)

    # -- accepted changes: wait for the operation ----------------------------

    def perform(
        self,
        cmd: str,
        *,
        timeout: float | None = None,
        poll_s: float | None = None,
        **args: Any,
    ) -> Reply:
        """Ask for a change and wait until mesoSPIM reports it finished.

        The server accepts a change (a move, a setting, an acquisition) before
        the work starts and answers with an operation record. This method then
        polls ``get_progress`` until that operation is ``completed`` or
        ``failed``, checking on every poll that the operation id is still the
        one it was given, so a change started by someone else is never
        mistaken for ours.

        Returns a :class:`~mesospim.protocol.Reply`: on success ``data`` holds
        the operation's result (the keys the call produced) plus the final
        ``operation`` record; on failure ``ok`` is False, ``error`` says why
        and ``code`` is ``"operation"``. A refused call (never accepted) comes
        back as the server's own error, as with :meth:`try_request`. A reply
        without an operation (a read, or an emergency call that finished at
        once) is returned as it is.

        An accepted change is never re-sent because polling was slow: if the
        wait runs out, this raises ``TimeoutError`` and names the operation so
        the caller can look at ``get_progress`` before deciding what to do.
        """
        accepted = self.try_request(cmd, **args)
        if not accepted.ok:
            return accepted
        operation = operation_of(accepted.data)
        if not is_active(operation):
            return self._finish(accepted.data, operation)
        return self.wait_for(operation, timeout=timeout, poll_s=poll_s, label=cmd)

    def wait_for(
        self,
        operation: dict[str, Any],
        *,
        timeout: float | None = None,
        poll_s: float | None = None,
        label: str = "operation",
    ) -> Reply:
        """Poll ``get_progress`` until ``operation`` has finished; see :meth:`perform`."""
        wanted = operation.get("id")
        budget = self._operation_timeout_s if timeout is None else timeout
        pause = self._poll_s if poll_s is None else poll_s
        deadline = time.monotonic() + budget
        latest = dict(operation)
        while is_active(latest):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"{label}: operation {wanted} was still {latest.get('status')} after "
                    f"{budget:.0f}s; check get_progress before sending it again"
                )
            time.sleep(pause)
            progress = self.request("get_progress")
            latest = operation_of(progress.data) or {}
            if latest.get("id") != wanted:
                raise MesospimError(
                    f"{label}: operation {wanted} was replaced by {latest.get('id')!r} "
                    "before it finished; someone else is driving the microscope",
                    code="operation",
                )
        return self._finish({}, latest)

    @staticmethod
    def _finish(accepted: dict[str, Any], operation: dict[str, Any] | None) -> Reply:
        """Shape the final reply of a change: its result, and the operation record."""
        data = {k: v for k, v in accepted.items() if k not in ("operation",)}
        if operation is None:
            return Reply(ok=True, data=data)
        if operation.get("status") == FAILED:
            return Reply(
                ok=False,
                data={"operation": operation},
                error=str(operation.get("error") or "the operation failed"),
                code="operation",
            )
        result = operation.get("result")
        if isinstance(result, dict):
            data.update(result)
        data["operation"] = operation
        return Reply(ok=True, data=data)

    # -- transport (length-framed) -------------------------------------------

    def _send_frame(self, payload: str) -> None:
        assert self._sock is not None, "not connected"
        self._sock.sendall(frame(payload))

    def _read_frame(self) -> str:
        assert self._sock is not None, "not connected"
        while b"\n" not in self._buf:
            self._fill()
        head, _, rest = self._buf.partition(b"\n")
        length = frame_length(head)
        while len(rest) < length:
            self._buf = rest
            self._fill()
            rest = self._buf
        self._buf = rest[length:]
        return rest[:length].decode(ENCODING, "replace")

    def _fill(self) -> None:
        chunk = self._sock.recv(4096)
        if not chunk:
            raise ConnectionError("the mesoSPIM Remote Control server closed the connection")
        self._buf += chunk
