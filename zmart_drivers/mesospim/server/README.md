# mesoSPIM resident command server (GPL edge)

`mesospim_command_server.py` is the small resident script that gives
mesoSPIM-control the external socket API it lacks, so the MIT ZMART driver can
drive it from another process. It is the **only GPL-3.0 file** in the mesoSPIM
driver: it uses the GPL mesoSPIM `Core` API and imports nothing from ZMART. The
ZMART client speaks to it over a localhost socket (see [`PROTOCOL.md`](PROTOCOL.md)),
so the process boundary keeps ZMART MIT (rationale in the driver
[`README.md`](../README.md) → Licensing).

## How it works

mesoSPIM-control has no headless mode and no RPC, but its Core menu has a
**Script Window** whose slot literally `exec()`s your script with `self` (the
`mesoSPIM_Core`) in scope. This script uses that hook to:

1. open a `QTcpServer` on `127.0.0.1:42000`, parented to the Core (so it
   outlives the script's `exec()` frame);
2. **`QTimer`-poll** the socket every ~20 ms — non-blocking, so the Qt event
   loop never freezes (the same pattern as the Nikon `NkSocketServerDemo.mac`
   `WM_TIMER` poll);
3. translate each JSON request line into a Core action (`move_absolute`,
   `sig_state_request`, run an `Acquisition`) or a state read, and write back a
   JSON reply line.

The Core-touching calls are grouped in one class, `_CoreBridge`, so they are the
single surface to confirm against your mesoSPIM version.

## Loading it

1. Start mesoSPIM-control (real hardware, or **`-D` demo mode** for a
   hardware-free run: `python mesoSPIM_Control.py -D`).
2. Core menu → **Script Window** → open `mesospim_command_server.py` → **Run**.
3. You should see `[mesospim-cmd-server] listening on 127.0.0.1:42000`.
4. From ZMART: `mesospim.connect({"host": "127.0.0.1", "port": 42000})`.

## Validating offline (recommended before any bench use)

mesoSPIM `-D` demo mode runs the whole app with Demo backends — no camera,
stages, lasers, or DAQ. Load the server there and run the ZMART round-trip:

```bash
python mesoSPIM_Control.py -D          # terminal 1: mesoSPIM in demo mode + Script Window → Run this file
python -m pytest zmart_drivers/mesospim/tests -m integration   # terminal 2 (see tests/)
```

This is unique among the ZMART drivers: the whole control loop can be exercised
against the **real acquisition software** with no hardware.

## Adapting to your instrument

The bridge follows mesoSPIM-control **v1.20.0** names. Confirm these against your
installed version in demo mode and adjust in `_CoreBridge` only:

- `core.move_absolute(sdict, wait_until_done=True)` / `core.move_relative(...)`
  and the `{axis}_abs` / `{axis}_rel` state keys.
- `core.sig_state_request_and_wait_until_done` for settings.
- The `Acquisition` run entrypoint and how the image-writer's output path is
  resolved (`_written_files`) — the most site-specific part.
- The config attribute names in `_CoreBridge.config()` / `_camera()`.

## Upstreaming

The cleanest long-term home for this file is the mesoSPIM project itself (a
first-class "command server" script, Zurich-local and community-run), so it is a
script mesoSPIM *ships and runs* rather than a patch anyone has to maintain.
