# Implementation Plan: Driver-First Architecture for Lab-Wide Output Naming Convention

Drafted 2026-05-11 against `cleanup/wave-2`. Final revision after three independent reviews. **Supersedes** `V3_OUTPUT_NAMING_PLAN_2026-05-08.md`.

Canonical convention spec: `smart_microscopy_smart_folder_structure.md` (auto-memory). This plan is the implementation path.

## Design discipline (read first)

The user's directive, applied throughout:

- **No fluff, no bloat, no workarounds, no patchwork.** Clean fundamental architecture.
- **Minimal changes.** Don't add modules, abstractions, or fields the current requirement doesn't justify.
- **Defer until needed.** Optional scaffolding stays out until something concrete demands it.
- **One thing in one place.** The driver owns the convention. Workflows trust it. No duplicated path math, no parallel validation paths, no thin-shim wrappers.

If a section below adds something, it answers "what breaks today if this isn't here?" If the answer is "nothing concrete," it's cut.

This is also a contract for me when implementing: if I notice myself adding optional kwargs, helper-helpers, or "for future flexibility" hooks, stop and ask.

## Architectural principle

**Driver owns the convention. Workflows specify what to acquire and trust the driver to land it correctly.**

Driver owns:
- Filename/folder schema (path math, builders, parser)
- Atomic save (image + XML as one unit, via `.tmp` + `os.replace` — never `copy2` direct)
- Validation (stability, OME integrity, size)
- Run directory lifecycle (collision-safe mkdir, summary writing)
- LAS X source → canonical `Naming` translation

Workflows own:
- *Which* acquisitions to perform, at *which* positions, with *which* job
- Building a `Naming` per acquisition (slot values)
- Workflow-specific records (lineage, decisions, analysis pointers)

Workflows never see `shutil.copy2`, `mkdir`, `wait_all_stable`, `check_ome_tiff`, or path strings beyond what they passed in.

## BLOCKING items (resolve before any code)

These are spec defects, not open questions. The memory spec was amended 2026-05-11 to reflect the locked decisions below.

### BLOCKING-1. Per-slice naming for `c` and `z` — RESOLVED

**User decision (2026-05-11): keep `c` and `z` in the image filename.** Each `.ome.tiff` represents one channel × one z-slice. A z-stack of N slices × M channels produces N×M files at that `(k, m, g, p, t, v)` position. XML companion still describes the full c×z grid at the position (omits `c` and `z` from its filename).

This means the driver must export per-slice from LAS X (or unpack on save if LAS X exports multi-channel multi-z OME-TIFFs). Driver-side implementation detail; the schema is per-slice.

### BLOCKING-2. Reacquisition contract (no `r` slot) — RESOLVED

**User decision (2026-05-11): do not add `r`.** The spec declares a hard reacquisition contract instead:
- Schema does **not** support multiple acquisitions of identical `(k, m, g, p, t, v, c, z)`.
- Workflows re-shooting the same logical target (autofocus correction, QC failure, drift registration) must either **overwrite** the original or **bump a slot value** (typically `t` — "second attempt at this target," or `g` if the retry belongs to a different logical group).
- Workflow is responsible for collision-free naming. No implicit retry dimension.
- Per-attempt provenance lives in `summary.json` lineage, not the filename.

### Final grammar

**Image filename** (per-slice, one file per channel × z-slice):
```
[acquisition-type]_[hash6]_k[NNNNN]_m[NNNNN]_g[NNNNN]_p[NNNNN]_t[NNNNN]_v[NN]_c[NN]_z[NNNNN].ome.tiff
```

**XML companion** (one per acquisition position; describes c×z grid):
```
[acquisition-type]_[hash6]_k[NNNNN]_m[NNNNN]_g[NNNNN]_p[NNNNN]_t[NNNNN]_v[NN].ome.xml
```

Slot order in `Naming` dataclass: `k, m, g, p, t, v, c, z` (all 8 present in image filename; XML omits `c` and `z`).

## Open questions

After resolution of the blocking items, two questions remain. Q1/Q3/Q5/Q6 from earlier drafts are resolved (Q1: `output_root` is derived, not configured) and folded out.

### Q2. Module placement for vendor-neutral schema

The driver currently lives under `controller/vendor/leica/navigator_expert/` and is self-contained. The schema module is lab-wide and vendor-neutral. Two coherent options:

