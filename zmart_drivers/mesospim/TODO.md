# mesoSPIM driver — what's left to do

Status as of this branch: the driver is **implemented and offline-tested** (115
tests green). It now rides mesoSPIM's generic **Remote Scripting** bridge (the
upstream patch under `pull_request/`): the driver injects Python scripts and
parses a structured result back, with all command vocabulary client-side in
`connection/scripts.py`. The mock server `exec`s those very scripts against a
Core-shaped fake, so framing/harness/vocabulary are exercised for real offline.

> **Transport change.** An earlier iteration used a bespoke ZMART command server
> loaded into the Core; it was live-validated in `-D` demo but had sharp edges (an
> `exec()`-scope `NameError` on load; two live-only bugs). It has been **retired**
> in favour of the generic Remote Scripting bridge (which reuses `Core.execute_script`
> unmodified). See [`LIVE_BENCH_VALIDATION.md`](LIVE_BENCH_VALIDATION.md) (marked
> superseded) for that history and why the design moved here.
>
> The Core-API findings below (config/state/move/`start(row=…)`/image-writer path)
> were verified against a live v1.20.0 Core and still hold — they now live in the
> injected scripts (`connection/scripts.py`). What is **not** yet re-run is the
> live round-trip on this **new** transport (§1); that plus **real-hardware**
> validation are the open blockers.

Legend: 🔴 blocker for live use · 🟠 needed for a real run · 🟢 polish / nice-to-have.

---

## 1. Bench validation against mesoSPIM `-D` demo mode 🔴

The one thing that cannot be done in CI (needs the GPL app + a display). Two parts:
**(a)** apply the Remote Scripting patch (`pull_request/`) and start it (Tools →
Remote Scripting), then **(b)** re-run the `-m integration` round-trip on the new
injected-script transport. The Core-name checklist below was confirmed on the old
transport and carried into `connection/scripts.py`; re-confirm it end-to-end here.
(The items marked done were validated against a live Core previously; the ☐ ones
are the new-transport re-run.)

**Environment (how/where to run this).** mesoSPIM-control is a pure-Python PyQt5
app but is effectively **Windows-only** (docs: Windows ≥7 64-bit; Python ≥3.12).
`-D` demo mode swaps in `Demo` backends, so **no camera / stage / DAQ hardware or
their drivers are needed** — a bare Windows box or VM is enough (a Windows 11 VM
on macOS works fine for this). A native macOS/Linux run is *not* supported:
`requirements-conda-mamba.txt` pins Windows-only packages (`pywinusb`, plus
`nidaqmx` / `pipython`), so the install fails before launch. Install via
Miniforge/mamba + `pip install -r requirements-conda-mamba.txt`, then
`python mesoSPIM_Control.py -D`. The ZMART **client** side is cross-platform;
only the resident server + live Core need Windows.

- [x] Launch mesoSPIM `-D` demo mode, load the (since retired) Script-Window
      loader, confirm it prints `listening on 127.0.0.1:42000`. **DONE** —
      validated against a live `mesoSPIM_Core` (v1.20.0, all Demo backends) on
      Windows, driven headless (offscreen Qt). **Found + fixed:** loading the
      server *module* directly failed (`NameError` — `exec(script)` runs in a
      `Core` method, so module-level names resolve as globals); a flat loader
      script was the fix. See [`LIVE_BENCH_VALIDATION.md`](LIVE_BENCH_VALIDATION.md).
- [x] Run the ZMART round-trip against it (`-m integration`): connect →
      get_config → get_state → move_absolute → get_position → snap. **DONE** —
      all 5 integration tests pass against the live demo Core (through the real
      Script-Window loader), including the opt-in `acquire` (`MESOSPIM_ALLOW_ACQUIRE=1`).
