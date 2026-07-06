# What the driver sends

The server accepts **named calls, not code**. Every request is one single-key
JSON object — the key is the method, the value is its args:

```json
{"<method>": {args}}
```

The server looks `<method>` up in a **fixed allowlist** — the `COMMANDS` table in
[`connection/command_api.py`](connection/command_api.py) — and runs the matching
mesoSPIM Core call. A method not in the table never runs. No client Python is ever
`exec`d. The reply is one line, `__ZMART_OK__<json>`, read back with
`^__ZMART_OK__(.*)$`; on error the reply is the error text (no marker line), which
the client surfaces as the error.

> The mesoSPIM server also exposes this same allowlist over **MCP (HTTP)** for LLMs
> (`tools/list` = these methods, `tools/call` runs one). This driver uses the framed
> TCP named-call lane; the LLM lane is the identical dispatch behind a JSON-RPC/HTTP envelope.

## Writes — the only calls that touch the instrument

| example | the Core call it runs |
|---|---|
| `{"move_absolute": {"targets": {"x": 1000, "z": -50}}}` | `core.move_absolute({axis+'_abs': v}, wait_until_done=True)` |
| `{"move_relative": {"deltas": {"z": 5}}}` | `core.move_relative({axis+'_rel': v}, wait_until_done=True)` |
| `{"set_state": {"settings": {…}}}` | `core.sig_state_request_and_wait_until_done.emit(settings)` |
| `{"zero": {"axes": ["x","y"]}}` | `core.zero_axes([...])` |
| `{"stop": {}}` | `core.sig_stop_movement.emit()` |
| `{"acquire_start": {"acquisition": {…}}}` | swap in a one-item `acq_list`, `core.start(row=0)` |
| `{"acquire_finish": {}}` | restore the operator's `acq_list` |

## `set_state` is the whole settings surface

`set_state` is a **generic passthrough**: its `settings` object is sent to the
exact signal the GUI uses (`sig_state_request_and_wait_until_done`), which accepts
**any mesoSPIM state key**. So every instrument option is controllable through this
one call — no per-option command needed. The keys mesoSPIM v1.20.0 exposes:

| key | what it controls |
|---|---|
| `filter` | emission filter (name from `cfg.filterdict`) |
| `zoom` | zoom / objective (name from `cfg.zoomdict`) |
| `laser` | active laser line (name from `cfg.laserdict`) |
| `intensity` | laser intensity, 0–100 % |
| `shutterconfig` | light-sheet side: `Left` / `Right` / `Both` |
| `etl_l_amplitude`, `etl_r_amplitude` | ETL sweep amplitude, left / right sheet |
| `etl_l_offset`, `etl_r_offset` | ETL focus offset, left / right |
| `galvo_l_amplitude`, `galvo_r_amplitude` | galvo sweep amplitude, left / right |
| `galvo_l_frequency`, `galvo_r_frequency` | galvo frequency, left / right |
| `samplerate`, `sweeptime` | waveform sample rate / sweep time |
| `camera_exposure_time`, `camera_line_interval` | camera timing |
| `state` | run state (`idle` / `live` / …) |

Any other key mesoSPIM's state carries works too — `set_state` does not filter the
keys, mesoSPIM does. The typed convenience wrappers in
[`commands/commands.py`](commands/commands.py) (`set_filter`, `set_zoom`,
`set_laser`, `set_intensity`, `set_shutter`, `set_etl`) all just call `set_state`.

## Reads — build a result from `core`, no hardware effect

| method | what it reads |
|---|---|
| `hello` / `ping` | app / version / state |
| `get_state` | `state` (position + all settings above) |
| `get_position` | `state['position']` |
| `get_config` | `cfg` (`laserdict`, `filterdict`, `zoomdict`, `shutteroptions`, `camera_*`) |
| `get_progress` | `state` progress keys |
| `stat_files` | `os.path.isfile` / `getsize` on `args['files']` (disk only) |

`procedure` is advertised but not implemented server-side: it raises, which the
client turns into a NAK.

## Filtering it (security)

The call is data with a fixed shape, so the allowlist is trivial and lives in the
server: `COMMANDS.get(method)` — unknown ⇒ rejected before anything runs. There is
no exec path in the server at all. Regenerate the accepted list with:

```
python -c "from mesospim.connection import command_api as c; print(list(c.COMMANDS))"
```
