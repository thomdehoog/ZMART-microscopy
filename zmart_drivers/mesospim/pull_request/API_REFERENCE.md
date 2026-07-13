# Remote Control — JSON API reference

Every input the server accepts over **TCP** or **MCP**. Generated to match
`mesoSPIM_RemoteControl_ValidateAndRunCommands.py` (`COMMANDS`, `_validate`); 54 commands.

## Wire

- **TCP** — one length-framed line `"<byte-count>\n"` + `{"<command>": {args}}`; reply
  `__MESOSPIM_OK__<json-result>` or an `error: <msg>` line. If a token is set, the first
  frame must be it (`OK` / `AUTH-FAILED`).
- **MCP** — `POST /mcp` a JSON-RPC `tools/call` with `{"name":"<command>","arguments":{args}}`;
  reply `result.content[0].text` is the same `<json-result>` (or `{"error":…}` with
  `isError:true`). `Authorization: Bearer <token>`, `Origin` must be localhost.
- Same command, same args, same validation, same result on both lanes.

Every accepted mutating command also returns `accepted: true`, `accepted_command`, and an
`operation` object containing `id`, `command`, and `status`. A synchronous call returns as
`completed`; a scheduled call returns as `processing` and reaches `completed` only after
its matching Core completion event. While one operation is `processing` or `stopping`, a
second mutation is rejected with the active command and operation ID. Reads, progress
polling, and emergency stop/shutter commands remain available over either transport.

## Conventions

- **Axes**: `x y z f theta`. Positions/targets/deltas are **µm** (`x y z f`) / **degrees** (`theta`).
- `arg?` = optional, `=v` = default. Types: `num` `int` `str` `bool` `[…]` list `{…}` object.
- `∈ name` = value must be one the live config lists (read them with `get_config` /
  `get_limits` / `get_capabilities` — they are machine-specific).
