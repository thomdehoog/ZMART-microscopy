# mesoSPIM driver — what's left to do

Status as of this branch: the driver is **implemented and offline-tested** (103
tests green, ruff clean), and the resident command server's Qt half is validated
headless. What remains is almost entirely **bench validation against the real
mesoSPIM-control app** plus a few polish items. Nothing below blocks using the
driver against the mock server or reviewing the design.

Legend: 🔴 blocker for live use · 🟠 needed for a real run · 🟢 polish / nice-to-have.

---

## 1. Bench validation against mesoSPIM `-D` demo mode 🔴

The one thing that cannot be done in CI (needs the GPL app + a display; see
`server/README.md`). Everything here is about confirming the resident script's
`_CoreBridge` against a *running* Core, not new code.

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

- [ ] Launch `python mesoSPIM_Control.py -D`, load `server/mesospim_command_server.py`
      via the Script Window, confirm it prints `listening on 127.0.0.1:42000`.
- [ ] Run the ZMART round-trip against it (mark the suite `-m integration`):
      `connect → get_config → get_state → move_absolute → get_position → snap`.
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
      **Bench-pending:** confirm `start(row=…)` + wait-for-idle is sufficient
      (vs. also waiting on `sig_finished`) and that disk/limit pre-checks in
      `start()` don't reject a scripted run.
- [x] The controller assigns the Acquisition a per-acquisition `folder`/`filename`
      (a unique `<output_root>/_staging/<stem>_NNNN` dir + canonical stem, cleaned
      up after the frames are relocated), and the module-level `_written_files`
      helper resolves the writer path as `realpath(folder + '/' + sanitize(filename))`.
      Corrected to the **default Tiff writer's real behaviour — one multi-page
      stack per acquisition** (not one file per plane), with mesoSPIM's
      `replace_with_underscores` filename sanitisation. **Bench-pending:** confirm
      for non-Tiff writers (OME-Zarr / BigTIFF / raw) and note the companion
      `MAX_*` MIP + `*_meta.txt` sidecar the writer also drops in the folder.
- [ ] Decide `snap` (single live frame, `sig_get_snap_image`) vs. a 1-plane
      series for `acquisition_type="snap"`, and where a live snap writes to.

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
- [ ] Add an `-m integration` test module that runs the round-trip in §1 so the
      bench step is one command, and wire it into the repo's `run_ci` aggregation.
- [ ] Add a `requirements-dev.txt` (pytest, numpy, tifffile for the mock/tests;
      PyQt5 only for `server/validate_headless.py`). Note: the MIT client itself
      has **no** heavy deps — `numpy`/`tifffile` are test-only.

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

- [ ] Propose `server/mesospim_command_server.py` to the mesoSPIM project as a
      first-class "command server" script (Zurich-local, community-run), so it is
      a script mesoSPIM ships rather than a patch to maintain. Keeps the GPL edge
      upstream and the ZMART client MIT.

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
