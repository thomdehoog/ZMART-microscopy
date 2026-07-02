# Remote scripting protocol

The wire protocol for the mesoSPIM **Remote Scripting** server
(`mesoSPIM_RemoteScripting.py`). Deliberately tiny: it is a transport for
"run this script, give me the console output," not a control vocabulary.

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
client ──▶  frame(<python script>)
       ◀──  frame(<console output during the run>)
```

- **Auth.** When the server has a token, the **first** frame must be that token
  (compared in constant time over UTF-8 bytes). `OK` = authenticated; any script
  before a successful token frame is refused. When the server has no token, every
  frame is a script from the start.
- **Script.** The payload is Python run in the live Core context — the same as
  mesoSPIM's Script Window, so `self` is the `mesoSPIM_Core`. It may use the full
  mesoSPIM API (`self.move_absolute(...)`, `self.state[...]`, `self.cfg`, run an
  acquisition, …).
- **Reply.** The captured **stdout + stderr** produced while the script ran, as
  text. A script error is caught and its traceback is included in that text (the
  connection is not dropped).

## Getting a result back

There is no result format on purpose. To return data, have the script `print()`
it — e.g. a JSON line. Because the reply is the process console (and may include
concurrent output from other threads, as the Script Window console does),
delimit a machine-readable result with markers and extract between them:

```python
# client sends:
script = (
  "import json\n"
  "print('<<<RESULT>>>' + json.dumps({'x': self.state['position']['x_pos']}) + '<<<END>>>')\n"
)
# client parses the reply between <<<RESULT>>> ... <<<END>>>
```

## Errors

- Bad framing (a non-integer length line) → the server sends a short error frame
  and closes the connection.
- A script that raises → its traceback is in the returned text; the connection
  stays open.
- A second concurrent client → the NEW connection wins: the server drops the
  old socket and serves the newcomer (which must still pass the token gate).
  One client at a time, but a crashed client's half-open socket can never hold
  the server hostage.