- **(a) `controller/vendor/_shared/output_layout/`** — sibling shared package under the vendor tree. Driver imports stay within `controller/vendor/...`, preserving vendor-isolation pattern. Recommended.
- **(b) `controller/output_layout/`** — sibling of `controller/vendor/`. Cleaner semantic placement (the convention is not a vendor), but driver now reaches outward from its vendor folder. Acceptable if vendor isolation isn't a hard requirement.

Pick before Commit 1. Recommend (a).

### Q4. v3 slot mapping and `pick_sequence` stability

Workflow-level decision (not spec-level). Analysis nondeterminism (cellpose GPU vs CPU, segmentation order) reorders detections across re-runs, so `p = pick_sequence` is unstable.

**Recommend:** deterministic analysis (cellpose CPU + fixed seed + sort detections by `(y, x)` before assigning `p`), AND record `(source_tile_rid, row, col, label, parent_image_path)` in the per-acquisition lineage dict that gets atomically appended to summary.json. Cross-run identity falls back on `(source_tile, label)`, not `p`.

## Driver public API

Locked surface. Workflows depend on this signature.

```python
# driver/acquisition.py

@dataclass(frozen=True)
class RunHandle:
    layout: LayoutPlan
    start_time_utc: float
    media_path: str           # LAS X export root, cached for source discovery
    baseline: str             # initial RelativePathName

@dataclass(frozen=True)
class SavedAcquisition:
    image: np.ndarray
    image_path: Path          # canonical, under run_dir/<acquisition-type>/data/
    naming: Naming            # echoed back, post-validation

def start_run(
    client,
    experiment: str,
) -> RunHandle:
    """Derive output_root as media_path/smart/, atomically create run dir.
    Cache LAS X media path + baseline. Write initial summary.json skeleton.
    Operator does not configure output_root — driver derives it from LAS X."""

def acquire_and_save(
    client,
    run: RunHandle,
    job: str,
    naming: Naming,
    *,
    lineage: dict | None = None,
    fix_ome: bool = False,
    cleanup_source: bool = False,
) -> SavedAcquisition:
    """Acquire frame → locate companion XML → validate → atomic save image+XML →
    atomic append record to summary.json (with lineage if given) → return result.

    Caller has positioned the stage. Returns one file per call. Multi-slice
    positions are produced by workflow loops varying (c, z) in Naming across
    successive calls."""
```

`SavedAcquisition` returns `image_path` only. XML path is derivable; workflows don't need it returned. Lineage records live inside summary.json via atomic append.

No `finalize_run`. If a workflow needs to mark a run done, add `record_status(run, status)` when that concrete need arises.

## Module layout

```
controller/vendor/_shared/output_layout/
    __init__.py
    naming.py                            # Naming, LayoutPlan, build_image_name, build_xml_name,
                                         # parse_image_name, run_hash, build_layout — one file

controller/vendor/leica/navigator_expert/
    driver/
        __init__.py                      # public API re-exports
        acquisition.py                   # NEW: start_run, acquire_and_save, internal atomic save
        file_confirmation.py             # KEEP validation primitives + parse_lasx_filename;
                                         # DELETE old SMART builders, rename_and_move, etc.;
                                         # REWRITE module docstring
        ome_tiff.py                      # unchanged
        (calibration, scanning_templates, etc.)  # off-limits

        notebooks/workflow/
            preflight.py                 # calls driver.start_run
            overview.py                  # builds Naming, calls driver.acquire_and_save
            target.py                    # same, with lineage dict
            context.py                   # Context.run = RunHandle
            _acquire.py                  # MOTION ONLY (acquire_frame + save_acquired removed)
            summary.py                   # KEPT — writes run_summary.json (rich aggregate);
                                         # driver owns summary.json (per-acquisition append log)
```

Two new modules. That's it. No `file_io.py`, no `run_manager.py`, no `summary_schema.py`. If `acquisition.py` grows past ~500 lines and has clear seams, split it then.

## Migration ordering

Four commits. Each independently runnable.

### Commit 1 — `output_layout/naming.py` + package wiring + SMB atomicity test

Pre-condition: BLOCKING-1 and BLOCKING-2 resolved; spec verified consistent.

