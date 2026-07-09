# Bench run — validating the driver against a live mesoSPIM

Everything offline is green (143 tests, incl. an end-to-end pass of the real
patched server over sockets against a *fake* Core). The one unproven link is a
**real mesoSPIM Core**. This is the checklist to close it.

Need: a machine with the mesoSPIM-control app + a display, running in `-D` demo
mode (all `Demo` backends, no hardware). Effectively Windows.

---

## 1. Apply the server patch and start it

```bash
# in a mesoSPIM-control checkout
git am /path/to/zmart_drivers/mesospim/pull_request/0001-Add-optional-remote-scripting-server-Tools-Remote-Sc.patch
```

Launch mesoSPIM in demo mode, then **Tools → Remote Scripting… → Start**.
Note the **token** it pre-fills (host `127.0.0.1`, port `42000` by default).

**Range limits are on by default.** Type + option (enum) validation is always on, and
range checking uses the per-axis travel envelope of the config you loaded at startup
(`cfg.stage_parameters`) — so no setup is needed. To *tighten* an axis below the config
(a soft limit), export an override before launching:

```bash
export MESOSPIM_RS_LIMITS='{"z":[-5000,5000]}'   # only overrides z; the rest stay at cfg
```

Verify with an out-of-range `move_absolute` — it should return an "outside the allowed
range" error **naming the limit**, and the stage should not move. `get_limits` reports the
exact rules in force (an axis with no limit shows `null`).

## 2. Run the gated integration suite (framed TCP lane)

From the ZMART repo, pointed at the running server:

```bash
MESOSPIM_HOST=127.0.0.1 MESOSPIM_PORT=42000 MESOSPIM_TOKEN=<token> \
  python -m pytest zmart_drivers/mesospim/tests -m integration -v
```

Add `MESOSPIM_ALLOW_ACQUIRE=1` to also run a real demo capture through the image
writer. (The full checklist of Core bindings to confirm is in
[`TODO.md`](TODO.md) §1.)

## 3. Smoke-test the MCP / HTTP lane (LLM door)

Same server, HTTP instead of framed TCP:

```bash
curl -s http://127.0.0.1:42000/mcp \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Expect a JSON-RPC result whose `tools` array is the command allowlist. Try a
`tools/call` too:

```bash
curl -s http://127.0.0.1:42000/mcp -H "Authorization: Bearer <token>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_state","arguments":{}}}'
```

Safety checks (should fail closed): a wrong/absent Bearer → `401`; a request with
`Origin: http://evil.example` → `403`.

To wire an actual LLM client (Claude Desktop, etc.), point it at the URL
`http://127.0.0.1:42000/mcp` with the Bearer token as a header.

---

## What's most likely to need adjusting

The offline fakes are verified against mesoSPIM-control v1.20.0, but the real
Core is the judge. Watch these (all live in
[`pull_request/`](pull_request/) `mesoSPIM_RemoteScripting.py`, `COMMANDS` table):

- **`acquire_start`** — the acquisition entry point (`core.start(row=0)`) and the
  image-writer's `folder`/`filename` path. Most likely to differ per version.
- **`set_state`** — that `sig_state_request_and_wait_until_done.emit(settings)` is
  the right signal and accepts the keys you send.
- **`get_config` / `get_state`** — the `cfg.*dict` and `state[...]` key names.

If any differ, tell me exactly what the real Core does (the method name, the
signal, the state key) and I'll fix the handler — offline tests will re-lock it.
```