- [ ] Confirm these Core names on the **installed** version (verified against the
      `1.20.0` source below, but versions drift — all are isolated in `_CoreBridge`):
  - [x] `core.move_absolute(sdict, wait_until_done=True)` / `move_relative(...)`
        and the `{axis}_abs` / `{axis}_rel` keys — confirmed (methods exist;
        `move_absolute` also takes `use_internal_position=True`).
  - [x] `core.zero_axes(list)`, `core.sig_stop_movement`,
        `core.sig_state_request_and_wait_until_done` — confirmed.
  - [x] `state['position']['x_pos' …]` layout and the settings keys
        (`laser`, `intensity`, `filter`, `zoom`, `shutterconfig`, `etl_*`) —
        confirmed against `mesoSPIM_State.py`.
  - [x] `cfg` attribute names in `_CoreBridge.config()` / `_camera()` — **fixed**
        to the real names: `laserdict` (was `laser_designation`), `filterdict`,
        `zoomdict` for zoom names + a separate `pixelsize` dict for µm/px (was
        reading pixel size off `zoomdict`), `shutteroptions`, and
        `camera_parameters['x_pixels'/'y_pixels']` (was `camera_x_pixels`). The
        config has no `version` attr — `hello`/config version falls back to the
        `mesoSPIM` package `__version__` if importable.
  - [x] Progress: mesoSPIM does not store it in the state singleton — the bridge
        now caches `core.sig_progress(dict)` (keys `current_acq` / `total_acqs` /
        `current_image_in_acq` / `images_in_acq`) instead of reading nonexistent
        `state['current_framenumber' …]` keys.

## 2. Acquisition path — the most site-specific piece 🔴

The capture reply must return the frame files the mesoSPIM **image writer**
actually wrote; the driver's `save()` then relocates them.

- [x] Run entrypoint corrected: `sig_run_timepoint(int)` is the *time-lapse*
      counter, not a per-acquisition trigger, so the old prepare→run_timepoint→end
      emit would never capture. The bridge now injects the `AcquisitionList` into
      `state['acq_list']` and calls the public `core.start(row=0)` (which drives
      the real `sig_add_images_to_image_series`), then waits for `idle`.
      **CONFIRMED on the demo Core:** `start(row=0)` + wait-for-idle captures a
      frame; `start()`'s disk pre-check runs (`Free disk C: space …`) and does not
      reject a scripted run. On the Remote Scripting transport a capture never
      blocks a script inside mesoSPIM: `acquire_start` returns immediately and
      the client polls progress + file existence up to
      `ACQUISITION.acquire_timeout_s` (600 s), raising on expiry (never a
      silent "success" without the stack on disk).
- [x] The controller assigns the Acquisition a per-acquisition `folder`/`filename`
      (a unique `<output_root>/_staging/<stem>_NNNN` dir + canonical stem, cleaned
      up after the frames are relocated), and the module-level `_written_files`
      helper resolves the writer path as `realpath(folder + '/' + sanitize(filename))`.
      Corrected to the **default Tiff writer's real behaviour — one multi-page
      stack per acquisition** (not one file per plane), with mesoSPIM's
      `replace_with_underscores` filename sanitisation. **CONFIRMED on the demo
      Core:** a snap wrote exactly one stack (`bench_snap.tiff`) that
      `_written_files` resolved correctly, alongside the predicted companions
      `MAX_bench_snap.tiff.tif` (MIP) and `bench_snap.tiff_meta.txt` — which the
      driver correctly does *not* return as frame data. **Still bench-pending:**
      confirm for non-Tiff writers (OME-Zarr / BigTIFF / raw).
- [ ] Decide `snap` (single live frame, `sig_get_snap_image`) vs. a 1-plane
      series for `acquisition_type="snap"`, and where a live snap writes to.

### Bench validation results (mesoSPIM `-D` demo, v1.20.0, Windows — old transport)

