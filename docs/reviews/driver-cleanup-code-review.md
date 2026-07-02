# Code Review — ZMART Controller & Leica Stellaris 5 Driver

> **Remediation status (2026-07-02, this branch):** the findings below have been
> addressed on `claude/zmart-driver-review-ktly65`. Outcome per finding:
>
> - **Fixed in code** (with regression tests; both suites green — controller 35,
>   driver 655 passed, ruff clean): C1's doc overstatements, C2, C3, C4, M1–M4,
>   M8–M20 (M14 and every unnumbered Major included), and most Minors/Nits —
>   see the commit history of this branch for the per-subsystem changes.
> - **Deliberate policy, reverted after counter-evidence — M5:** the unbounded
>   idle wait is a dated operator decision ("Idle-before-anything policy,
>   2026-06-11") pinned by `test_idle_prechecks.py`; a default ceiling was
>   implemented, then reverted to respect that policy. Revisit with the operator
>   if a watchdog is wanted.
> - **Documented as known limitation — M6:** fast-scan invisibility needs
>   frame-counter/hardware evidence; the docstring and failure message now say
>   exactly what happens, and `save()`'s freshness check remains the backstop.
> - **Documented, not flipped — M7:** `success_on_unconfirmed=True` is
>   deliberate per profile comments; the contradictory docstrings were fixed and
>   the accepted-vs-took-effect contract is now stated where every wrapper
>   lives. `move_xy_with_backlash` (M19) now demands `confirmed`.
> - **Fixed in the second pass (2026-07-02, this branch):**
>   - **C1's driver↔controller adapter layer** — built at
>     `navigator_expert/zmart_adapter.py` (registers on import) and validated
>     end-to-end against a live LAS X simulator through a real
>     `zmart_controller.Session`
>     (`tests/hardware/validate_zmart_adapter.py`; read-only slice wired into
>     `run_ci.py online`). The live pass exposed and fixed a stage-limits gap
>     (the adapter now applies the machine envelope at connect). Still owed on
>     a real scope: the z-wide drive leg and physical z-additivity.
>   - **Adopt-time matrix provenance** (finding 10, §6) — objective-pair
>     sessions record `image_to_stage_hash`; `adopt_calibration` refuses a
>     staged translation measured under a different (or unrecorded) matrix.
>   - **DST-safe log timestamps** (§3 minor 7) — `_parse_ts` disambiguates the
>     fall-back hour by choosing the fold closest to now.
>   - **`age_for_snapshot` semantics** (§3 minor 12) — mirrors the readers'
>     value derivation instead of min/max over tangential timestamps.
>   - **CONFIRM_SPECS folding** (§2 m7) — `sequential_mode` and
>     `z_stack_step_size` folded into the table; drift tests updated.
>   - The stress-suite acquire flake (mock scanning window missable under CPU
>     load) — the mock now guarantees one observed scanning read.
> - **Deferred (need hardware evidence or an owner decision):**
>   `GALVO_FIELD_FRACTION` snapshot routing (§6 finding 13 — warning
>   strengthened instead); ROI rotation unit (docs now say "unverified raw
>   value" — needs a hardware measurement); geometry-grid spacing and planned
>   column-major order (§4 minors 14/15 — pinned by tests as intended; needs an
>   owner decision before changing the math).

- **Branch:** `driver-cleanup` @ `a5465a5`
- **Date:** 2026-07-01
- **Scope:** `zmart_controller/` (all files) and `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` (all production modules: commands, readers, scanfields, experimental/lrp_edits, acquisition, calibration, motion, config, facade, run_ci)
- **Method:** full line-by-line review of ~20k lines of driver code + ~760 lines of controller code, cross-checked against test fixtures and the READMEs; test suites executed in a fresh Linux container.

## Test suite verification

Both suites are **green** on this branch:

- `zmart_controller/tests`: **21 passed**.
- Leica offline suite (`run_ci.py offline`): **631 passed, 1 skipped** after `pip install -r requirements-dev.txt`. Every failure seen along the way was a missing optional dependency in the fresh container (numpy, cv2, scikit-image, matplotlib, ome-types, lxml, IPython) — all of which `requirements-dev.txt` correctly documents. One flake observed: `calibration/tests/integration/test_workflows.py::test_image_to_stage_save_and_visualize_writes_png_diagnostics` failed once in a full-suite run and passed on re-run and in isolation (likely matplotlib global state in a headless run); worth keeping an eye on.

## Executive summary

The driver is in genuinely good shape for hardware-control code: the confirmation architecture (dual-leg API/log races, fail-closed staleness gates, table-driven readback specs), snapshot-based calibration persistence, and atomic file writes are careful, well-documented, and well-tested. The controller layer is clean and minimal.

The most important problems found:

1. **The controller↔driver integration does not exist yet.** No real driver registers with `zmart_controller`, and the real facades' APIs don't match the controller's ops contract — while several docs present the integration as working. (Known per `docs/ZMART.md`, but the READMEs oversell it.)
2. **`confirm_acquire` can report success for an acquisition that never ran** — a single failed scan-status read is misread as "scanning".
3. **The LRP text-edit primitives can corrupt sibling attributes** (`Zoom` vs `BaseZoom`) and `reorder_jobs` rewrites LRPs with the platform locale encoding, dropping the XML declaration.
4. **Every command profile has `success_on_unconfirmed=True`**, so `result["success"]` does not mean the setting took effect — and `move_xy_with_backlash`'s docstring promises the opposite of what it does.
5. **`mode="api"` reads bypass the capped worker thread entirely**, so the modal-dialog CAM hang this subsystem was built to survive blocks the caller indefinitely in the *default* read mode.

Findings below are grouped by component, most severe first. Severity: **Critical** = wrong results/data loss on plausible inputs; **Major** = real failure mode or contract violation; **Minor** = robustness/consistency gap; **Nit** = polish.

---

## 1. ZMART Controller (`zmart_controller/`)

### Critical

- **C1 — No real driver implements or registers the controller's ops contract.** `registry.py:13` says "Real vendor drivers register here", but the only `register()` callers are the test mock and the example notebook; nothing in `zmart_drivers/` imports `zmart_controller`. The real facades also can't be wired as-is: the Leica driver exposes `connect_python_client(...)` (not `connect(connection: dict)`), split `move_xy`/`move_z` (no `set_xyz(handle, x, y, z, with_actuators=...)`), and a capture-only `acquire(...)` with a separate `save()` — versus the controller's one-step acquire+save keyed by `acquisition_type` (`layer.py:127-146`). `set_origin`, `get_xyz`, `get_state`, `get_procedures`, `acquisition_options`, and `get_context` have no Leica counterparts at all. In production, `get_instruments()` returns `[]` and `set_instrument` raises. `docs/ZMART.md:60` admits this is under construction, but `zmart_controller/README.md` ("The same workflow runs on any microscope that has a driver") and the Leica README ("the vendor-agnostic surface this driver registers with") present it as existing. **Adapter modules per driver are the missing piece; until then the READMEs should say so.**

### Major

- **M1 — Stale `_active` after disconnect** (`__init__.py:60-63`). Module-level calls delegate through `_active`, which is never cleared on `disconnect()`; verified that `z.acquire(...)` still "succeeds" against a disconnected session. On real hardware that means commands over a dead connection. A module-level `disconnect()` that clears `_active` is needed.
- **M2 — Instrument swap is not failure-safe** (`__init__.py:54-56`, `layer.py:157-161`). If the old driver's `disconnect` raises during `set_instrument`, the newly connected session leaks (returned but untracked) and `_active` still points at the half-dead old session. `Session.disconnect()` also has no closed-flag, so the double-disconnect the test suite itself performs would raise on any real driver whose teardown isn't idempotent.
- **M3 — README example crashes against the reference driver** (`README.md:101`). `with_actuators={"x": ["motoric"], ...}` passes lists where the contract requires strings; verified `ValueError`. Should be e.g. `{"z": "piezo"}`.
- **M4 — Driver-teardown path has zero test coverage.** The mock registers no `disconnect` op and its handle has no closed state, so the branch real drivers need (`layer.py:159-161`) is never exercised and use-after-disconnect bugs (M1) pass silently.

### Minor

- Registry: duplicate identity silently overwrites, and identity excludes connection params like host, so two scopes of the same model collide (`registry.py:44,70`). No registry unit tests; no unregister/clear.
- Op key `"acquisition_options"` breaks the otherwise 1:1 op↔method naming convention (`registry.py:29` vs `layer.py:117-125`).
- `registry.py:54` reprs the full connection dict — which the README invites users to put credentials in — into exception text.
- `__getattr__` delegation makes the module surface depend on whether a session is active; bound methods captured before a `set_instrument` swap keep driving the old microscope. The "no active microscope" error branch (`__init__.py:64-67`) is dead in the test suite because `_active` is never reset between tests.
- Mock driver silently accepts unknown/invalid acquire options (`mock_driver.py:104-109`) and never persists the `with_actuators` selection (`mock_driver.py:150-154`) — as the advertised reference implementation, it teaches driver authors not to validate.

### Nits

- README license badge path is `../../LICENSE` (should be `../LICENSE`); "It then pass your choice" typo (`README.md:59`).
- `conftest.py` puts the tests dir on `sys.path` and imports a collision-prone top-level `mock_driver`.

---

## 2. Leica driver — commands (`navigator_expert/commands/`)

### Critical

- **C2 — `confirm_acquire` treats a failed status read as "scanning"** (`confirmations.py:1094-1107`). A failed `get_scan_status` read returns `None`, coerced to `"Unknown"`; `"Idle" not in "Unknown"` sets `saw_scanning = True` permanently. That skips the phase-1 permanent-error check and the `start_timeout` guard, and arms phase 2 — so two subsequent Idle reads yield `{"success": True}` for an acquisition that may never have started. One transient COM glitch is enough. Fix: treat `None`/`"Unknown"` as a third state, neither idle nor scanning. (`save()`'s freshness check is a backstop, but the command result itself is a false positive.)

### Major

- **M5 — Unbounded idle-waits on every hardware command.** `MOVE_XY`, `MOVE_Z`, `OBJECTIVE`, `ACQUIRE`, `SELECT_JOB` all use `pre_check_fn=partial(check_idle, timeout=None)` (`config/profiles.py:313-452`), a `while True` loop (`prechecks.py:50-76`). If an operator leaves live view running, every command blocks forever (heartbeat log only). A default ceiling (with the existing `pre_check_timeout` override) is warranted.
- **M6 — Fast scans are invisible to `confirm_acquire`** (`confirmations.py:1090-1127`). Level-based polling at 0.1 s (plus an API round trip per poll) can miss a short resonant scan entirely → 15 s stall then a false `"Scan not started"` failure for data that was actually acquired. Needs edge/counter evidence to supplement level polling.
- **M7 — `success_on_unconfirmed=True` everywhere, with contradictory docs.** `CommandProfile` defaults it True (`profiles.py:246`); `confirm_and_fire`'s docstring says "Default False" (`dispatch.py:468-469`). Effective behavior: a `set_*` whose readback never matched returns `success=True, confirmed=False`. Any caller gating on `result["success"]` alone proceeds with wrong optics settings. See also M15 (motion) for a concrete consumer bitten by this. At minimum align the docstrings and state in every command docstring that `success` ≠ "took effect".
- **M8 — `pre_check_fn`/`error_check_fn` exceptions escape as raw exceptions** (`dispatch.py:239,339`). Steps 2/3 and `confirm_fn` are try/except-wrapped; steps 1 and 4 are not. `_check_api_error` dereferences `client.PyApiCommandEcho.Model` unguarded (`errors.py:126`), so a transient COM fault crosses the "always returns a result dict" contract as an unhandled exception.

### Minor

- `_await_echo_result` timeout return value is discarded (`dispatch.py:295-296`): a LAS X rejection arriving after the 1.0 s settle window is read as success by the error check; only readback catches it (→ M7).
- Docstrings claim `error_check_fn=None` "defaults to `_default_error_check`"; it actually skips the check (`dispatch.py:205-207` vs `338-341`).
- Unknown `unit` string in `move_xy`/`move_z` is treated as µm for the limit check then raises a raw `KeyError` (`commands.py:1039-1064,1249-1280`); validate up front.
- `move_xy` docstring calls `result["position"]` a "final XY readback"; it is the target (`commands.py:1034-1035` vs `1097-1098`) — the real readback from `confirm_move_xy` is discarded.
- `set_z_stack_definition`'s `old_begin_um`/`old_end_um` are undocumented flag-only params whose values are never sent (`commands.py:584-624`).
- Z-stack quantised candidates assume ascending stacks; a descending stack that LAS X quantises never matches → 3 spurious re-fires (`confirmations.py:465-479`).
- `_confirm_sequential_mode` / `_confirm_z_stack_step_size` duplicate `_confirm_readback` and belong in `CONFIRM_SPECS`, contradicting the module's own design note (`confirmations.py:27-31`).
- Dead parameters: `_dispatch`'s `retry_backoff`/`retry_escalate`/`max_confirm_attempts` and `_readback`'s `observed_after` have no callers (`commands.py:126-128`, `confirmations.py:206`).
- `set_objective` "exactly one selector" is documented but not enforced; contradictory selectors resolve to first match (`commands.py:501-538`).
- No mutual exclusion around the shared `PyApiCommandEcho` for concurrent *commands* (reads are single-flight capped, commands aren't) (`dispatch.py:284-289`).

### Nits

- Any `HasError` message containing "warning" is treated as success (`errors.py:153`) — "Warning: stage limit exceeded, move aborted" would be swallowed.
- `select_job` hand-builds a log entry without `"ts"` (`commands.py:1414-1423`); its `timing.total_s` excludes `prepare_select_job` (`commands.py:1384-1387`).
- `method="async"` is hardcoded in every `_make_timing` call including sync paths (`dispatch.py:524+`).
- `_confirm_image_format` compares against the exact string `f"{w} x {h}"` — a reader formatting change breaks confirmation silently (`confirmations.py:836`).

---

## 3. Leica driver — readers (`navigator_expert/readers/`)

### Major

- **M9 — `mode="api"` bypasses the capped worker and all timeouts** (`router.py:183-188`). Only the hybrid leg goes through `_fire_api_read`; api mode calls `_api_read(api_fn)` on the caller's thread. The README claims "api (one CAM read in a capped worker thread)" — false. Consequences: per-datum profile timeouts are dead config outside hybrid; a modal-dialog CAM hang (the documented motivation for this subsystem) blocks the caller indefinitely in the **default** mode; and api-mode reads never check the in-flight cap, so they can pile onto a channel a hybrid worker is already hung on.
- **M10 — Polled API responses aren't correlated with their query** (`api_reader.py:117-134` and the same flush-and-poll in `get_xy`, `get_jobs`, `get_hardware_info`). If a query for job A times out and the caller then queries job B, A's late response lands in `Model.Settings` and is returned as B's settings — wrong FOV/geometry attributed to B. The payload carries `jobName`; a one-line `parsed.get("jobName") == job_name` guard is missing.
- **M11 — Sub-unity zoom clamped to 1, corrupting base-FOV by up to ~33%** (`derived.py:44-46`). The hardware zoom range includes [0.75, 1) (the driver's own mock declares `(0.75, 48.0)`); clamping makes `get_base_fov` — and hence galvo-pan scaling — silently wrong whenever zoom < 1. The `or 1` on the previous line already guards None/0; the clamp changes correct data.
- **M12 — `current_block_id` can pair a fresh Name with a stale ID** (`log_reader.py:290-292`). Only the Name line updates the timestamp; a parse racing the writer between the Name and BlockID lines returns `{"Name": <new>, "ID": <old>, "IsSelected": True}` from `get_selected_job`. A caller keying on `ID` acts on the wrong job.
- **M13 — Every log read re-reads and regex-scans the entire log file** (`log_reader.py:216-218,279`). No tail seek, position tracking, or size cap; `wait_for_selected_job_log` polls at 0.1 s and the hybrid race grants the log leg a 0.25 s grace window. A multi-hour LAS X session log makes each parse slower than the grace/poll interval, so the "hang-proof" log leg silently loses every hybrid race. (The stateless whole-file parse is a nice simplicity trade for rotation-correctness — it just needs a size-aware complement.)

### Minor

- With `diagnostics=True`, failed api/log reads return bare `None`, discarding the error, while `_unsupported` returns a `Reading` carrying the exception — inconsistent, and contradicts the README's source-tagged-`Reading` promise (`router.py:188,193`).
- `_parse_ts` uses naive local-time `strptime` vs `time.time()`: during DST fall-back, every `*_log_max_age_s` gate (0.5-2 s) refuses all log data for up to an hour (`log_reader.py:95-101`).
- `_log_rescue_concurrent` checks the deadline before draining the queue and busy-waits with `get_nowait()` + 5 ms sleeps; a result already in the queue at timeout is dropped (`router.py:248-275`).
- Scan-status failure sentinel diverges by mode: api mode passes through `"Unknown"`; log mode maps it to `None` (`api_reader.py:53-59`, `capabilities.py:38-39`).
- Log-leg job dicts are partial (`{"Name","IsSelected"[,"ID"]}` — no `IsAutofocus`/`FocusRange`), so `job["ID"]` works in api mode and KeyErrors in log mode, despite the router docstring's "keep the old reader return shapes" (`log_reader.py:471-501`).
- The README's "never raise" claim is violated by unguarded `ET.parse` in `get_lasx_settings` (`api_reader.py:386`) and `read_zwide_um`'s `RuntimeError` (`router.py:370-371`); `log_reader.read_zwide_um` claims "parity with the API reader" but no API counterpart exists.
- `age_for_snapshot` uses `max` over tangential datums for `"jobs"` (fresh value reports ancient age) and `min` for `"selected_job"` (stale value can report fresh age) — diagnostics-only, but that's their sole purpose (`capabilities.py:79-100`).
- README reader table drift: `ping` and `get_pending_dialog` signatures don't match the code (README vs `router.py:295,451`).

### Nits

- `_client_api_key = id(client)` can collide after GC (`router.py:114-115`).
- `_RE_CURRENT_BLOCK_NAME` truncates job names at internal whitespace-then-apostrophe (`log_reader.py:90`); the XY regex requires exact attribute order (`log_reader.py:87`); locale decimals (`"1,23"`) are silently skipped with no one-time warning (`log_reader.py:227,259`).

---

## 4. Leica driver — scanfields & LRP edits (`scanfields/`, `experimental/lrp_edits/`)

### Critical

- **C3 — `_set_job_attr` can corrupt sibling attributes with suffix-colliding names** (`_primitives.py:54,69`). The search regex `rf'{attr_name}="([^"]*)"'` has no word boundary, so for `attr_name="Zoom"` it matches inside `BaseZoom="0.75"` if serialized first — editing the wrong attribute outright. And the replacement `element_text.replace(m.group(0), ...)` replaces **every** occurrence in the tag, so when `Zoom="1"` and `BaseZoom="1"` coincide, `lrp_set_zoom(..., 2.5)` rewrites both. Real fixtures carry both attributes on the same `ATLConfocalSettingDefinition` tag; `_verify_job_attr` checks only the target attribute so the corruption is invisible. Same latent risk for `ScanSpeed`/`LastCsScanSpeed`, `Begin`/`*Begin`. Fix: anchor with `(?<=\s)` and replace with `count=1` (or slice-replace at `m.start()`).
- **C4 — `reorder_jobs` writes LRPs with the platform locale encoding and drops the XML declaration/header comments** (`transaction.py:93`). `ET.ElementTree(root).write(path, encoding="unicode", xml_declaration=False)` with a *filename* opens the file in the locale encoding (cp1252 on the Windows targets). Any non-ASCII character (a job name like "Übersicht", "µ" in annotations) becomes invalid UTF-8 with no declaration to say otherwise → malformed LRP for LAS X. The four Leica header comments are also discarded. This runs on **every** `apply_lrp_change` (`transaction.py:151`).

### Major

- **M14 — `reorder_jobs` silently deletes unmappable entries** (`transaction.py:84-91`). All sequence elements and blocks are removed, then only entries reachable via `block_to_job` re-appended: blocks without `LDM_Block_Sequential`, unmapped `BlockID`s, and duplicate `BlockName`s are permanently dropped. Also an uncaught `KeyError` if the first job has a block but no sequence element.
- `apply_lrp_change` ignores the edit result and has no rollback (`transaction.py:148-181`): a no-op edit (job not found → 0 attributes changed) still reorders/reloads/saves and returns `{"success": True}` when `verify_fn is None`; a failed reload returns `None` with the LRP edited on disk, LAS X state stale, and no pre-edit backup — the "transaction backbone" docstring oversells this.
- Verification is vacuously true when the attribute is absent (`_primitives.py:96-101`): `_set_job_attr` never *adds* attributes, and `_verify_job_attr` skips absent ones — so an edit that changed nothing reports verified success.
- `lrp_set_stack_calculation_mode` searches for the Master element without bounding at the job block's end (`focus.py:66`) — if the target job lacks a Master, the **next job's** `StackCalculationMode` is modified, reported as success.
- `_tile_size_from_image_size_str` parses `"nm"` but never converts it → 1000× tile-size error propagating into every bounding box and planned grid (`parsers.py:102-110`).
- `parse_rgn_tile_colors` reads `<n>` instead of `<Name>` (`parsers.py:750`), so the documented JN job-name path is dead; colors key off `LabelText` (the `"R22 (19)"` tag in real files), and the unit test passes only because its fixture puts the job name in `LabelText`.
- `save_and_read_lrp` returns stale pre-save data when the save fails, despite its docstring promising `None` (`files.py:246-273`).
- A stale `.lrp.bak` from a crashed prior run is restored over the current LRP (`strip_restore.py:288-291,357-359`): `bak_lrp` is only refreshed when `stripped_lrp` exists and never cleaned up otherwise. Fix: `bak_lrp.unlink(missing_ok=True)` in the else branch.
- `disable_roi_scan` / `reset_pan` discard `apply_lrp_change`'s result despite docstrings promising verification (`roi.py:169-185`, `scan.py:304-319`) — a failed ROI disable produces exactly the black-frame failure the docstring warns about, silently.

### Minor

- One malformed `ScanFieldData` (`SectionX/Y` → `None`) makes region sorting raise `TypeError`, killing the whole parse (`parsers.py:219`); mixed-job sections take an arbitrary `job_name` (`parsers.py:227`).
- Geometry-derived grids place tile centres on the bbox corners with spacing `width/(n-1)`, ignoring `DistanceData` — disagrees with LAS X's materialized layout whenever spacing ≠ width/(n-1) (`parsers.py:289-296,369-370`; pinned by a test, so intended, but worth revisiting).
- Planned regions emit `row=0, col=i, num_rows=1` for 2-D grids and iterate column-major while the XML parser sorts row-major — consumers matching planned order to acquired order get transposed indices (`planning.py:164-209,269-281`).
- `confirm_delays` are actually per-attempt save *timeouts*; the first (0.5 s) is nearly always too short for a LAS X save, guaranteeing wasted re-fires (`transaction.py:109,158-160`).
- On total restore failure the backups are deleted (`strip_restore.py:349-355`), and the success criterion never checks the focus-map count.
- `find_scanning_templates_dir` picks the alphabetically-first `User_*` profile (`files.py:59-63`); corrupt templates classify as "stripped" (`files.py:101-117`).
- `lrp_add_roi` documents rotation in degrees; `roi_geometry` documents the same attribute in radians — one is wrong by 57× (`roi.py:527` vs `849`).
- `center_vertices` has no empty guard and biases the centroid toward the duplicated closing vertex of closed polygons (`roi.py:443-447`).
- `lrp_set_z_stack_size`: missing Master reports "job not found"; missing `ZPosition` silently centers the stack at Z=0 m (`z.py:273-279`).
- `parse_lrp` doesn't filter `BlockType == "1"` and collapses duplicate job names, unlike `_get_job_names` (`lrp.py:347-370`).

### Nits

- Three different `.lrp` serialization styles in one subsystem (UTF-8+declaration, locale-text, byte-preserving text replace).
- `_verify_job_attr`/`_verify_job_attr_float` are copy-paste twins; the string-mode reverse-dict dance repeats four times.
- Auto ROI names `ROI {len+1}` can collide after deletions; `MemBlock_{uuid % 100000}` has birthday-collision risk (`roi.py:560-607`).
- `infer_overlap_pct_from_geometry_counts` brute-forces 501 full grid generations per call (`planning.py:102-110`).

---

## 5. Leica driver — acquisition (`navigator_expert/acquisition/`)

### Major

- **M15 — Navigator export reads pixel data & XML before the stability check** (`navigator_expert_export.py:59-90`). Building `detected` runs `tifffile.imread(...)` and `xml_paths[0].read_bytes()` (`:362,366`) before `wait_all_stable` is called; the completeness loop only waits for files to *exist*. On Windows, LAS X holds an exclusive write lock and files may be partially written → `PermissionError` or truncated reads. The native-autosave path does it in the correct order (`lasx_native_autosave.py:78`); the two paths should match.
- **M16 — Freshness check compares host wall-clock to file mtime** (`files.py:87-92`, seeded from `capture.py:46`). `st_mtime >= started_at` breaks both ways on SMB shares with coarse mtime resolution or clock skew: fresh exports rejected ("No files found") or stale leftovers accepted.
- **M17 — Per-plane OME-TIFFs are written with physical pixel sizes stripped to `None`** (`ome_canonical.py:157-162`). Only the companion XML keeps calibration; tools opening the plane TIFF directly silently lose pixel calibration, and the docstring doesn't mention the deliberate loss.
- `summary.json` is rewritten in full once per plane — O(n²) disk I/O for large grids — and an externally corrupted summary aborts the whole save with images already written (`save.py:216,273-288`).

### Minor

- Re-export into a reused folder hard-fails: `parse_lasx_filename` recognises the `--NNN` repeat suffix but position collection ignores it, so original+repeat both land in `fresh` and raise `duplicate LAS X plane index` (`navigator_expert_export.py:234-279`).
- `DEFAULT_EXPORT_COMPLETION_TIMEOUT_S = 5.0` for *all* planes to appear vs 120 s for stability — the asymmetry looks unintentional and can fail healthy long time-series (`navigator_expert_export.py:31,214-227`).
- Interior Windows backslashes in `RelativePathName` aren't normalized (only leading separators stripped) — correct on Windows, wrong for cross-platform tooling (`navigator_expert_export.py:122`).
- Fixed `.tmp` suffix collides under concurrent writers of the same destination (`materialize.py:130-131`, `save.py:268`).
- On a job-settings read timeout, the known-bad vendor `PhysicalSizeZ` is silently kept with no warning (`ome_canonical.py:107-137`) — a transient slow read yields silently wrong Z calibration.
- `materialize.extract_embedded_ome_xml` is a test-driven pass-through duplicating `ome_canonical`'s.

### Nits

- `endian_or_err` holds an error string or an endian char depending on branch (`ome.py:324-391`).
- Generated OME roots omit the recommended top-level `UUID` attribute; image summary records lack the `sha256` that vendor records carry; `_metadata_from_native_tiff` opens the TIFF a second time.

Note: `ome.py` vs `ome_canonical.py` is **not** duplication — `ome.py` validates/patches vendor XML (the `Laser Wavelength="0"` fix), `ome_canonical.py` generates the driver's canonical output. Both are live; the split is coherent.

---

## 6. Leica driver — facade, calibration, motion, config, CI (`__init__.py`, `calibration/`, `motion/`, `config/`, `run_ci.py`, `utils.py`)

### Major

- **M18 — README documents a nonexistent `run_ci.py --hardware` flag** (`README.md:362`). `run_ci.py` accepts only positional `offline|online|both` plus `--no-lint`/`--no-cov`; the documented command exits with an argparse error, so anyone following the testing section cannot run the hardware suite. (The branch's own recent commits renamed the interface; the README lagged.)
- **M19 — `move_xy_with_backlash` docstring promises raise-on-failure but an unconfirmed move passes silently** (`motion/movement.py:71-93`). It checks only `r.get("success")`, and `MOVE_XY` has `success_on_unconfirmed=True` (see M7) — so after 3 exhausted confirm windows the stage may be outside tolerance and the helper returns normally. `workflows/target_acquisition/pipeline/_acquire.py:41` uses it immediately before every acquisition and also checks only `success` — imaging at the wrong position with no error, the exact bug the docstring claims is prevented. `calibration/core/common.py:168-189` does the explicit readback for exactly this reason; the final leg here should too.
- **M20 — `objective_pair.py` module docstring contradicts the code on z-wide parking** (`objective_pair.py:14-21` vs `:464-466,550-551`). The operator-facing steps 2/3 say "park z-wide at the peak"; the implementation deliberately does not move z-wide (operator manages it manually). An operator following the module contract assumes focus that isn't there.

### Minor

- `run_ci.py online` still runs ruff despite the docstring's "just the live LAS X validators" (`run_ci.py:9` vs `:159-180`); `run_step` catches only `FileNotFoundError`, so any other `OSError` aborts with no CI summary (`run_ci.py:100-107`).
- Calibration schema version is duplicated (`stage_config.py:24` and `model.py:20`, both 11, validated independently) — a future bump updating one desynchronizes `load_stage_config` and `load_calibration` on the same file.
- D4 residual printed as µm is actually a dimensionless Frobenius matrix distance (threshold 0.3) — operator misreads the gate (`image_to_stage.py:426-430`).
- `read_job_geometry` crashes with a bare `TypeError` on missing pixel/format metadata instead of a clear error (`common.py:125-132`).
- `adopt_calibration` never checks which image_to_stage matrix the session's `correction_xy` was measured under — an intervening adoption silently pairs a translation with the wrong matrix (`adopt.py:182-188`). A recorded matrix hash verified at adopt would close this.
- Hardcoded `({confidence}/4)` voting count in `objective_pair.py:291` (elsewhere `len(VOTING_METHODS)` is used correctly).
- `correct_backlash`/`move_xy_with_backlash` omitted from `__all__` (`__init__.py:357`), contradicting README §11's convention; the calibrated `backlash["tolerance_um"]` is required by config but unused on the transit path.
- `GALVO_FIELD_FRACTION` was measured on a STELLARIS **8** and baked as a source constant into the STELLARIS **5** driver (`utils.py:48-65`); unlike image_to_stage/backlash it doesn't route through machine snapshots, so a per-scope error requires a source edit.

### Nits

- `_leica_root = parents[1]` actually points at the machine dir, not `leica/` (`__init__.py:267`).
- `_parse_dim_um` applies the first-matched unit to both dimensions of a mixed-unit string (`utils.py:141-156`).
- Type-incorrect annotations in `CommandProfile` (`callable = None`, `float = None`).
- `connect_python_client` has no disconnect/close counterpart anywhere — acceptable for an in-process API, worth one README sentence.
- README architecture tree places `run_ci.py · pytest.ini` under `tests/`; both live at the package root.

---

## Strengths worth keeping

- **Fail-closed confirmation architecture.** The select-job transition-witness gate (a stale readback already showing the target before the command can't prove the command worked), the dual-leg API/log race that surfaces source disagreement instead of hiding it, and the in-flight API cap that holds until the CAM call truly returns are genuinely rigorous — rare in instrument-control code.
- **Table-driven confirmations with drift protection.** `CONFIRM_SPECS` collapses ~14 near-identical poll loops into data, and a test asserts table↔wrapper coverage so they can't silently diverge.
- **Snapshot persistence is structurally stale-proof** (`config/machine.py`): lexically-chronological UTC stamps, monotonic guards, `.partial` staging invisible to the snapshot regex, atomic publish with cleanup on `BaseException` — pinned by tests.
- **Coordinate math is self-consistent end-to-end**: `-inv(M)` sign conventions match across `image_to_stage`, `model.pixel_to_stage`, `objective_pair.correction_xy`, and the D4 scorer; reflection is guarded by determinant; tests assert exact values, not just shapes.
- **The log reader's "None, never wrong" contract is actually enforced**: per-datum source timestamps, ambiguous duplicates refused, index-fallback gated on provably unambiguous clusters.
- **`_wait_file_stable`** (present + non-zero + size-unchanged + unlocked, N consecutive readings) is a solid guard against partial GUI-app writes — where it's invoked before reads (native path; the Navigator path needs the same ordering, M15).
- **Docstrings capture hard-won hardware behavior** (pan-then-zoom clamping order, `eMoveXY=2 NOT 0 which is eDontMove!`, ROI sign conventions) — valuable institutional knowledge.
- **`requirements-dev.txt` is exemplary**: every heavy dependency traced to the import that needs it; the offline suite really does run anywhere.

## Suggested priorities

1. **Now (data corruption / false success):** C2 (`confirm_acquire` Unknown-as-scanning), C3 (`_set_job_attr` sibling-attribute corruption), C4 (`reorder_jobs` locale write) + M14 (silent entry deletion) — the last three make every `apply_lrp_change` risky on real-world LRPs.
2. **Next (silent wrong results):** M11 (zoom clamp), M19 (backlash helper vs `success_on_unconfirmed`, plus a driver-wide decision about M7), M10 (uncorrelated API polls), M15/M16 (export races), M17 (stripped pixel sizes).
3. **Then (availability/docs):** M9 (api-mode bypasses the worker), M5 (unbounded idle waits), M13 (whole-log rescans), M18 (README `--hardware`), M20 and the other README/docstring drift.
4. **Controller:** decide whether the ops contract or the driver facades move — then build the Leica adapter and make the mock exercise `disconnect` (C1, M1-M4). Until then, soften the READMEs.
