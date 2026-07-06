# What the driver injects

Every command the driver sends is **one Python script with the same envelope**;
only the `# zmart-cmd:` name, the `_a = {...}` args, and one or two body lines
change. This is the complete list of what the ZMART client can run in the Remote
Scripting window — nothing else is ever sent.

## The envelope (identical for every command)

```python
# zmart-cmd: <name>
import json, traceback
try:
    _a = { ...args as a plain literal... }
    <body>                                   # the per-command line(s) below
    print('__ZMART_OK__' + json.dumps(_result))
except Exception:
    print('__ZMART_ERR__' + json.dumps(traceback.format_exc()))
```

The reply is a single line: `__ZMART_OK__<json>` on success, or
`__ZMART_ERR__<json>` (a traceback string) if the body raised. Extract it with
`^__ZMART_(OK|ERR)__(.*)$`.

## Reads — no hardware effect (just build `_result` from `self`)

| `# zmart-cmd:` | what it reads |
|---|---|
| `ping` | `self.state['state']` |
| `hello` | `self.cfg.version`, `self.state['state']` |
| `get_state` | `self.state` (position + settings) |
| `get_position` | `self.state['position']` |
| `get_config` | `self.cfg` (`laserdict`, `filterdict`, `zoomdict`, `shutteroptions`, `camera_*`) |
| `get_progress` | `self.state` progress keys |
| `stat_files` | `os.path.isfile` / `getsize` on the paths in `_a['files']` (disk only, no Core) |

## Writes — the *only* lines that touch the instrument

| `# zmart-cmd:` | the exact call |
|---|---|
| `move_absolute` | `self.move_absolute({axis+'_abs': v, ...}, wait_until_done=True)` |
| `move_relative` | `self.move_relative({axis+'_rel': v, ...}, wait_until_done=True)` |
| `set_state` | `self.sig_state_request_and_wait_until_done.emit(settings)` — filter / zoom / laser / intensity / shutter / ETL |
| `zero` | `self.zero_axes([...])` |
| `stop` | `self.sig_stop_movement.emit()` |
| `acquire_start` | set `self.state['acq_list'] = AcquisitionList([Acquisition])`, then `self.start(row=0)` |
| `acquire_finish` | restore the operator's `self.state['acq_list']` |
| `procedure` | `raise` (not implemented server-side) — no effect |

That is the whole surface: a handful of `self.` calls (`move_absolute`,
`move_relative`, `zero_axes`, `sig_stop_movement`,
`sig_state_request_and_wait_until_done`, `start`) plus `acq_list` bookkeeping.
Everything else is a read.

## Filtering it (security)

Because the shape is fixed, a server-side allowlist is easy: accept a script only
if its first line is `# zmart-cmd: <known name>` **and** its body matches that
command's template (only `_a` differs). Anything else is not a ZMART command and
can be rejected before it runs. See the templates in
[`connection/scripts.py`](connection/scripts.py); regenerate this list with
`python -c "from mesospim.connection import scripts; [print(scripts.build_script(c, {})) for c in scripts.known_commands()]"`.
