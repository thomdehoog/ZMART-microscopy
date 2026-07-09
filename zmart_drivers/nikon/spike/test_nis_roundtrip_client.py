"""Offline tests for the round-trip client's pure logic.

The socket round-trip itself needs the NIS 6.2 bench; these cover everything
that does not -- reply parsing and line framing -- so the protocol contract is
pinned before the hardware run.

Run:  pytest test_nis_roundtrip_client.py
"""

from __future__ import annotations

import socket
import threading

from nis_roundtrip_client import TERMINATOR, NisRoundTripClient, parse_reply


def test_terminator_is_carriage_return() -> None:
    # NkSocket ReadLineA/WriteLineA frame on '\r'; the client must match.
    assert TERMINATOR == "\r"


def test_parse_ping() -> None:
    r = parse_reply("OK|pong")
    assert r.ok
    assert r.status == "OK"
    assert r.fields == {}
    assert r.extras == ["pong"]


def test_parse_calibration_keeps_objective_spaces() -> None:
    line = (
        "OK|query=Get_Calibration|cal_um_per_px=0.32300|aspect=1.0000|unit=0|objective=Plan Apo 20x"
    )
    r = parse_reply(line)
    assert r.ok
    assert r.fields["cal_um_per_px"] == "0.32300"
    assert r.fields["aspect"] == "1.0000"
    assert r.fields["unit"] == "0"
    # '|' (not whitespace) is the separator, so the spaced name survives intact
    assert r.fields["objective"] == "Plan Apo 20x"


def test_parse_error_message() -> None:
    r = parse_reply("ERROR|no image open - cannot read calibration")
    assert not r.ok
    assert r.status == "ERROR"
    assert r.extras == ["no image open - cannot read calibration"]


def test_parse_status_only() -> None:
    r = parse_reply("OK")
    assert r.ok
    assert r.fields == {}
    assert r.extras == []


# --- transport round-trip against a fake server (emulates the .mac) ----------

_CANNED = {
    "?ping": "OK|pong",
    "?Get_Calibration": (
        "OK|query=Get_Calibration|cal_um_per_px=0.32300|aspect=1.0000|unit=0|objective=Plan Apo 20x"
    ),
}


def _fake_nis_server(sock: socket.socket) -> None:
    """One-connection server that frames on '\\r' exactly like NkSocket*LineA."""
    conn, _ = sock.accept()
    with conn:
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
            while b"\r" in buf:
                raw, _, buf = buf.partition(b"\r")
                line = raw.decode("ascii").strip("\r\n")
                reply = _CANNED.get(line, f"ERROR|unknown query: {line[1:]}")
                conn.sendall((reply + "\r").encode("ascii"))


def test_client_round_trip_over_socket() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))  # ephemeral port
    srv.listen(1)
    host, port = srv.getsockname()
    thread = threading.Thread(target=_fake_nis_server, args=(srv,), daemon=True)
    thread.start()

    with NisRoundTripClient(host, port, timeout=5.0) as client:
        assert client.query("ping").extras == ["pong"]

        cal = client.query("Get_Calibration")
        assert cal.ok
        assert cal.fields["cal_um_per_px"] == "0.32300"
        assert cal.fields["objective"] == "Plan Apo 20x"

        # unknown query surfaces as an ERROR reply, not an exception
        bad = client.query("frobnicate")
        assert not bad.ok
        assert bad.extras == ["unknown query: frobnicate"]

    srv.close()
