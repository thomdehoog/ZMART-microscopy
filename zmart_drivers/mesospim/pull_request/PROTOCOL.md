# Remote scripting protocol

The wire protocol for the mesoSPIM **Remote Scripting** server
(`mesoSPIM_RemoteScripting.py`). Deliberately tiny: the server accepts **named
calls, not code** — it validates a small JSON message and translates it into one
`mesoSPIM_Core` call from a fixed allowlist. No client Python is ever run.

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
  value is its args. The server (1) parses it, (2) validates it is a single-key
  object whose key is in the `COMMANDS` allowlist, and (3) translates it into the
  matching `Core` call — the same methods the GUI's own buttons call
  (`move_absolute`, `set_state`, an acquisition, a state read, …).
- **Reply.** One line, `__ZMART_OK__` + the JSON result. On a bad payload, an
  unknown method, or a handler error, the reply is the error text (no marker line),
  and the connection stays open.

## MCP (LLM) front end

The same socket also accepts **MCP** (JSON-RPC 2.0) — for an LLM instead of a
script. A frame whose object has `"jsonrpc": "2.0"` is routed to the MCP handler;
anything else is a named call (above). Both land on the *same* allowlist dispatch:

- `initialize` → server info + `{"capabilities": {"tools": {}}}`.
- `tools/list` → one tool per `COMMANDS` entry (the allowlist *is* the tool list),
  each with an argument hint in its `description`.
- `tools/call` `{name, arguments}` → runs that one method and returns its JSON as
  MCP text content (`isError` set on failure). Unknown tool = an error result, not
  a crash.
- a notification (no `id`, e.g. `notifications/initialized`) gets no reply.

So an LLM and a script reach the exact same validated call surface; neither can
invoke anything outside `COMMANDS`.

## Getting a result back

The reply is already a clean line: `__ZMART_OK__<json>`. Extract it with the regex
`^__ZMART_OK__(.*)$` and parse the JSON. If no such line is present, the whole
reply text is the error. (The `__ZMART_OK__` marker survives even if another thread
prints to the console, as the Script Window console can.)

## Why this shape (vs. running scripts)

An earlier draft of this feature ran arbitrary client Python via
`Core.execute_script` and returned the console. That is maximally flexible but is
**arbitrary remote code execution** on the acquisition PC. The named-call form
gives the same control surface (every `Core` operation the driver needs) while the
server only ever does a dict lookup + a fixed call — so a client can never run code
that is not in the allowlist. See `COMMANDS` in `mesoSPIM_RemoteScripting.py`.

## Errors

- Bad framing (a non-integer length line) → the server sends a short error frame
  and closes the connection.
- A bad payload / unknown method / handler that raises → the error text is the
  reply; the connection stays open.
- A second concurrent client → the NEW connection wins: the server drops the
  old socket and serves the newcomer (which must still pass the token gate).
  One client at a time, but a crashed client's half-open socket can never hold
  the server hostage.
