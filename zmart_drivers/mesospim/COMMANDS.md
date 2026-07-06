# What the driver sends

Restricted Remote Scripting carries **named calls, not code**. Every request the
driver sends is one JSON object:

```json
{"call": "<name>", "args": {...}}
```

The server looks `<name>` up in a **fixed allowlist** — the `COMMANDS` table in
[`connection/command_api.py`](connection/command_api.py) — and runs the matching
mesoSPIM Core call. A name not in the table never runs. No client Python is ever
`exec`d. The reply is one line, `__ZMART_OK__<json>`, read back with
`^__ZMART_OK__(.*)$`; on error the reply is the traceback text (no marker line),
which the client surfaces as the error.

## Writes — the only calls that touch the instrument

| `call` | `args` | the Core call it runs |
|---|---|---|
| `move_absolute` | `{targets: {x, y, …}}` | `core.move_absolute({axis+'_abs': v}, wait_until_done=True)` |
| `move_relative` | `{deltas: {z, …}}` | `core.move_relative({axis+'_rel': v}, wait_until_done=True)` |
| `set_state` | `{settings: {filter, zoom, laser, …}}` | `core.sig_state_request_and_wait_until_done.emit(settings)` |
| `zero` | `{axes: [...]}` | `core.zero_axes([...])` |
| `stop` | `{}` | `core.sig_stop_movement.emit()` |
| `acquire_start` | `{acquisition: {...}}` | swap in a one-item `acq_list`, `core.start(row=0)` |
| `acquire_finish` | `{}` | restore the operator's `acq_list` |

## Reads — build a result from `core`, no hardware effect

| `call` | what it reads |
|---|---|
| `hello` / `ping` | app / version / state |
| `get_state` | `state` (position + settings) |
| `get_position` | `state['position']` |
| `get_config` | `cfg` (`laserdict`, `filterdict`, `zoomdict`, `shutteroptions`, `camera_*`) |
| `get_progress` | `state` progress keys |
| `stat_files` | `os.path.isfile` / `getsize` on `args['files']` (disk only) |

`procedure` is advertised but not implemented server-side: it raises, which the
client turns into a NAK.

## Filtering it (security)

The call is data with a fixed shape, so the allowlist is trivial and lives in the
server: `COMMANDS.get(call)` — unknown ⇒ rejected before anything runs. Compare
with the old injected-script model, where the server `exec`d arbitrary client
Python and the safety net was a regex over script text. Regenerate the accepted
list with:

```
python -c "from mesospim.connection import command_api as c; print(c.known_commands())"
```
