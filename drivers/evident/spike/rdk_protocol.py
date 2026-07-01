"""
Evident/Olympus RDK wire protocol (shape only).
===============================================
The Olympus/Evident Remote Development Kit family speaks a simple text protocol
over TCP: the microscope PC runs an RDK **server**; a client sends one-line
commands ``VERB= arg1,arg2`` and the server replies ``VERB= +`` on success, a
query value line ``VERB= v1,v2``, or ``VERB= -`` on error. Lines are CRLF-terminated.

This module is the pure, testable core of that protocol — encode/parse only, no
sockets. It is grounded in the **public OLS5000 RDK** sample (the closest openly
documented member of the family); the *verbs themselves* for the FV4000 confocal
are behind Evident's developer program and are NOT encoded here.

    ⚠ SHAPE, NOT VOCABULARY. The command verbs used by the spike (MVSTG, CHOB, …)
    are OLS5000-derived placeholders. The real FV RDK verbs must replace them once
    the Evident RDK reference is obtained. Only this framing is expected to be stable.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass

TERMINATOR = "\r\n"
_SEP = "= "  # OLS5000 uses "VERB= payload" (equals then a space)


def encode(verb: str, *args) -> str:
    """Build a command line ``VERB= a,b`` (without the terminator)."""
    payload = ",".join(str(a) for a in args)
    return f"{verb}{_SEP}{payload}"


def frame(line: str) -> bytes:
    """Add the CRLF terminator and encode to bytes for the wire."""
    return (line + TERMINATOR).encode("ascii")


@dataclass(frozen=True)
class Message:
    """A parsed protocol line (request or reply)."""

    verb: str
    payload: str
    raw: str

    @property
    def ok(self) -> bool:
        """Success acknowledgement (``VERB= +``)."""
        return self.payload == "+"

    @property
    def is_error(self) -> bool:
        """Error/nak (``VERB= -``)."""
        return self.payload == "-"

    @property
    def args(self) -> list[str]:
        """Payload split into fields (empty for ``+``/``-``/empty)."""
        if self.payload in ("+", "-", ""):
            return []
        return self.payload.split(",")


def parse(line: str) -> Message:
    """Parse one line ``VERB= payload`` into a :class:`Message`.

    Tolerant of a missing terminator and of a bare ``VERB=`` (empty payload).
    """
    stripped = line.strip("\r\n")
    if _SEP in stripped:
        verb, payload = stripped.split(_SEP, 1)
    elif stripped.endswith("="):
        verb, payload = stripped[:-1], ""
    else:
        verb, payload = stripped, ""
    return Message(verb=verb.strip(), payload=payload.strip(), raw=stripped)


# Reply payload constants for servers.
ACK = "+"
NAK = "-"
