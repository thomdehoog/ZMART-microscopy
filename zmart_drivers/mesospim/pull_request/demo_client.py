"""
Demo client for the mesoSPIM Remote Scripting server.
=====================================================
The server accepts named calls, not code: you send one single-key JSON object
``{"<method>": {args}}`` and read back a ``__ZMART_OK__<json>`` line. This tiny
client shows the whole protocol -- framing, the optional token, and a call.

Run mesoSPIM (-D demo is fine), start Tools -> Remote Scripting..., then:

    python demo_client.py --host 127.0.0.1 --port 42000 --token <token>

MIT (this is client-side example code; it imports nothing from mesoSPIM).
Author: Thom de Hoog (ZMB, University of Zurich).
"""
import argparse
import json
import socket

OK = "__ZMART_OK__"


class RemoteScripting:
    """Tiny client for the length-framed named-call protocol."""

    def __init__(self, host="127.0.0.1", port=42000, token=None, timeout=10.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._buf = b""
        if token:
            self._send(token)
            if self._recv().strip() != "OK":
                raise PermissionError("authentication failed")

    # -- framing: "<byte-count>\n" + payload --------------------------------
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

    # -- one named call -> its JSON result ----------------------------------
    def call(self, method, **args):
        """Send ``{method: args}``; return the JSON result, or raise on an error reply."""
        self._send(json.dumps({method: args}))
        reply = self._recv()
        for line in reply.splitlines():
            if line.startswith(OK):
                return json.loads(line[len(OK):])
        raise RuntimeError(reply.strip())  # no OK line -> the reply IS the error

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
        print("state:", c.call("get_state"))
        print("config:", c.call("get_config"))
        print("set filter:", c.call("set_state", settings={"filter": "561/LP"}))
    finally:
        c.close()


if __name__ == "__main__":
    main()
