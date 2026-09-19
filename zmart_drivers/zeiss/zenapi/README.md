# zenapi — ZEISS ZEN driver for ZMART

> **Status (2026-09-19): aligned with the real ZEN API, validated against a fake
> gateway.** The driver now speaks the protocol of ZEISS's published `zen_api`
> packages (2025.10.1 for ZEN 3.13 and 2026.05.1 for ZEN 3.14) and runs the full
> ZMART round trip — connect, set origin, move, **acquire**, state, procedures —
> over the real generated classes and a real TLS connection to
> [its own fake ZEN API gateway](#working-without-a-microscope-the-fake-gateway).
> Offline suite: 74 tests without any ZEISS package plus 19 against the fake
> gateway. **Not yet run against ZEN itself**: a ZEISS simulator has been
> requested; the [hand-over checklist](#when-the-zeiss-simulator-or-the-microscope-arrives)
> says what that first run has to confirm.

This driver lets ZMART drive a ZEISS microscope through **ZEN** (blue edition or
ZEN core). It is a sibling of the Leica, mesoSPIM and Nikon drivers and speaks
the same neutral `zmart_controller` interface, so a workflow written for one of
them runs here unchanged.

- **Author:** Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com
- **License:** MIT

## How it works (one picture)

```
  your Python (ZMART)                          the ZEN computer
  ┌──────────────────────────┐  gRPC over TLS  ┌──────────────────────────────┐
  │ zenapi package           │ ─ + control ──▶ │ ZEN API Gateway              │
  │  readers / commands      │     token       │  (checks the token, forwards)│
  │  zen_zmart_adapter       │ ◀────────────── │        │                     │
  └──────────────────────────┘                 │        ▼                     │
        uses ZEISS's zen_api wheel             │ ZEN (blue / core)            │
        (the generated service classes)        │  stage, focus, objectives,   │
                                               │  experiments -> CZI files    │
                                               └──────────────────────────────┘
```

ZEN can be controlled from the outside through the **ZEN API**: a set of
services (stage, focus, objective changer, experiments, autofocus, ...) that
ZEN offers over the network using gRPC. A small separate program, the **ZEN API
Gateway**, sits in front of ZEN: it encrypts the connection and checks that
every call carries the gateway's *control token*, a password it generates.
ZEISS publishes the Python classes for those services as a `zen_api` package,
and that package is what this driver uses to talk to ZEN.

Two things are good to know before you start:

- **ZEN keeps the imaging settings.** What to image (channels, exposure,
  Z-stack, tiles) is a ZEN *experiment* that you set up and save in ZEN as you
  normally would. The driver loads an experiment by name and runs it; it does
  not build experiments itself.
- **ZEN writes the images.** Every acquisition becomes one CZI file in ZEN's
  image output folder on the ZEN computer. The driver asks where that folder
  is and copies the file into the ZMART output folder. When ZMART runs on
  another computer, that folder must be reachable as a network share.

## Working without a microscope: the fake gateway

The driver ships with a **fake ZEN API gateway**. It is a small server that
implements the ZEN API services this driver uses, on top of the real service
definitions from the `zen_api` package, with the same TLS and token check as
the real gateway. Behind it is an imaginary microscope: an XY stage, a focus
drive, three objectives, a few saved experiments, and an image folder where
every acquisition is written as a placeholder `.czi` file. It is meant to
stand in until ZEISS's simulator or a real microscope is available, so that
the switch is only a change of `config.ini`.

```
pip install -r zmart_drivers/zeiss/zenapi/requirements.txt   # grpclib + the zen_api wheel
cd zmart_drivers/zeiss
python -m zenapi.simulator
```

It prints where it listens and writes a ready `config.ini` (by default under
`fake_zen_gateway/`). Everything in the next sections then works against it.
Useful options: `--slow` makes moves and frames take a little time,
`--supervised` refuses controlling calls the way ZEN does before an operator
enables *Unsupervised API Mode* (see [Setting it up](#setting-it-up-on-the-microscope-pc)).

What it fakes faithfully: the request and response messages, blocking
behaviour (`MoveTo` and `RunExperiment` return when done), the status stream
and its rule that you can only subscribe while an experiment is active,
`OUT_OF_RANGE` for a move beyond the stage, the missing/wrong token errors and
the supervised-mode refusal. What it does not: pixels (the CZI is a
placeholder), optics, timing of a real stage, and the many ZEN services this
driver does not use (they answer *unimplemented*).

## Setting it up on the microscope PC

1. **Install the ZEN API toolkit and gateway** with the ZEISS Microscopy
   Installer (ZMI) and activate the *ZEN API* toolkit in ZEN. Needs ZEN 3.11
   or newer; the packages here were made for ZEN 3.13 and 3.14. The gateway
   starts together with ZEN and also sits in the system tray.
2. **Allow control from outside.** In ZEN go to *Tools ▸ Options ▸ ZEN API*
   (ZEN core: *Maintenance ▸ General Options ▸ ZEN API*) and tick *Enable
   Unsupervised API Mode*. Without it ZEN only answers read-only calls and
   refuses every move or acquisition with *"Permission denied - Execution of
   API methods that can change the system state is currently not allowed"*.
   In that mode you and the driver can both use the microscope, so take care
   not to click in ZEN while a workflow is moving the stage.
3. **Get the control token**: right-click the gateway's tray icon and copy it,
   or read `C:\ProgramData\Carl Zeiss\ZEN APIGateway\GlobalControlToken.txt`.
4. **Install the Python packages** into the ZMART environment (the `zen_api`
   package is not on PyPI; ZEISS publishes it in its OAD repository):
   ```
   pip install -r zmart_drivers/zeiss/zenapi/requirements.txt
   ```
   The requirements file points at the 2026.05.1 wheel (ZEN 3.14); for ZEN
   3.13 use `zen_api-2025.10.1` from the same folder of the OAD repository.
   The driver works with both and records which one it found in `get_info()`.
5. **Write `config.ini`**: copy [`config.ini.example`](config.ini.example) and
   fill in the gateway host and port, the path of the gateway's root
   certificate (`C:\ProgramData\Carl Zeiss\ZEN APIGateway\Certificates\...RootCA.pem`)
   and the control token. **Never commit `config.ini`** (it holds the token);
   the driver's `.gitignore` already excludes it.
6. **Save the experiments you want to acquire with** in ZEN (for example
   `ZMART_Snap` with your channels and exposure, `ZMART_ZStack` with a
   Z-stack). The driver lists them under *available experiments*.

## Using it

With the controller (what a workflow does):

```python
import sys

sys.path.insert(0, r"...\ZMART-microscopy\zmart_drivers\zeiss")
import zenapi  # registers the instrument with zmart_controller

from zmart_controller.layer import set_instrument

s = set_instrument(
    {
        **zenapi.CONNECTION,
        "config": r"C:\zen\config.ini",
        "output_root": r"D:\runs\today",
        "experiment": "ZMART_Snap",
    }
)
s.set_origin()                       # here is (0, 0, 0) from now on
s.set_xyz(100, -100, 5)              # micrometres from the origin
s.acquire(acquisition_type="snap", position_label="tile_01")
s.run_procedure({"name": "software_autofocus"})
s.disconnect()
```

Or without the controller, using the driver directly:

```python
import zenapi as drv

client = drv.connect(r"C:\zen\config.ini")
drv.apply_stage_limits_from_config(drv.load_stage_config("stage_limits.json"))
drv.get_xy(client)                                   # {'x_um': ..., 'y_um': ..., ...}
drv.move_xy(client, 1000, 2000)                      # micrometres, refused outside the limits
drv.set_objective(client, name="Plan-Apochromat 20x/0.8")
exp = drv.load_experiment(client, "ZMART_ZStack")
acq = drv.acquire(client, exp, mode="experiment", output_name="stack_01")
saved = drv.save(client, acq, output_root, naming)   # copies the CZI into output_root
drv.close(client)
```

Every command returns a small dict: `success` (the call went through),
`confirmed` (a readback showed the requested result), a `message`, timing and
a log trace. Limit violations return `success=False` without contacting ZEN.

## What the driver offers today

| Neutral surface | ZEN meaning |
|---|---|
| `get_xyz` / `set_xyz` | The XY stage and the focus drive, µm, absolute from the origin. Every target is checked against this microscope's stage limits before ZEN is asked to move (XY first, then Z). One motor per axis, so `get_actuators` lists `motoric` only. |
| `set_origin` | Marks the current position as (0, 0, 0). Saved to `C:\ProgramData\zmart-microscopy\zeiss\<microscope>\origin.json`, restored on the next connect. |
| `acquire` | Runs the loaded ZEN experiment: a **snap** (one image with the active channels) by default, the **whole experiment** (Z-stack, tiles, time series) when `mode="experiment"` or the acquisition type mentions a stack, tiles or a time lapse. ZEN writes `<type>_<label>.czi` into its image folder; the file is copied to `<output_root>/data/` when that folder is reachable, otherwise the record says where ZEN left it. |
| `get_state` / `set_state` | Changeable: `objective_position` (position on the objective changer), `experiment` (the loaded ZEN experiment, which carries the imaging settings). Observed: objectives (name, magnification, NA), the experiments ZEN can load, ZEN's image folder, the limits, whether ZEN is busy. |
| `get_procedures` / `run_procedure` | `software_autofocus` (ZEN's focus search with the settings of the loaded experiment; reports `frame_z_um`), `find_surface` / `store_focus` / `recall_focus` (Definite Focus, on systems that have it), `live`, `stop`. |
| `get_info` | Initial position, limits and where they came from, objectives, output root, ZEN's image folder, and which `zen_api` version and services the session speaks. |

### Stage limits: the one thing ZEN does not tell us

The ZEN API does not report how far the stage can travel, so the driver keeps
its own envelope in `C:\ProgramData\zmart-microscopy\zeiss\<microscope>\stage_limits.json`
(micrometres, absolute ZEN coordinates). On the first connect the generic
defaults from [`limits/defaults/stage_limits.json`](limits/defaults/stage_limits.json)
are copied there with a warning; replace them with the real travel range of
your stage before running workflows. `get_info()["limits_are_defaults"]` tells
you whether that has been done.

## Architecture

```
zmart_drivers/zeiss/zenapi/
├── zen_zmart_adapter.py   the ZMART controller ops table (registers on import)
├── connection/   zen_runtime.py  the ONE place that imports zen_api: service classes
│                                 (with the stage-service fallback across ZEN releases),
│                                 request messages, TLS, token, config.ini
│                 client.py       ZenClient: the async gRPC client behind a blocking facade
│                 session.py      connect() / close()
├── commands/     commands.py     move_xy / move_z / set_objective / load_experiment /
│                                 run_snap / run_experiment / start_experiment / start_live /
│                                 stop / find_autofocus / find_surface / store_focus / recall_focus
│                 dispatch.py     the fire -> confirm backbone (retry on transient errors)
│                 confirmations.py readbacks (positions, objective, GetStatus after a run)
│                 errors.py       gRPC status code -> transient / permanent
├── readers/      api_reader.py   unary reads -> dicts (the single m -> µm boundary), monitor()
├── acquisition/  capture.py (acquire), save.py (find and copy the CZI), naming.py, product.py
├── limits/       checks.py, stage_config.py, defaults/stage_limits.json
├── calibration/  machine.py      origin.json + stage_limits.json under ProgramData
├── simulator/    fake_gateway.py the fake ZEN API gateway; certs.py; `python -m zenapi.simulator`
└── tests/        unit/ (fake objects, no wheel) · gateway/ (real wheel, fake gateway)
                  · hardware/ (real ZEN, marked) · helpers/roundtrip_checks.py (shared checks)
```

**ZEN speaks meters and blocks until done.** All positions on the wire are SI
meters; the driver converts at the request builder and the reader only. ZEN's
move calls return when the move is finished and its run calls when the
acquisition is finished, so the driver's readback confirmations (position
within 1 µm, objective position, `GetStatus` not running) are insurance, not
the completion signal. Acquisitions are never re-sent on a transient error: a
second send would start a second acquisition.

**The stage service moved between ZEN releases.** The 2025.10.1 package has it
under `zen_api.lm.hardware.v2.StageService`; the 2026.05.1 package dropped that
and offers `zen_api.hardware.v1.SimpleStageService` with the same two calls.
`connection/zen_runtime.py` tries both and uses whichever the installed
package provides; nothing else in the driver knows the difference.

## Testing

```bash
cd zmart_drivers/zeiss/zenapi
python run_ci.py                # ruff + offline pytest + coverage
pytest tests/unit               # 74 tests: fake ZEN API objects, no ZEISS package needed
pytest tests/gateway            # 19 tests: the real zen_api wheel over TLS to the fake gateway
python run_ci.py --hardware     # ONLY the @pytest.mark.hardware suite (needs a real gateway)
```

The unit layer injects fake service objects into a **real** `ZenClient`, so the
async-to-blocking bridge, the dispatch retry and confirm loop, unit conversion,
limit enforcement and the controller adapter are exercised for real. The
gateway layer replaces the fake objects with the real generated classes and a
real TLS connection to the fake gateway (it skips itself when the `zen_api`
package is not installed). The bench suite reuses the same round-trip checks
(`tests/helpers/roundtrip_checks.py`) against whatever `ZENAPI_CONFIG` points
at, and moves only 100 µm in XY and 10 µm in Z before returning.

## When the ZEISS simulator (or the microscope) arrives

Nothing needs to be written for the first bench run; it is the same checks
against a different `config.ini`:

```
set ZENAPI_CONFIG=C:\zen\config.ini
set ZENAPI_EXPERIMENT=ZMART_Snap
cd zmart_drivers\zeiss\zenapi
python run_ci.py --hardware
```

What that run confirms, which the fake gateway cannot:

1. **Which ZEN version and package pair you have.** `get_info()["server"]`
   shows the `zen_api` version and the stage service picked. If the gateway
   answers *service unavailable* for the stage, install the other package
   (see [Setting it up](#setting-it-up-on-the-microscope-pc), step 4).
2. **That moves return only when finished.** The documentation says they do;
   `test_small_moves` checks the readback right after the call. If a real
   stage is still travelling, raise `confirm_poll_s` in
   [`config/profiles.py`](config/profiles.py) for `STAGE_MOVE` / `FOCUS_MOVE`.
3. **Where the CZI is and whether this computer can see it.** `test_snap`
   prints the path ZEN reported. The driver looks for the file under that
   same path, so when ZMART runs on another computer, ZEN's image folder must
   be reachable there under the same path (a mapped share). Otherwise
   `acquire` leaves the file on the ZEN computer and says so in its record.
4. **The output-name rules.** ZEN wants a plain file name without extension;
   the adapter builds `<type>_<label>` with unsafe characters replaced.
5. **The status stream on a started experiment**
   (`test_monitor_started_experiment`): updates arrive several times per
   second and the last one says the experiment is over.
6. **The real stage travel range**, which goes into `stage_limits.json`.

## References

- ZEISS OAD — ZEN API overview, gateway setup and Python examples:
  <https://github.com/zeiss-microscopy/OAD/tree/master/ZEN-API>
- The `zen_api` packages (wheel + full API documentation per version):
  <https://github.com/zeiss-microscopy/OAD/tree/master/ZEN-API/python_package>
- Online API documentation: <https://zeiss-microscopy.github.io/OAD/zenapi/2026.05.1/>
- Sibling drivers (same architecture): `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`,
  `zmart_drivers/nikon/nis_elements_6_10/`