**Package wiring (required — current sys.path does not reach `_shared/`):**
- Create `controller/vendor/_shared/__init__.py` (empty).
- Create `controller/vendor/_shared/output_layout/__init__.py` (re-exports from `naming.py`).
- Update `controller/vendor/leica/navigator_expert/test/conftest.py` to also insert `controller/vendor/` into `sys.path`. Currently it only inserts `controller/vendor/leica/`.
- Update `controller/vendor/leica/navigator_expert/notebooks/workflow/__init__.py:14-15` to insert `controller/vendor/` into `sys.path` *before* importing workflow modules. The current bootstrap only inserts `controller/vendor/leica/`; once `driver/acquisition.py` imports from `_shared`, any code path going through this bootstrap fails without it.
- Driver imports use: `from _shared.output_layout.naming import Naming, LayoutPlan, build_image_name, ...`. Document this convention in `_shared/output_layout/__init__.py` docstring.
- Update `smart_microscopy_v3.ipynb` first cell to inject `controller/vendor/` into `sys.path` alongside the existing `controller/vendor/leica/` injection.

**Schema module:**
- `Naming`, `LayoutPlan`, `build_image_name`, `build_xml_name`, `parse_image_name`, `run_hash`, `build_layout`.
- `build_layout` uses atomic `mkdir(exist_ok=False)` + bump-retry (cap: 10 attempts, fail fast — operator collision implies a real bug, not a real-world race).
- `start_time_utc` persisted in `LayoutPlan`; hash computed once at construction. Never recomputed elsewhere.
- Validators: `experiment ≤ 40 chars` (kebab-case + underscore allowed), `acquisition_type` kebab-case `≤ 25 chars`. Both caps recorded as comments with rationale in `naming.py` — not silent.
- Unit tests: round-trip parse/build, base36 encode/decode, collision-bump correctness, length caps, kebab-case validation, adversarial inputs.

No SMB atomicity test needed — `output_root` lives on the same filesystem as the vendor's media_path (typically local NTFS), so `mkdir(exist_ok=False)` and `os.replace` atomicity are guaranteed by the OS. If a future driver targets a network-only media_path, revisit then.

Zero callers.

### Commit 2 — `driver/acquisition.py` + crash-recovery test

- `start_run`, `acquire_and_save`, `RunHandle`, `SavedAcquisition`.
- Internal helpers (file-private): `_find_companion_xml`, `_save_atomic`, `_append_summary_atomic`.

**`_save_atomic` contract** (precise operation order, addressing both reviews):
1. Copy image to `image_dest.tmp` (e.g. `shutil.copy2(src, image_dest.tmp)`).
2. Copy XML to `xml_dest.tmp` (if XML expected).
3. Validate both `.tmp` files match their source file size exactly. Size match catches truncation, the realistic failure mode under partial copies (disk full, network blip). Silent bit corruption is not caught — that responsibility lies with the filesystem. OME integrity is validated source-side before this function; same-size copy on success is trusted.
4. **Only after both `.tmp` files exist and validate**, do `os.replace(image_dest.tmp, image_dest)` followed by `os.replace(xml_dest.tmp, xml_dest)`.
5. On any exception in steps 1–4: unlink any `.tmp` files this call created, no `os.replace` runs, no final paths appear.
6. On exception between step 4's two `os.replace` calls (extremely narrow window): unlink the second `.tmp`; the first `os.replace` may have committed an image without its XML — log the partial state loudly, but this is a hardware-level race that can only happen on filesystem failure mid-syscall.

Never `shutil.copy2(src, dest)` directly to the final path — partial-file-with-final-name on network blip is the bug this prevents.

**`_append_summary_atomic` contract:** read current summary, append record, write to `summary.json.tmp`, `os.replace` to `summary.json`. **Single-threaded contract:** `acquire_and_save` MUST be called from one thread. The current v3 workflow is serial (`engine.submit` runs analysis after acquisition returns); no lock needed. Document this constraint in the docstring. If a future workflow needs concurrent acquisitions, revisit then.

- Path-length sentinel runs inside `start_run`: builds worst-case path under documented caps; if >250 chars, raise.
- Re-export from `driver/__init__.py`. **Do not remove old SMART symbols yet.**
- Unit tests against `mock_lasx_api.py`: end-to-end driver flow with no workflow code.