- Every arg is validated **before** the Core is touched; a bad type / option / range is
  refused with a message that names the limit (see [Validation](#validation)).

## Read / introspection — no side effects

| Command | Args | Returns |
|---|---|---|
| `hello` | — | `app, version, protocol, state` |
| `ping` | — | `pong, state` |
| `get_state` | — | `state, position{}, laser, intensity, filter, zoom, shutterconfig, etl_l/r_amplitude/offset` |
| `get_position` | — | `x, y, z, f, theta` |
| `get_state_all` | `keys?: [str]` | `{key: value}` (all state keys if omitted) |
| `get_config` | — | `app, version, lasers[], filters[], zooms[], shutter_configs[], axes[], camera{pixels_x,pixels_y}` |
| `get_limits` | — | `stage{}, camera{}, startup{}, enforced{axes{axis:[lo,hi]|null}, parameters{key:{type,options,range}}}` |
| `get_capabilities` | — | `commands[], axes[], position_keys{}, settable_state_keys[], modes[], acquisition_fields[]` |
| `get_progress` | — | `state, current_plane, total_planes, current_acquisition, total_acquisitions, operation` |
| `self_test` | — | `ok, report[]` — re-proves the loaded limits against a mock Core; never moves hardware |

## Motion

| Command | Args | Returns |
|---|---|---|
| `move_absolute` | `targets: {axis→num}` | `{}` — range-checked per axis |
| `move_relative` | `deltas: {axis→num}` | `{}` |
| `zero` | `axes?: [axis]` (omit = all) | `{}` |
| `unzero` | `axes?: [axis]` (omit = all) | `{}` |
| `stop` | — | `{}` — interrupt movement |
| `stop_activity` | — | `state` — stop live / acquisition |

## Optics & state

| Command | Args | Returns |
|---|---|---|
| `set_state` | `settings: {key→value}` | `{}` — each key ∈ `settable_state_keys`; options/ranges enforced |
| `set_filter` | `filter: str ∈ filters`, `wait?: bool=false` | `{}` |
| `set_zoom` | `zoom: str ∈ zooms`, `wait?: bool=true`, `update_etl?: bool=true` | `{}` |
| `set_laser` | `laser: str ∈ lasers`, `wait?: bool=false`, `update_etl?: bool=true` | `{}` |
| `set_intensity` | `intensity: num 0–100`, `wait?: bool=false` | `{}` |
| `set_shutterconfig` | `shutterconfig: str ∈ shutter_configs` | `{}` |
| `set_camera` | one+ of `camera_exposure_time, camera_line_interval, camera_delay_%, camera_pulse_%, camera_display_live_subsampling, camera_display_acquisition_subsampling, camera_sensor_mode, camera_binning` | `{}` |
| `set_etl` | one+ of `etl_{l,r}_{delay_%,ramp_rising_%,ramp_falling_%,amplitude,offset}` | `{}` |
| `set_galvo` | one+ of `galvo_{l,r}_{frequency,amplitude,offset,duty_cycle,phase}, galvo_amp_scale_w_zoom` | `{}` |
| `set_laser_timing` | one+ of `laser_{l,r}_{delay_%,pulse_%}` | `{}` |
| `reload_etl_config` | `path?: str`, `wait?: bool=true` | ETL readback (`ETL_cfg_file, laser, zoom, etl_*`) |
| `update_etl_from_laser` | `laser?: str`, `wait?: bool=true` | ETL readback |
| `update_etl_from_zoom` | `zoom?: str`, `wait?: bool=true` | ETL readback |

## Shutters, modes, sample

| Command | Args | Returns |
|---|---|---|
| `open_shutters` | — | `shutterstate` |
| `close_shutters` | — | `shutterstate` |
| `snap` | `write?: bool=true`, `laser_blanking?: bool=true` | `scheduled` |
| `set_mode` | `mode: str ∈ modes` | `scheduled, mode` (or `mode` for `idle`) |
| `start_live` | — | `scheduled, mode` |
| `start_visual_mode` | — | `scheduled, mode` |
| `start_lightsheet_alignment_mode` | — | `scheduled, mode` |
| `load_sample` | — | `{}` |
| `unload_sample` | — | `{}` |
| `center_sample` | — | `{}` |
| `execute_stage_program` | — | `{}` |
| `save_etl_config` | — | `{}` |

## Acquisition

| Command | Args | Returns |
|---|---|---|
| `get_acquisition_list` | — | `acquisitions[]` |
| `set_acquisition_list` | `acquisitions: [{…}]`, `selected_row?: int` | `count` |
| `run_acquisition_list` | — | `scheduled` |
| `run_selected_acquisition` | `row?: int` | `scheduled, row` |
| `preview_acquisition` | `row?: int`, `z_update?: bool=true` | `scheduled, row` |
| `acquire_start` | `acquisition: {…}` (see `acquisition_fields`) | `started, scheduled, files[], planes, pixels[x,y]` |
| `stat_files` | `files: [path]` | `missing[], sizes{path:bytes}` |
| `acquire_finish` | — | `state` |
| `get_disk_space` | `acquisitions?: [{…}]` (omit = current list) | `free_bytes, required_bytes` |
| `check_motion_limits` | `acquisitions?: [{…}]` (omit = current list) | `outside_limits[]` |
| `time_lapse_start` | `timepoints?: int=1`, `interval_sec?: int=0` | `started` |
| `time_lapse_stop` | — | `stopped` |
| `procedure` | `name: str` | *(error: not implemented server-side)* |

## Enumerations

Fixed lists (structural). Value **options** for `filter`/`zoom`/`laser`/`shutterconfig` are
**not** here — they come from the live config; read them with `get_config`.

- **axes**: `x y z f theta`
- **position_keys**: `x→x_pos y→y_pos z→z_pos f→f_pos theta→theta_pos`
- **modes**: `live snap run_selected_acquisition run_acquisition_list preview_acquisition_with_z_update preview_acquisition_without_z_update idle lightsheet_alignment_mode visual_mode`
- **settable_state_keys** (for `set_state`): `filter zoom laser intensity shutterconfig state camera_exposure_time camera_line_interval samplerate sweeptime ETL_cfg_file etl_l_delay_% etl_l_ramp_rising_% etl_l_ramp_falling_% etl_l_amplitude etl_l_offset etl_r_delay_% etl_r_ramp_rising_% etl_r_ramp_falling_% etl_r_amplitude etl_r_offset galvo_l_frequency galvo_l_amplitude galvo_l_offset galvo_l_duty_cycle galvo_l_phase galvo_r_frequency galvo_r_offset galvo_r_duty_cycle galvo_r_phase laser_l_delay_% laser_l_pulse_% laser_r_delay_% laser_r_pulse_% camera_delay_% camera_pulse_% camera_display_live_subsampling camera_display_acquisition_subsampling camera_sensor_mode camera_binning galvo_amp_scale_w_zoom`
- **acquisition_fields** (for `acquisition` / `acquisitions[]`): `x_pos y_pos z_start z_end z_step planes rot f_start f_end laser intensity filter zoom shutterconfig folder filename image_writer_plugin etl_l_offset etl_l_amplitude etl_r_offset etl_r_amplitude processing`

## Validation

A value is refused (with a message that names the limit) if it fails any of:

- **type** — `num` (JSON booleans are **not** numbers) or `str`, per parameter.
- **option** — `filter zoom laser shutterconfig` must be one the live config allows
  (checked in `set_*`, `set_state`, and inside an `acquisition`).
- **range**
  - absolute targets and relative destinations (`move_absolute`, `move_relative`) — the loaded config's envelope `cfg.stage_parameters`
    (`{axis}_min`/`{axis}_max`); `MESOSPIM_RS_LIMITS` (`{"x":[lo,hi],…}` or a path) can
    tighten an axis; an axis with no limit is unchecked (see `get_limits.enforced.axes`).
  - `intensity` and every `%` parameter (`*_delay_% *_pulse_% *_ramp_*_% *_duty_cycle`) ∈ `0–100`.
- **string, no options** (`state ETL_cfg_file camera_sensor_mode camera_binning`) — type only.
- Any parameter not listed above with a limit is **type-checked only** (`range: null` in
  `get_limits.enforced.parameters`).

Unknown command → `error` (allowlist reject). Unknown `set_state` key → `error`. The limits
themselves are read-only — no command changes them.
