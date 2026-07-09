"""
Demo client for the mesoSPIM Remote Scripting server.
=====================================================
Shows how an external tool (e.g. the ZMART driver) builds on the minimal PR: it
sends Python scripts and reads back console output, using MARKERS to extract a
clean machine-readable result (the reply may also carry other threads' console
output, as the Script Window console does).

Run mesoSPIM (-D demo is fine), start Tools -> Remote Scripting..., then:

    python demo_client.py --host 127.0.0.1 --port 42000 --token <token>

MIT (this is client-side example code; it imports nothing from mesoSPIM).
Author: Thom de Hoog (ZMB, University of Zurich).
"""

import argparse
import json
import socket


class RemoteScripting:
    """Tiny client for the length-framed remote-scripting protocol."""

    def __init__(self, host="127.0.0.1", port=42000, token=None, timeout=10.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._buf = b""
        if token:
            self._send(token)
            reply = self._recv()
            if reply.strip() != "OK":
                raise PermissionError(f"authentication failed: {reply!r}")

    # -- framing -------------------------------------------------------------
    def _send(self, text):
        b = text.encode("utf-8")
        self._sock.sendall(str(len(b)).encode("ascii") + b"\n" + b)

    def _recv(self):
        while b"\n" not in self._buf:
            self._buf += self._sock.recv(4096)
        head, _, rest = self._buf.partition(b"\n")
        length = int(head)
        while len(rest) < length:
            rest += self._sock.recv(4096)
        self._buf = rest[length:]
        return rest[:length].decode("utf-8")

    # -- API -----------------------------------------------------------------
    def run(self, script):
        """Send a script; return its raw captured console output."""
        self._send(script)
        return self._recv()

    def eval(self, expr):
        """Evaluate a Python expression in the Core context and return it as JSON.

        Wraps the expression so it prints a marker-delimited JSON payload, then
        extracts it from the reply -- robust to interleaved console output.
        """
        script = f"import json as _json\nprint('<<<R>>>' + _json.dumps({expr}) + '<<<E>>>')\n"
        out = self.run(script)
        start = out.index("<<<R>>>") + len("<<<R>>>")
        end = out.index("<<<E>>>", start)
        return json.loads(out[start:end])

    def close(self):
        self._sock.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=42000)
    ap.add_argument("--token", default=None)
    args = ap.parse_args()

    c = RemoteScripting(args.host, args.port, args.token)
    try:
        # A clean structured read via the marker pattern:
        pos = c.eval("self.state['position']")
        print("position:", pos)
        lasers = c.eval("list(self.cfg.laserdict.keys())")
        print("lasers:", lasers)
        # A raw run (console text, may interleave):
        print("raw:", c.run("print('hello from', self.cfg.laserdict and 'the Core')").strip())
    finally:
        c.close()


if __name__ == "__main__":
    main()