**Crash-recovery integration test** (single test, stdlib-only — no special pytest fixtures):
- Spawn subprocess via `subprocess.Popen` running a minimal `start_run → 3× acquire_and_save` script.
- After ~2 acquisitions, terminate it with `.kill()` (Windows-compatible; **not** `signal.SIGKILL`, which doesn't exist on Windows).
- In the parent process: verify `summary.json` parses cleanly, run_dir is scannable, no half-written files. Stale `.tmp` files from the kill are acceptable since the next `start_run` rejects pre-existing run dirs.

### Commit 3 — workflow migration (REVISED scope after summary.py reality check)

The original plan called `summary.py` a thin shim and proposed deleting it. On reading, it isn't — it writes a rich aggregate (config snapshot, focus map, scan_field, preflight telemetry, overview stats, picks, target records) at end-of-run. The driver's `summary.json` is a per-acquisition append log; the workflow's aggregate is a different concern. **Resolution (2026-05-11): keep `summary.py`, change its output filename to `run_summary.json`. Driver owns `summary.json` (canonical append log); workflow owns `run_summary.json` (rich aggregate).** One file each, no schema merging.

This collapses Commit 3 to five focused edits:

- `preflight.py:115-119`: replace timestamp + mkdir block with:
  ```python
  ctx_run = drv.start_run(client, cfg.experiment)
  out_dir = ctx_run.layout.run_dir
  out_dir.joinpath("logs").mkdir(parents=True, exist_ok=True)
  ```
  Add `run=ctx_run` to Context construction. (No `output_root` arg — derived inside `start_run`.) Also: replace `Config.output_root: Path` with `Config.experiment: str`.

- `overview.py:122-129`: position via existing `acquire()` motion helper, then call driver:
  ```python
  acquire(ctx, cfg.acquisition_job, x_um, y_um, zwide_um)          # motion only (modified)
  naming = Naming(acquisition_type="overview-scan",
                  hash6=ctx.run.layout.hash6, g=int(rid), p=i)
  result = drv.acquire_and_save(ctx.client, ctx.run, cfg.acquisition_job, naming)
  ```
  Use `result.image` and `result.image_path` for engine.submit.

- `target.py:135-142`: same two-call pattern, with `lineage={"source_tile_rid": ..., "row": ..., "col": ..., "label": ..., "parent_image_path": ...}` passed to `acquire_and_save`.

- `notebooks/workflow/_acquire.py`: **keep — motion only.** Remove the trailing `acquire_frame` call from `acquire()` (driver does it now) and remove `save_acquired` entirely. Update `acquire()` docstring to clarify it now positions the stage only and returns None.

- `notebooks/workflow/summary.py`: **one-line rename** of the output file from `summary.json` to `run_summary.json` in `write_summary` (line 111). Everything else stays. Re-exports in `workflow/__init__.py:21,28` stay. v3 notebook Cells 13–14 stay (they still call `write_summary`, `plot_results`, `finish`).

Integration smoke test: full workflow against mock LAS X, assert canonical file tree shape and that both `summary.json` (driver) and `run_summary.json` (workflow) exist at run_dir top level. Assert `import navigator_expert.notebooks.workflow` succeeds.

**Follow-up cleanup (future, not this commit):** the driver's `summary.json` is really a per-acquisition event log, not a summary. A future rename to `acquisitions.jsonl` (JSONL semantics, one record per line) would be more honest and free up the `summary.json` name to mean what humans expect. The spec doesn't strictly mandate the name, just that a run-level file sits at run_dir top level. Note for later; no change this commit.

### Commit 4 — driver SMART-naming removal + cleanup

- **Grep all callers** of: `_build_image_name`, `_build_xml_name`, `rename_and_move`, `predict_manifest`, `confirm_acquisition`, `next_position_index`, `_RE_TARGET_IMAGE`. For each caller: port to new API, or delete. No deprecated shims. (`_parse_target_name` was listed in earlier drafts but never existed in the codebase — phantom.)
- **`confirm_acquisition` has no callers** (verified by both reviews). The grep hit at `driver/notebook_workflow.py:357` is a substring false-positive — that's a *private* `_confirm_acquisition(sequence, config)` at `notebook_workflow.py:614`, an unrelated `input("Type ACQUIRE…")` prompt helper. Do not touch it. Delete the driver-level `confirm_acquisition` unconditionally.
- Delete from `driver/file_confirmation.py`: `_build_image_name`, `_build_xml_name`, `rename_and_move`, `predict_manifest`, `confirm_acquisition`, `next_position_index`, `_RE_TARGET_IMAGE`, and the private OME-path patching helpers used only by `rename_and_move` (`_replace_full_path_in_xml`, `_set_ome_paths_tiff`, `_set_ome_paths_xml`) and `_result`. (`_parse_target_name` never existed.)
- **Rewrite `file_confirmation.py` module docstring.** Current docstring (lines 1–50) describes the deleted ten-step SMART workflow. After deletions the module is "LAS X source-side primitives" (parsing + validation + discovery). Rewrite to reflect this, or rename the file to `lasx_source.py` if rename is cheap.
- Update `driver/__init__.py`: remove deleted symbols from imports + `__all__` (lines 159, 162, 435, 440, 442). Run `python -c "import navigator_expert.driver"` as a hard test.
- Final grep across all repos to confirm no stale callers.

## What stays in `driver/file_confirmation.py`

Kept and used by `acquisition.py`:
- `parse_lasx_filename` — LAS X source filename segment parser
- `read_relative_path` — baseline string
- `detect_new_files` — fallback companion XML discovery
- `wait_all_stable` — file stability gate
- `check_ome_tiff`, `check_ome_xml_file`, `fix_ome_tiff`, `fix_ome_xml_file`

## Risks

1. **Driver API is load-bearing.** Changing `acquire_and_save` signature breaks every workflow. Lock the API before Commit 2.

2. **`driver/notebook_workflow.py:357` and other legacy callers.** Q9 (folded into Commit 4) must resolve. No deprecated shims.

3. **Clock non-monotonicity.** `time.time()` step-back on NTP/VM resume corrupts hash chronological-sort invariant. `start_run` calls `time.time()` once, persists to `RunHandle.start_time_utc`. No other code calls `time.time()` for hash purposes.

4. **`pick_sequence` instability across re-runs.** Mitigated by Q4: deterministic analysis + lineage dict carrying `(source_tile_rid, row, col, label)`.

5. **Kernel kill mid-z-stack leaves orphan files.** `summary.json` is atomic, so consistent on restart. Data dir may have orphan TIFFs from incomplete acquisitions. `start_run` on a pre-existing run dir is *rejected* by `mkdir(exist_ok=False)` — operator must explicitly delete the orphan dir or supply a different experiment name. Document this behavior; do not add resume semantics until a workflow actually needs them.

6. **`media_path` must be writable at runtime.** Driver does `(media_path / "smart").mkdir(parents=True, exist_ok=True)`. If LAS X is configured to export to a directory the python process can't write into (rare but possible), `start_run` raises with a clear message.

7. **`media_path` length eats path budget.** Convention adds ~145 chars under `media_path / smart`. If `media_path` itself is longer than ~80 chars, the path-length sentinel in `start_run` will fail. Operator must configure LAS X to export to a shallow path (e.g. `D:\LASX\` rather than `D:\Users\someuser\Documents\Leica\Exports\`).

## Critical files

**New:**
- `controller/vendor/_shared/output_layout/naming.py`
- `controller/vendor/_shared/output_layout/test/test_naming.py`
- `controller/vendor/leica/navigator_expert/driver/acquisition.py`
- `controller/vendor/leica/navigator_expert/driver/test/test_acquisition.py`

**Modified:**
- `controller/vendor/leica/navigator_expert/driver/__init__.py` — re-exports updated Commit 2, old symbols removed Commit 4 (lines 159, 162, 435, 440, 442)
- `controller/vendor/leica/navigator_expert/driver/file_confirmation.py` — old SMART functions deleted Commit 4; **module docstring rewritten** to match remaining surface
- `controller/vendor/leica/navigator_expert/notebooks/workflow/preflight.py:115-134`
- `controller/vendor/leica/navigator_expert/notebooks/workflow/overview.py:122-129`
- `controller/vendor/leica/navigator_expert/notebooks/workflow/target.py:135-142`
- `controller/vendor/leica/navigator_expert/notebooks/workflow/context.py`
- `smart_microscopy_v3.ipynb` config cell

**Modified (motion-only / one-line):**
- `controller/vendor/leica/navigator_expert/notebooks/workflow/_acquire.py` — `acquire()` keeps motion (ensure_job_state + move_z zwide + backlash + move_xy); `acquire_frame` call removed, `save_acquired` deleted.
- `controller/vendor/leica/navigator_expert/notebooks/workflow/summary.py` — output filename: `summary.json` → `run_summary.json` (one-line change at line 111). Driver owns `summary.json` as canonical per-acquisition log; workflow owns `run_summary.json` as rich aggregate.

**Commit 4 grep targets:**
- `controller/vendor/leica/navigator_expert/driver/notebook_workflow.py:357` — **substring false-positive**, do not port. That line calls the private `_confirm_acquisition` at `notebook_workflow.py:614`, which is an `input("Type ACQUIRE…")` prompt helper unrelated to the driver `confirm_acquisition`. Leave it alone.
- `controller/vendor/leica/navigator_expert/notebooks/legacy_*.ipynb` (if active)

**Read-only consumers (verified safe per cross-repo grep):**
- `smart-analysis/workflows/target_acquisition/steps/segment_tile.py:80-81` — `tifffile.imread`, opaque path, no parsing