Validated against a **live `mesoSPIM_Core` with all Demo backends** by mirroring
`mesoSPIM_Control.main()` (load `demo_config.py` → `PluginRegistry(cfg)` → build
`mesoSPIM_MainWindow`) and `exec()`-ing `mesospim_command_server.py` against the
Core exactly as the Script Window does. Run headless (offscreen Qt); the harness
only disables the USB webcam and auto-dismisses mesoSPIM's construction-time modal
dialogs (ETL-config picker) — no driver/mesoSPIM code was patched to make it run.

**Result: all 5 `-m integration` tests pass**, including `acquire` — the full
`connect → get_config → get_state → move_absolute → get_position → snap` loop runs
against the real Core, moves the demo stage, captures a frame, and writes/relocates
the stack. `_CoreBridge` names (config/state/move/position/zero/stop/set_state),
the `start(row=0)` run path, and image-writer path resolution are all confirmed.

Two real bugs surfaced that the mock/headless-fake-Core suites could not (both
now fixed on this branch):

1. **`acquire` import was wrong.** The server did `from utils.acquisitions import
   …`, which raises `ModuleNotFoundError` in a real mesoSPIM process (the class is
   `mesoSPIM.src.utils.acquisitions`, the repo root being on `sys.path`). This
   would have broken *every* capture on real hardware, not just headless. Fixed to
   import the canonical `mesoSPIM.src.utils.acquisitions` with a bare-`utils`
   fallback.
2. **`acquire` had no long timeout.** The capture reply only arrives once the run
   finishes, which exceeds the ~10 s default socket deadline (a demo snap alone
   takes several seconds). Added `ACQUISITION.acquire_timeout_s` (600 s) and a
   per-call `read_timeout` on the client, used by `acquire`/`run_acquisition_list`.

## 3. Real-hardware validation 🟠

- [ ] On an actual mesoSPIM: verify moves land within tolerance, that limits in
      `config/stage_limits.json` match the instrument envelope, and that theta /
      focus behave. Update `stage_limits.json` defaults to the real envelope.
- [ ] Sanity-check the zoom→pixel-size table in `config/profiles.py`
      (`HARDWARE.zoom_pixel_size_um`) against the instrument's calibration.

## 4. Protocol / client hardening 🟠

- [x] Enforce protocol-version compatibility: `MesospimClient.connect` now
      refuses a `hello.data.protocol` it does not know (`protocol.PROTOCOL_VERSION`)
      and drops the socket instead of leaving it half-open.
- [x] Added the `-m integration` round-trip module
      (`tests/integration/test_live_roundtrip.py`): connect → get_config →
      get_state → move → get_position → acquire against a live server. Skips when
      nothing is listening; capture is opt-in via `MESOSPIM_ALLOW_ACQUIRE=1`;
      address via `MESOSPIM_HOST`/`MESOSPIM_PORT`. Still to do: wire it into the
      repo's `run_ci` aggregation (it is excluded from the default run today).
- [x] Added `requirements-dev.txt` (pytest, numpy, tifffile). The MIT client
      itself has no heavy deps — `numpy`/`tifffile` are test-only.

## 5. Real procedures 🟢

- [ ] `autofocus` / `find_sample` currently forward to a server `procedure`
      command that the resident script NAKs. Implement them server-side (e.g. an
      ETL/remote-focus sweep for autofocus) or drop them from
      `config.profiles.ACQUISITION.procedures` until they exist.

## 6. Acquisition features 🟢

- [ ] Multi-channel captures (loop lasers/filters into an `AcquisitionList`) and
      expose a channel list through the controller `acquire` options.
- [ ] Tiling helpers (build an `AcquisitionList` over an XY grid).
- [ ] Optional OME-TIFF re-encode in `acquisition/save.py` (today it copies the
      writer's frames verbatim + a JSON sidecar; the pixel-pull → OME path is a
      documented seam).

## 7. Upstream 🟢

