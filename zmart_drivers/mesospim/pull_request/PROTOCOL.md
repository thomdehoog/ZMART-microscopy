# Remote Control protocol

The wire protocol for the mesoSPIM **Remote Control** server
(`mesoSPIM_RemoteControl_Servers.py` + `mesoSPIM_RemoteControl_ValidateAndRunCommands.py`).
Deliberately tiny: the server accepts **named calls, not code** — it validates a
small JSON message and translates it into one `mesoSPIM_Core` call from a fixed
allowlist. No client Python is ever run.

## Framing

Length-prefixed UTF-8, both directions:

```
message = "<decimal-byte-count>" + "\n" + <payload bytes>
```

- The count is the number of **payload** bytes that follow the newline.
- One TCP connection carries many messages (persistent).
- The server processes messages one at a time on the Core thread.

## Sequence

```
client ── connect
                                     (if a token is configured)
client ──▶  frame(token)
       ◀──  frame("OK")            # or frame("AUTH-FAILED"), then close
                                     (repeat, or from the start if no token)
client ──▶  frame({"<method>": {args}})
       ◀──  frame("__ZMART_OK__" + <json result>)   # or error text
```

- **Auth.** When the server has a token, the **first** frame must be that token
  (compared in constant time over UTF-8 bytes). `OK` = authenticated; any call
  before a successful token frame is refused. With no token, every frame is a call.
- **Call.** The payload is one single-key JSON object: the key is the method, the
  value is its args. The server (1) parses it (`parse_call`), (2) checks the key is
  in the `COMMANDS` allowlist, (3) **validates the args** (see below), and (4)
  translates it into the matching `Core` call — the same methods the GUI's buttons
  call. Steps 2–4 are the single `run()` choke point both transports share.
- **Reply.** One line, `__ZMART_OK__` + the JSON result. On a bad payload, an
  unknown method, a rejected value, or a handler error, the reply is the error text
  (no marker line), and the connection stays open.

### Input validation (`_validate`)

Beyond "known method," the server checks each call's **args** before touching the
instrument, and returns a *specific* error if they're off:

- **shape** — `targets`/`deltas` must be an object of `axis → number`, `settings`
  an object, etc. (`"targets" must be a non-empty object of axis -> number`).
- **allowed options** — `filter`/`zoom`/`laser`/`shutterconfig` are checked against
  the **live `cfg`** (`filter` ∈ `filterdict`, `zoom` ∈ `zoomdict`, `laser` ∈
  `laserdict`, `shutterconfig` ∈ `shutteroptions`); `intensity` ∈ `[0, 100]`.
- **range** — `move_absolute` targets are checked against optional per-axis soft
  limits, set via `MESOSPIM_RS_LIMITS` (a JSON object `{"x": [lo, hi], …}` or a
  path to one). Unset → no soft limit (the Core's own hardware bound is the backstop).

This is what makes the LLM lane safe: a bad *value* (not just a bad name) is
refused at the door, with a message the caller can act on.

## MCP (LLM) front end — a separate HTTP process

An LLM can drive the same allowlist over **MCP** (JSON-RPC 2.0, the MCP *Streamable
HTTP* transport). Unlike the framed TCP server (which runs inside the Core), the MCP
server is a **small standalone process** (`mesoSPIM_RemoteControl_Servers.py`'s
`main`, entry point `mesospim-mcp-server`, `--port` default `42100`) that **forwards**
each `tools/call` to the TCP server as a framed named call. Both lanes therefore
land on the *same* validated `run()` dispatch. The client POSTs one JSON-RPC message
to `/mcp` and gets one back:

- `initialize` → server info + `{"capabilities": {"tools": {}}}`.
- `tools/list` → one tool per `COMMANDS` entry (the allowlist *is* the tool list),
  each with an argument hint in its `description`.
- `tools/call` `{name, arguments}` → forwarded to the TCP server; returns its JSON as
  MCP text content (`isError` on a rejected value / handler error, not a crash).
- a notification (no `id`) → `202 Accepted`, no body. Non-`/mcp` path → `404`.

**HTTP safety**: bind `127.0.0.1`; require the token as `Authorization: Bearer
<token>` (constant-time) when one is set; and **reject any non-localhost `Origin`**
so a web page in the operator's browser can't drive the instrument
(DNS-rebinding / CSRF). An LLM and a script reach the exact same validated surface;
neither can invoke anything outside `COMMANDS`.

## Getting a result back

The reply is already a clean line: `__ZMART_OK__<json>`. Extract it with the regex
`^__ZMART_OK__(.*)$` and parse the JSON. If no such line is present, the whole
reply text is the error.

## Why this shape (vs. running scripts)

Running arbitrary client Python (e.g. via `Core.execute_script`) is maximally
flexible but is **arbitrary remote code execution** on the acquisition PC. The
named-call form gives the same control surface (every `Core` operation the driver
needs) while the server only ever does a dict lookup + a fixed call — so a client
can never run code that is not in the allowlist. See `COMMANDS` in
`mesoSPIM_RemoteControl_ValidateAndRunCommands.py`.

## Errors

- Bad framing (a non-integer length line) → the server sends a short error frame
  and closes the connection.
- A bad payload / unknown method / rejected value / handler that raises → the error
  text is the reply; the connection stays open.
- A second concurrent client → the NEW connection wins: the server drops the old
  socket and serves the newcomer (which must still pass the token gate). One client
  at a time, but a crashed client's half-open socket can never hold the server hostage.
