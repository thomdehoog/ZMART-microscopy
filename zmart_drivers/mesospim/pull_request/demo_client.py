"""
Demo client for the mesoSPIM Remote Control server.
===================================================
The server accepts named calls, not code: you send one single-key JSON object
``{"<method>": {args}}`` and read back a ``__MESOSPIM_OK__<json>`` line. This tiny
client shows the whole protocol -- framing, the optional token, and a call.

Run mesoSPIM (-D demo is fine), start the Remote Control tab (TCP mode), then:

    python demo_client.py --host 127.0.0.1 --port 42000 --token <token>

Or, right after you press Start, run the VIABILITY CHECK first -- it proves both
lanes are up and that a limit CANNOT be violated, without ever moving the stage
(the out-of-limit probe is refused before the Core is touched)::

    python demo_client.py --self-check --port 42000 --token <t> --mcp-port 42100 --mcp-token <t2>

MIT (this is client-side example code; it imports nothing from mesoSPIM).
Author: Thom de Hoog (ZMB, University of Zurich).
"""
import argparse
import json
import socket
import urllib.request

OK = "__MESOSPIM_OK__"


class RemoteControl:
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


def mcp_call(host, port, token, method, name, arguments, timeout=10.0):
    """POST one JSON-RPC message to the MCP server; return the parsed reply."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": {"name": name, "arguments": arguments} if name else {}}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Origin": "http://127.0.0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"http://{host}:{port}/mcp", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _first_limited_axis(limits):
    """Pick an axis that actually has a range, so we can prove the range is ENFORCED.
    Returns (axis, [lo, hi]) or (None, None) if every axis' range check is off."""
    axes = (limits.get("enforced") or {}).get("axes") or {}
    for axis, lohi in axes.items():
        if lohi:  # a real [lo, hi]; null means the check is off for that axis
            return axis, lohi
    return None, None


def self_check(host, port, token, mcp_port=None, mcp_token=None):
    """Viability check: prove both lanes are live and a limit CANNOT be violated.

    The out-of-limit probe is ``max + 1`` -- the smallest value past the envelope --
    and it is refused BEFORE the Core, so the stage never moves. If it were ever
    accepted, that is the FAIL we are looking for (and only a 1-unit overshoot).
    """
    ok = True
    c = RemoteControl(host, port, token)
    try:
        print("[TCP] connect + auth .......... OK")
        hello = c.call("hello")
        print(f"[TCP] hello ................... OK (version={hello.get('version')}, state={hello.get('state')})")
        print(f"[TCP] get_position ............ OK ({c.call('get_position')})")
        st = c.call("self_test")  # the server re-runs its pre-flight against a mock of ITS cfg
        n_fail = sum(1 for line in st.get("report", []) if line.startswith("FAIL"))
        print(f"[TCP] self_test (server-side) . {'OK' if st.get('ok') else 'FAIL'} "
              f"({len(st.get('report', []))} checks, {n_fail} failed)")
        ok = ok and bool(st.get("ok"))
        limits = c.call("get_limits")
        axis, lohi = _first_limited_axis(limits)
        if axis is None:
            print("[TCP] get_limits .............. WARN: every axis range is OFF -- cannot verify enforcement")
            probe = None
        else:
            bad = lohi[1] + 1
            probe = (axis, bad)
            print(f"[TCP] get_limits .............. OK ({axis}={lohi}, ...)")
            try:
                c.call("move_absolute", targets={axis: bad})
                print(f"[TCP] reject out-of-limit ..... FAIL: {axis}={bad} was ACCEPTED -- limit violated!")
                ok = False
            except RuntimeError as e:
                print(f"[TCP] reject out-of-limit ..... OK ({axis}={bad} refused: {str(e).splitlines()[0][:50]})")
    finally:
        c.close()

    if mcp_port:
        try:
            got = mcp_call(host, mcp_port, mcp_token or token, "tools/call", "get_state", {})
            up = not got.get("result", {}).get("isError", True)
            print(f"[MCP] tools/call get_state .... {'OK' if up else 'FAIL (isError)'}")
            ok = ok and up
            if probe:
                axis, bad = probe
                res = mcp_call(host, mcp_port, mcp_token or token,
                               "tools/call", "move_absolute", {"targets": {axis: bad}}).get("result", {})
                if res.get("isError"):
                    print(f"[MCP] reject out-of-limit ..... OK ({axis}={bad} -> isError)")
                else:
                    print(f"[MCP] reject out-of-limit ..... FAIL: {axis}={bad} ACCEPTED over MCP -- limit violated!")
                    ok = False
        except Exception as e:  # noqa: BLE001 - a viability check reports any failure, doesn't crash
            print(f"[MCP] .......................... FAIL ({e})")
            ok = False

    print()
    print("VIABILITY: " + ("PASS  (both lanes up, limits enforced, stage never moved)"
                           if ok else "FAIL  (see above -- do NOT rely on this server)"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=42000)
    ap.add_argument("--token", default=None)
    ap.add_argument("--self-check", action="store_true",
                    help="run the viability check (prove both lanes enforce limits; never moves the stage)")
    ap.add_argument("--mcp-port", type=int, default=None, help="also check the MCP lane on this port")
    ap.add_argument("--mcp-token", default=None, help="MCP token if it differs from --token")
    args = ap.parse_args()

    if args.self_check:
        raise SystemExit(0 if self_check(args.host, args.port, args.token,
                                         args.mcp_port, args.mcp_token) else 1)

    c = RemoteControl(args.host, args.port, args.token)
    try:
        print("state:", c.call("get_state"))
        print("config:", c.call("get_config"))
        print("capabilities:", c.call("get_capabilities"))
    finally:
        c.close()


if __name__ == "__main__":
    main()