- [x] **Draft the upstream PR (minimal)** — an opt-in, off-by-default
      **Tools → Remote Scripting…** server: an external process sends a Python
      script, it runs via the existing `Core.execute_script`, and the console
      output is returned (text in / text out). No command vocabulary in mesoSPIM —
      all of that stays on the ZMART side, injected as scripts. Token-gated,
      localhost-default, ~276 lines / 3 files, reuses `execute_script` unmodified.
      Built + validated live against the `-D` demo Core via the button's signal
      path (auth, read state, **move the demo stage**, structured output, error →
      traceback). Packaged in [`pull_request/`](pull_request/) (patch + README +
      PROTOCOL + demo_client). **Not yet submitted upstream.**
      *(An earlier, larger draft that put the whole command vocabulary upstream was
      replaced by this minimal version — smaller PR, fewer decisions, easier to
      merge; the vocabulary belongs to ZMART, not mesoSPIM.)*
- [ ] Open an issue with the mesoSPIM maintainers to gauge interest, then submit
      the PR from `pull_request/`. If accepted, operators start the server from the
      GUI and the Script-Window loader becomes the fallback for older installs; the
      ZMART client is unchanged either way.

## 8. Docs consistency 🟢

- [x] `server/README.md` → "Adapting to your instrument" reworded: the config
      names / bindings verified against `1.20.0` are marked ✓, and only the
      genuinely site-specific bits (acquisition run path, image-writer path) are
      left as bench-pending. README/PROTOCOL/docstrings brought in line with the
      single-stack + fail-closed + protocol-enforcement behaviour.

---

### Already done (for reference)

Protocol + client + session · dispatch backbone (retry/confirm) · command
wrappers (move/state/etl) · readers · profiles + 5-axis limits (fail-closed;
auto-loaded in `controller.connect`) · capture + save · ZMART controller adapter
+ `register()` · resident command-server script · `PROTOCOL.md` · mock command
server + 110 offline tests · headless Qt validation of the server · Core bindings
checked against mesoSPIM-control `1.20.0` source.

Post-review hardening: stage limits fail **closed** (unconfigured axis rejected,
matching the Leica sibling) and the controller loads them at connect · acquire
maps stack Z bounds through the frame origin and names the writer output so the
server can resolve frame paths · dispatch re-fire survives a NAK (envelope, not
exception) · the confirm freshness gate stamps observed-after at fire time so a
pre-command readback can't confirm · `set_state` fingerprint includes the
instrument name and rejects an empty fingerprint · client enforces the protocol
version and never leaves a half-open socket.

API-alignment (checked against mesoSPIM-control `1.20.0` on GitHub): fixed the
`_CoreBridge.config()` attribute names (`laserdict`, `pixelsize`,
`camera_parameters`), the progress reader (cache `sig_progress` instead of
nonexistent state keys), the acquisition run entrypoint (`core.start(row=…)` +
wait-for-idle, not the time-lapse `sig_run_timepoint`), and the image-writer path
model (one sanitised multi-page stack per acquisition, not one file per plane).
The mock server now mirrors that single-stack contract.

Production hardening (post critical review): resident server no longer blocks the
Qt event loop during an acquisition (nested `QEventLoop` wait), guards against
re-entrant polling, snapshots/restores the GUI's `acq_list`, caps the read
buffer, and is reload-safe (stops a prior instance, disconnects `sig_progress`);
`_written_files` refuses an empty folder and a non-existent path. Client-side:
`close()` now takes the socket lock, protocol-version parsing is defensive, and
any unexpected `fire_fn`/re-fire error is returned as an envelope (never raised).
Controller: per-acquisition staging that is cleaned up (no on-disk duplication),
collision-safe save names (no silent overwrite of a repeated type+label), and the
acquisition Z-sweep is limit-checked (fail-closed) before firing. `save()`
validates all sources before copying any (no partial datasets). Mock aligned to
the real server (procedures NAK, progress `None` defaults, `realpath`).
