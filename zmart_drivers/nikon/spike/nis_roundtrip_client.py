"""Round-trip client for the SmartMicroscopy <-> NIS-Elements socket spike.

Connects to the resident ``nis_socket_server_roundtrip.mac`` running inside
NIS-Elements 6.2 and exercises the text protocol:

    ?<query>   -> server computes a value and replies with one line
    !<command> -> server runs the line as a NIS macro command (fire-and-forget)

Lines are ASCII, terminated by a carriage return (``\\r``) -- the framing used
by ``NkSocket_WriteLineA`` / ``NkSocket_ReadLineA``. Reply lines are
pipe-delimited (``STATUS|key=value|...``) so an objective name may contain
spaces without breaking the parse.

This proves the Leica-symmetric external-orchestrator loop end to end *before*
any device-motion verbs exist: ``?Get_Calibration`` reads real state back today.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import argparse
import socket
from dataclasses import dataclass, field

TERMINATOR = "\r"  # NkSocket ReadLineA/WriteLineA frame on a carriage return
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 54468


@dataclass
class Reply:
    """A parsed reply line: ``STATUS|key=value|...|bare-token``."""

    status: str
    fields: dict[str, str] = field(default_factory=dict)
    extras: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def parse_reply(line: str) -> Reply:
    """Parse a pipe-delimited reply into status + key/value fields.

    ``|`` is the field separator (never present in a value), so values such as
    an objective name keep their spaces. Fields without ``=`` (e.g. ``pong`` or
    an error message) are collected in ``extras``.
    """
    parts = line.split("|")
    status = parts[0] if parts else ""
    fields: dict[str, str] = {}
    extras: list[str] = []
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
        elif part:
            extras.append(part)
    return Reply(status=status, fields=fields, extras=extras, raw=line)


class NisRoundTripClient:
    """Minimal TCP client speaking the round-trip spike protocol."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 5.0,
    ) -> None:
        self._addr = (host, port)
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""

    def __enter__(self) -> NisRoundTripClient:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def connect(self) -> None:
        self._sock = socket.create_connection(self._addr, timeout=self._timeout)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _send_line(self, line: str) -> None:
        assert self._sock is not None, "not connected"
        self._sock.sendall((line + TERMINATOR).encode("ascii"))

    def _read_line(self) -> str:
        assert self._sock is not None, "not connected"
        term = TERMINATOR.encode("ascii")
        while term not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("server closed the connection")
            self._buf += chunk
        raw, _, self._buf = self._buf.partition(term)
        return raw.decode("ascii", errors="replace").strip("\r\n")

    def query(self, name: str) -> Reply:
        """Send ``?name`` and return the parsed reply line."""
        self._send_line("?" + name)
        return parse_reply(self._read_line())

    def command(self, macro_command: str) -> None:
        """Send ``!macro_command`` (fire-and-forget; the server does not reply)."""
        self._send_line("!" + macro_command)


def main() -> int:
    ap = argparse.ArgumentParser(description="NIS-Elements round-trip spike client")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--command", help="send a single !<macro command> and exit")
    args = ap.parse_args()

    with NisRoundTripClient(args.host, args.port) as client:
        if args.command:
            client.command(args.command)
            print(f"sent: !{args.command}")
            return 0

        ping = client.query("ping")
        print(f"ping  -> {ping.raw}")

        cal = client.query("Get_Calibration")
        print(f"calib -> {cal.raw}")
        if cal.ok:
            print(f"  objective    : {cal.fields.get('objective', '?')}")
            print(f"  um per pixel : {cal.fields.get('cal_um_per_px', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
