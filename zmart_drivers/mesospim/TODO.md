# mesoSPIM driver — what's left to do

Status as of this branch: the driver speaks the **Remote Control** TCP protocol of
mesoSPIM-control [pull request #106](https://github.com/mesoSPIM/mesoSPIM-control/pull/106)
and is **offline-tested** (174 tests green) against a faithful mock of that server. It
is plugged into `zmart_controller` and follows the layout the other drivers write
(`data/` for the pixels, `data/metadata/` for what describes them).

> **Transport history.** Two earlier transports preceded this one — a bespoke command
> server loaded into the Core, then a generic "run this Python script" bridge — and
> both were validated on the `-D` demo before being retired in favour of the proper,
> validated API that mesoSPIM-control now carries. What the earlier bench runs taught
> (the Core names, the `start(row=…)` entry point, the image writer's one-stack-per-run
> behaviour) is built into the Remote Control server itself and into this driver's
> acquisition flow. The old material lives in this folder's git history.

Legend: 🔴 blocker for live use · 🟠 needed for a real run · 🟢 polish / nice-to-have.

---

## 1. Live validation against mesoSPIM `-D` demo mode 🔴

The offline mock reproduces the server's validation, one-change gate, operation
polling and file writing, but it is a re-implementation. The live round trip must be
run once against the real server before the driver is used on an instrument:

- [ ] Run the `remote-control-py312` branch of mesoSPIM-control in `-D` demo mode,
      start the TCP transport (or use `tests/hardware/launch_demo_server.py`), and run
      `run_ci.py online` with `MESOSPIM_TOKEN` set and `MESOSPIM_ALLOW_ACQUIRE=1`.
- [ ] Confirm on the real server what the mock assumes:
  - `acquire_start`'s result (`files`, `planes`, `pixels`) is readable from
    `get_progress` → `operation.result` once the run is `completed`;
  - `acquire_finish` restores the operator's list and is refused with `busy` while a
    run is still active;
  - `set_state` accepts the nine keys the adapter treats as changeable;
  - the default Tiff writer still leaves `<name>_meta.txt` beside the stack (the
    driver keeps it under `data/metadata/vendor/mesospim`; a missing note is fine).
- [ ] Re-run once the pull request is merged into mesoSPIM-control's main line, then
      update the status line in `README.md`.

## 2. Real-hardware validation 🟠

- [ ] On an actual mesoSPIM: verify moves land within tolerance, that limits in the
      machine copy of `stage_limits.json` match the instrument envelope reported by
      `get_limits`, and that theta / focus behave. Record the real envelope as the
      machine copy of `stage_limits.json` (under the ProgramData machine dir — see
      `calibration/machine.py`) rather than editing the bundled default.
- [ ] Sanity-check the zoom→pixel-size table in `config/profiles.py`
      (`HARDWARE.zoom_pixel_size_um`) against the instrument's calibration; the
      server's `get_config` reports the configured pixel sizes and should win.
- [ ] Non-Tiff image writers (OME-Zarr / BigTIFF / raw): confirm what files they
      leave and that `stat_files` sees them stop growing.

## 3. Acquisition features 🟢

- [ ] Multi-channel captures (loop lasers/filters into an acquisition list) and expose
      a channel list through the controller `acquire` options.
- [ ] Tiling helpers (build an acquisition list over an XY grid; the server offers
      `set_acquisition_list` / `run_acquisition_list` / `check_motion_limits`).
- [ ] Optional OME-TIFF re-encode in `acquisition/save.py` (today it copies the
      writer's stack verbatim; the pixel-pull → OME path is a documented seam).
- [ ] Decide whether the controller's `"snap"` should use the server's `snap` call
      (one live frame into the snap folder) instead of a one-plane acquisition run.

## 4. Procedures 🟢

- [ ] An autofocus. Remote Control offers none today; an ETL/remote-focus sweep
      would be a new server call (see the pull request's "Extending the command
      set") plus a driver procedure. Nothing is advertised until it exists.
