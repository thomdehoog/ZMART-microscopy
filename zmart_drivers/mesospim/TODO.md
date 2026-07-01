# mesoSPIM driver — what's left to do

Status as of this branch: the driver is **implemented and offline-tested** (94
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

- [ ] Launch `python mesoSPIM_Control.py -D`, load `server/mesospim_command_server.py`
      via the Script Window, confirm it prints `listening on 127.0.0.1:42000`.
- [ ] Run the ZMART round-trip against it (mark the suite `-m integration`):
      `connect → get_config → get_state → move_absolute → get_position → snap`.
- [ ] Confirm these Core names on the **installed** version (they match v1.20.0
      source today, but versions drift — all are isolated in `_CoreBridge`):
  - [ ] `core.move_absolute(sdict, wait_until_done=True)` / `move_relative(...)`
        and the `{axis}_abs` / `{axis}_rel` keys.
  - [ ] `core.zero_axes(list)`, `core.sig_stop_movement`,
        `core.sig_state_request_and_wait_until_done`.
  - [ ] `state['position']['x_pos' …]` layout and the settings keys
        (`laser`, `intensity`, `filter`, `zoom`, `shutterconfig`, `etl_*`).
  - [ ] `cfg` attribute names in `_CoreBridge.config()` / `_camera()`
        (`laser_designation`, `filterdict`, `zoomdict`/`zoom`, `shutteroptions`,
        `camera_x_pixels` / `camera_y_pixels`).

## 2. Acquisition path — the most site-specific piece 🔴

The capture reply must return the frame files the mesoSPIM **image writer**
actually wrote; the driver's `save()` then relocates them.

- [ ] Confirm the correct run entrypoint for one `Acquisition` / a single-item
      `AcquisitionList` in the installed version. The current server emits
      `sig_prepare_image_series` → `sig_run_timepoint(0)` → `sig_end_image_series`;
      verify that is the right sequence (vs. a dedicated `run_acquisition_list`
      slot) and that it blocks until frames are on disk.
- [ ] Implement real output-path resolution in `_CoreBridge._written_files`
      (currently `folder/filename` only): per-plane filenames the image-writer
      plugin produces, in plane order.
- [ ] Decide `snap` (single live frame, `sig_get_snap_image`) vs. a 1-plane
      series for `acquisition_type="snap"`, and where a live snap writes to.

## 3. Real-hardware validation 🟠

- [ ] On an actual mesoSPIM: verify moves land within tolerance, that limits in
      `config/stage_limits.json` match the instrument envelope, and that theta /
      focus behave. Update `stage_limits.json` defaults to the real envelope.
- [ ] Sanity-check the zoom→pixel-size table in `config/profiles.py`
      (`HARDWARE.zoom_pixel_size_um`) against the instrument's calibration.

## 4. Protocol / client hardening 🟠

- [ ] Enforce protocol-version compatibility: `MesospimClient.connect` should
      refuse a `hello.data.protocol` major it doesn't know (today it only stores
      `server_info`).
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

---

### Already done (for reference)

Protocol + client + session · dispatch backbone (retry/confirm) · command
wrappers (move/state/etl) · readers · profiles + 5-axis limits · capture + save ·
ZMART controller adapter + `register()` · resident command-server script ·
`PROTOCOL.md` · mock command server + 94 offline tests · headless Qt validation
of the server · Core bindings checked against mesoSPIM-control v1.20.0 source.
