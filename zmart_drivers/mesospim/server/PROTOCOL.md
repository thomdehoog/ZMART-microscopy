# mesoSPIM command-server protocol (v1)

The ZMART mesoSPIM driver and the resident command-server script speak this
protocol over a localhost TCP socket. It is a **line-oriented JSON** protocol:
one JSON object per line, UTF-8, `\n`-terminated. The pure encode/parse lives in
[`mesospim/protocol.py`](../protocol.py) (MIT); the reference client is
[`mesospim/connection/client.py`](../connection/client.py) (MIT); the reference
server is [`mesospim_command_server.py`](mesospim_command_server.py) (GPL edge —
it uses the mesoSPIM `Core` API).

## Framing

- **Request:** `{"cmd": <str>, "args": {<object>}, "id": <int|null>}`
- **Reply (ok):** `{"ok": true, "data": {<object>}, "id": <int|null>}`
- **Reply (nak):** `{"ok": false, "error": <str>, "id": <int|null>}`

The server echoes the request `id` in its reply. One request/reply pair at a
time (the server lives in the Qt event loop and is single-client).

Units: linear axes (`x`, `y`, `z`, `f`) are **micrometers**; `theta` is
**degrees**. The server converts to mesoSPIM's internal units.

## Commands

### Session

| `cmd` | `args` | reply `data` |
|---|---|---|
| `hello` | – | `{app, version, protocol, state}` |
| `ping` | – | `{}` |
| `bye` | – | `{}` (server may close after) |

### Reads

| `cmd` | `args` | reply `data` |
|---|---|---|
| `get_state` | – | full state dict: `{state, position:{x,y,z,f,theta}, laser, intensity, filter, zoom, shutterconfig, etl_l_amplitude, etl_l_offset, etl_r_amplitude, etl_r_offset}` |
| `get_position` | – | `{x, y, z, f, theta}` |
| `get_config` | – | `{app, version, lasers:[{name,wavelength_nm}], filters:[str], zooms:[{name,pixel_size_um}], shutter_configs:[str], axes:[str], camera:{pixels_x,pixels_y}}` |
| `get_progress` | – | `{state, current_plane, total_planes, current_acquisition, total_acquisitions}` |

### Movement

Map directly onto the mesoSPIM `Core` movement signals.

| `cmd` | `args` | maps to | reply `data` |
|---|---|---|---|
| `move_absolute` | `{targets: {axis: value}}` | `sig_move_absolute` (`{axis_abs: v}`), waits | `{position}` |
| `move_relative` | `{deltas: {axis: delta}}` | `sig_move_relative` (`{axis_rel: v}`), waits | `{position}` |
| `zero` | `{axes: [str]}` | `zero_axes(list)` | `{}` |
| `stop` | – | `sig_stop_movement` | `{}` |

The axis keys are `x`, `y`, `z`, `f`, `theta`. The server translates each axis
to the mesoSPIM key (`x_abs`/`x_rel`, ..., `f_abs`/`f_rel`, `theta_abs`/…).

### State settings

| `cmd` | `args` | maps to | reply `data` |
|---|---|---|---|
| `set_state` | `{settings: {key: value}}` | `sig_state_request(settings)`, waits | `{applied}` |

`settings` keys are mesoSPIM state keys: `filter`, `zoom`, `laser`, `intensity`,
`shutterconfig`, `etl_l_amplitude`, `etl_l_offset`, `etl_r_amplitude`,
`etl_r_offset`, and any other `sig_state_request` key.

### Acquisition

| `cmd` | `args` | maps to | reply `data` |
|---|---|---|---|
| `acquire` | `{acquisition: {<Acquisition>}, acquisition_type: str}` | build `Acquisition`+`AcquisitionList`, snap (planes≤1) or run series | `{files:[path], planes, pixels:[x,y]}` |
| `run_acquisition_list` | `{acquisitions: [{<Acquisition>}]}` | run the whole list | `{files:[path], per_acquisition:[…]}` |
| `procedure` | `{name: str, args: {}}` | a named server-side procedure (e.g. `autofocus`) | procedure-specific |

An `<Acquisition>` object uses the real mesoSPIM field names: `x_pos`, `y_pos`,
`z_start`, `z_end`, `z_step`, `planes`, `rot`, `f_start`, `f_end`, `laser`,
`intensity`, `filter`, `zoom`, `shutterconfig`, `folder`, `filename`,
`etl_l_amplitude`, `etl_l_offset`, `etl_r_amplitude`, `etl_r_offset`. (These
match mesoSPIM-control's `Acquisition` keys; note the rotation key is `rot`.)

The `files` returned are the output files the mesoSPIM **image writer** wrote on
the acquisition PC. The default Tiff writer produces **one multi-page stack per
acquisition** (all planes in a single ImageJ TIFF), so `acquire` returns a single
path and `run_acquisition_list` returns one path per acquisition. The ZMART
driver's `save()` relocates them into the canonical output layout — it does not
re-encode pixels.

## Errors

Any request the server cannot honour returns `{"ok": false, "error": "<why>"}`.
Unknown `cmd`, a malformed `args`, an out-of-range move the mesoSPIM stage
rejects, or an acquisition failure are all NAKs. Transport-level failures
(dropped socket, timeout) are the client's concern and are retried there.

## Versioning

`hello.data.protocol` carries the integer protocol version (currently `1`). A
client should refuse a server whose major protocol version it does not know.
