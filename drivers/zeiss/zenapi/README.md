# zenapi — ZEISS ZEN API microscope driver

A vendor sibling to the Leica `navigator_expert` driver, targeting **ZEISS ZEN** through the
**ZEN API** (gRPC/grpclib via a ZEN API Gateway). It mirrors the Leica driver's architecture —
connection + command vocabulary + state readers, with all tuning in `config/profiles.py` — but
adapts the transport to ZEN's fully-async, typed gRPC surface.

The public API is **synchronous** (a blocking facade over an async core), so operator notebooks keep
the thin 1–3-line invocation style used across the other drivers.

> **Status:** MVP. Core commands (stage XY, focus Z, objective, snap / run-experiment), api state
> readers, status-stream acquisition confirmation, config profiles, and a full offline test suite are
> implemented and green. The server-facing details are transcribed from the
> [zeiss-microscopy/OAD](https://github.com/zeiss-microscopy/OAD/tree/master/ZEN-API) examples and
> **not yet validated against the `zen_api` wheel or a live gateway** — see [Risks](#risks--bench-verify).

**Author:** Thom de Hoog (ZMB, University of Zurich) · thom.dehoog@zmb.uzh.ch · thomdehoog@gmail.com
**License:** MIT

---

## Quick start

```python
import zenapi as drv

client = drv.connect("config.ini")                     # gRPC + TLS + control-token
drv.apply_stage_limits_from_config(drv.load_stage_config("stage.json"))

drv.move_xy(client, 1000, 2000)                        # micrometers
drv.move_z(client, 50)                                 # micrometers
drv.set_objective(client, name="Plan-Apochromat 20x/0.8")

exp = drv.load_experiment(client, "TileScan_10x")
acq = drv.acquire(client, exp)                         # blocks until acquisition complete
saved = drv.save(client, acq, output_root, naming)     # copies the CZI into the layout

for status in drv.monitor(client, exp):                # live progress (status stream)
    print(status["images_acquired_index"])

drv.close(client)
```

## Install (on a ZEN PC)

1. Install the **ZEN API toolkit + gateway** via the ZEISS Microscopy Installer; enable the ZEN API
   (and *Unsupervised API Mode* if you want concurrent UI use). Requires ZEN ≥ 3.11.
2. `pip install` the shipped `zen_api` wheel (and `grpclib`).
3. Generate a **global control token** from the gateway; copy `config.ini.example` → `config.ini` and
   fill in host/port/cert_file/control-token. **Never commit `config.ini`** (it holds the token).

## Architecture

| Layer | Module | Role |
|---|---|---|
| Connection | `connection/zen_runtime.py` | wheel check, TLS context, metadata, and the ONE place that knows `zen_api` module paths / stub classes / request-message field names |
| Connection | `connection/client.py` | **`ZenClient`** — persistent asyncio loop thread; `submit()` (unary) and `stream()` (server-streaming) bridge async gRPC to blocking calls; lazy per-subsystem stubs |
| Connection | `connection/session.py` | `connect()` / `close()` |
| Commands | `commands/dispatch.py` | the dumb backbone: `confirm_and_fire` runs pre-check → **`fire_fn`** → confirm → re-fire, with transient retry |
| Commands | `commands/errors.py` | gRPC status-code → transient/permanent classification |
| Commands | `commands/confirmations.py` | readback confirms + `confirm_acquire` (consumes the status stream) |
| Commands | `commands/commands.py` | `move_xy` / `move_z` / `set_objective` / `load_experiment` / `run_snap` / `run_experiment` |
| Readers | `readers/api_reader.py` | `get_xy` / `get_z` / `get_objective` / `get_status` / `monitor` / `ping` — the single m→µm boundary |
| Config | `config/profiles.py` | `ZenApiProfile`, `ReaderProfile`, `CommandProfile` + per-command instances (all tuning) |
| Motion | `motion/limits.py`, `movement.py`, `stage_config.py` | µm safety envelope, backlash primitives, config loader |
| Acquisition | `acquisition/{product,capture,save}.py` | neutral product types, `acquire()`, CZI `save()` |

**The one load-bearing adaptation.** Leica fires by mutating a stateful model, calling a sync
transport, and reading an echo model. ZEN has none of that: a command is `await stub.<verb>(<Request>)`,
which returns on success or raises `GRPCError`. So the backbone's transport machinery collapses into a
single vendor-supplied **`fire_fn`** (a zero-arg sync callable that bridges one coroutine and returns
Leica's exact result shape). The backbone never sees asyncio, gRPC, or stubs.

**Units.** Public API is micrometers; ZEN is SI meters. Conversion happens only in the request builder
(`commands.py`) and reader parser (`api_reader.py`) — limits, profiles, and notebooks stay in µm.

**Readers are api-only.** ZEN has no log leg (errors are gRPC status codes; state comes from unary
reads + the native status stream), so the Leica api/log/hybrid router collapses to a single api path.

## Testing

```bash
python run_ci.py                # ruff (if present) + offline pytest + coverage (if present)
python run_ci.py --hardware     # only the @pytest.mark.hardware suite (needs a live ZEN)
pytest -m "not hardware"        # offline suite directly
```

The offline suite (50 tests) runs with **no `zen_api` wheel, no gateway, no scope**: a behavioral fake
ZEN API (`tests/helpers/mock_zen_api.py`) is injected into a **real** `ZenClient`, so the async→blocking
bridge, dispatch backbone, unit conversion, limits, error classification, status-stream consumption,
`acquire()`/`save()`, and clean package import are all exercised for real. Only the wire is faked.

## Risks / bench-verify

These are transcribed from the OAD examples and must be confirmed against the wheel / a bench; each is
confined so a fix touches one place:

1. **Request/response field names & module paths** (`zen_api.lm.hardware.v2` vs `hardware.v1`, enum
   spellings, `experiment_id`) — all in `connection/zen_runtime.py` and `readers/api_reader.py`.
2. **Completion semantics** — the design assumes `move_to` awaits to motion-complete. If it returns on
   command-*accepted*, make the readback confirm mandatory (raise `confirm_poll_s`, set
   `refire_on_unconfirmed=True`) in `config/profiles.py`.
3. **CZI retrieval** — `get_image_output_path` signature, local-vs-share path, and whether
   `run_experiment` returns only after the CZI is fully written (`acquisition/save.py`).
4. **Status stream** — it takes an `experiment_id`; whether a bare-instrument idle stream exists (hence
   no idle pre-check on moves) and whether it replays current status on subscribe (the "register before
   fire" ordering in `confirm_acquire`).
5. **TLS/auth + config schema** — validate against `zen_api_utils.misc.initialize_zenapi`.

## Extension seams (not in the MVP)

Experiment/template editing · calibration (image↔stage, parfocality) · pixel-pull exporter
(`monitor(kind="pixels")` → numpy → OME) · autofocus (SWAF / DefiniteFocus) · Optovar/filter/detector
services · a real reader router if a hardware-event stream appears.
