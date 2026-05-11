# Implementation Plan: Lab-Wide Output Naming Convention + Validated File Handling

Drafted 2026-05-08 against `cleanup/wave-2`. **Revised 2026-05-11** twice: first after the convention substantially evolved (flat layout, hash-based dirs, vendor-neutral module); second after two independent reviews surfaced design gaps. The earlier draft (carrier/compartment as folders, segmented `G_P_T_J_V_C_Z` naming, timestamp dirs) is superseded.

Canonical convention spec lives in auto-memory `smart_microscopy_smart_folder_structure.md`. This plan is the implementation path for landing it in code.

**Changes from the prior revision (review-driven):**
- Q4 surfaces a `pick_sequence` stability problem — analysis nondeterminism (cellpose GPU/CPU, segmentation order) breaks cross-run filename comparison
- Q7 reframed as a binary spec decision (packed vs per-slice) — current draft is internally contradictory
- New Q8: retry/attempt/registration slot was dropped without analyzing closed-loop reacquisition collisions
- New Q9: legacy `driver/notebook_workflow.py` blast radius before deleting `confirm_acquisition`
- Collision handling specified as atomic `mkdir(exist_ok=False)` retry, not TOCTOU check-then-create
- `summary.json` schema promoted from optional commit 8 to core commit 1 (it carries load-bearing lineage; non-atomic write is a single point of failure)
- New risks: clock non-monotonicity (`time.time()` step-back), network-share latency in acquisition hot loop, source-tile lineage loss
- Critical Files expanded: `driver/notebook_workflow.py:357`, `driver/__init__.py` re-exports, `driver/file_confirmation.py:165, 177-197` (`next_position_index`)

## Open questions for the user (READ FIRST — block on answers before code)

### Q1. Output root location

`output_root` must be a shallow path to leave Windows MAX_PATH budget (LongPathsEnabled = 0 on this machine). Convention is ~145 chars; current `controller/vendor/leica/navigator_expert/output/` eats too much prefix.

**Recommend:** `Z:\smart-data\` — keeps it on the network share, single short namespace, ~110 chars saved vs current. Alternative: `C:\ProgramData\MinicondaZMB\home\t.de\smart-data\` (local, faster I/O, no network hiccups).

### Q2. Module placement (vendor-neutral home)

The convention is vendor-neutral and lab-wide. The naming/layout module must live where any current and future smart-microscopy workflow (under any driver) can import it.

**Options:**
- **A.** New sibling of `controller/vendor/`: `controller/output_layout/` (lives in the smart-microscopy repo, importable by anything under `controller/`)
- **B.** Pull out into its own top-level package, e.g. `smart_io/` — importable by sibling repos (`smart-analysis`, `smart-selection`) too
- **C.** Start at A, promote to B when a second consumer needs it

**Recommend C.** Move now would touch too many repos at once; promote when there's an actual second consumer.

### Q3. `experiment` source

There's no `experiment` field in `Config` today. Convention requires it.

**Recommend:** required `Config.experiment: str` (no default), operator types it in the notebook config cell. Alternative: auto-derive from LAS X experiment name at preflight (brittle).

### Q4. v3 → canonical slot mapping (REVISED — surfaces a stability problem)

v3 has internal coordinates `(rid, row, col, label)`. The canonical schema has `k/m/g/p/t/v/c/z`. The mapping is workflow-specific.

**Draft mapping (provisional, see stability problem below):**
- **Overview-scan:** `g = int(rid)` (round = group), `p = tile_sequence` (0..N within round, linearized over row×col). Tile `(row, col)` not in filename — recorded in `summary.json` and OME-XML metadata.
- **Target-acquisition:** `g = int(rid)`, `p = pick_sequence` (0..M within round). Source-tile lineage recorded in `summary.json`.
- All other slots (`k`, `m`, `t`, `v`) default to 0 for v3. `c`, `z` carried through from LAS X export (or dropped if Q7 picks packed).

**Stability problem — needs a decision before this mapping is safe:**

`p = pick_sequence` depends on the analysis pipeline's iteration order over detected objects. Cellpose with GPU vs CPU produces different segmentation orderings; non-deterministic torch operations can re-order detections across re-runs. The same physical cell can get `p=3` in one run and `p=7` in a re-run — making cross-run filename comparison silently wrong.

**Options:**
- **(a)** Encode source-tile lineage into the slot itself: `p = source_tile_seq * 1000 + label_within_tile`. Pick id within a tile is determinate if analysis is rerun on the same tile (cellpose seed-able). Cross-tile picks are still ordered by tile, which is stable.
- **(b)** Make analysis deterministic — pin cellpose to CPU + fixed seed, sort detections by `(y, x)` pixel coordinate before assigning `p`. Cheap, robust, doesn't change schema.
- **(c)** Accept `p` is run-scoped only; never compare across runs by filename. Must be documented loudly in the spec.
- **(d)** Skip filename lineage entirely, write a per-image sidecar `.lineage.json` alongside `.ome.tiff` + `.ome.xml` that carries `(source_tile_rid, row, col, label, parent_image_path)`. Travels with the image as an atomic unit.

**Recommend (b)+(d) combined.** Make analysis deterministic to give filenames a chance at cross-run stability, AND add per-image lineage sidecar so reconstruction doesn't depend on `summary.json` being intact.

Filename schema stays *dimension-pure*; v3's encoding lives in metadata + per-image sidecars.

### Q5. Cleanup of LAS X source files after copy

Legacy `driver/file_confirmation.confirm_acquisition` defaults to `cleanup_source=True` (deletes the source after copy). v3's current `save_acquired` leaves source alone.

**Recommend:** `cleanup_source=False` for v3 — keep source until the run completes successfully, then optionally batch-cleanup. Re-runs over the same files stay safe.

### Q6. OME corruption handling

`drv.fix_ome_tiff` rewrites the source file in place to fix corrupted OME headers.

**Recommend:** `fix_ome=False` (fail loud, leave source untouched). Opt in per acquisition type if a workflow has known-bad export.

### Q7. Channel/Z packing in OME-TIFF (REFRAMED — current draft is contradictory)

The spec says "All slots always present, default to zero when unused." But the prior draft of this plan introduced a `packed=True` mode that *drops* `c` and `z` from the image filename. Those positions are incompatible. Pick one canonical profile:

**Option A — packed always, drop `c` and `z` from image filename:**
- Image: `[acquisition-type]_[hash6]_k[NNNNN]_m[NNNNN]_g[NNNNN]_p[NNNNN]_t[NNNNN]_v[NN].ome.tiff`
- XML: same base, `.ome.xml` extension
- Channel and z-slice live inside the OME-TIFF as internal dimensions, described by the embedded OME-XML
- Update spec: `c` and `z` are *internal-only* slots, present in `Naming` for in-memory use, omitted from filename
- Pro: matches how LAS X actually exports; one file per acquisition position; avoids 5×c×z file explosion
- Con: image and XML share base name + differ by extension only — that's standard OME-TIFF practice, but `parse_image_name` must handle both `.ome.tiff` and `.ome.xml` and they yield identical `Naming` minus extension

**Option B — per-slice always, `c` and `z` always in image filename:**
- Image: `[acquisition-type]_[hash6]_k[NNNNN]_m[NNNNN]_g[NNNNN]_p[NNNNN]_t[NNNNN]_v[NN]_c[NN]_z[NNNNN].ome.tiff`
- XML: drop `c` and `z` (one XML per acquisition position, describes the full c×z grid)
- Pro: schema is uniform — all 8 slots always present in image filenames; `parse_image_name` is total
- Con: 5×c×z file explosion (a single z-stack of 30 slices × 4 channels = 120 files instead of 1); requires post-processing to merge if downstream wants packed OME-TIFFs

**Recommend A**, but **the spec must be updated to declare `c` and `z` as "internal slots"** — present in `Naming` dataclass, omitted from `build_image_name`. The current "all slots always present" language is wrong and must be amended before implementation. Do not implement until this language is fixed in the spec.

### Q8. Retry / attempt / registration slot — does the schema need one?

The convention dropped `r` (registration index) on 2026-05-11 without analyzing closed-loop reacquisition. **Real failure mode in closed-loop microscopy:**
- Operator (or controller) detects autofocus drift mid-acquisition and reacquires the same `(k, m, g, p, t, v)` target
- QC step rejects a tile due to motion blur; controller reshoots
- Drift-correction registration acquires the same field multiple times to align

Under the current schema, **all of these collide on identical filenames**. Two interpretations:
- **Hard contract: "no reacquisitions, ever."** Reshoots overwrite the original. Acceptable only if the original is genuinely discarded and the bad data is not preserved for analysis.
- **Soft contract: "we sometimes keep both."** Need a slot to disambiguate.

**Workflows that probably need a retry slot:** target acquisition with autofocus rescue (v3's stated direction), screening with QC-driven reshoot, drift-correction registration acquisitions.

**Options:**
- **(a)** Add `r[NNN]` slot back, default `r000`, present always (uniform parser).
- **(b)** Add it as an optional slot appended only when >0. Breaks parser uniformity (same problem as Q7).
- **(c)** Hard contract: spec says "reacquisitions overwrite originals; if both must be kept, encode in `t` with a documented sub-second scheme." Fragile.

**Recommend (a).** 3 chars, schema stays uniform, common case is `r000` (no cost), reacquisitions get a clean integer. Reverses the 2026-05-11 decision; user should confirm.

### Q9. Legacy `notebook_workflow.py` blast radius — what's its deprecation status?

`controller/vendor/leica/navigator_expert/driver/notebook_workflow.py:357` calls `confirm_acquisition` (which Commit 6 plans to delete or refactor). The plan does not enumerate this dependency or other callers under `notebooks/` outside `notebooks/workflow/`.

**Before Commit 6:**
- Grep for all callers of `confirm_acquisition`, `rename_and_move`, `_build_image_name`, `_build_xml_name`, `predict_manifest`, `next_position_index`, `_parse_target_name`, `_RE_TARGET_IMAGE`.
- For each caller in legacy notebooks: decide (preserve / port / delete).
- If `notebook_workflow.py` and the legacy `legacy_*.ipynb` notebooks are still operationally used, Commit 6 must either keep `confirm_acquisition` (refactored to use new builders) or migrate the callers.

**Recommend:** start by enumerating callers (one grep, written into this plan) before Commit 6 begins. If callers exist, add a "Commit 5b: migrate legacy callers" step before Commit 6 deletes anything.

## What we know for certain (from code reading on cleanup/wave-2)

1. `save_acquired` lives at `controller/vendor/leica/navigator_expert/notebooks/workflow/_acquire.py:59-79`. Behavior: `destination.parent.mkdir(parents=True, exist_ok=True)`, then `shutil.copy2(lasx_path, destination)` if source exists, else `tifffile.imwrite`. **No validation.** No stability check. No size check. No OME readability check. No XML companion handling.

2. Two callers: `overview.py:127` and `target.py:140`. Both build `ctx.out_dir / "<overview|target>" / <semantic_name>.tif` and pass `(image, lasx_path, destination)`.

3. `drv.acquire_frame(client, job)` returns `(image, lasx_path)` — single TIFF path, OME companion XML is not tracked or copied.

4. `summary.json` consumers in-repo: only `workflow/summary.py` writes them; no other code reads them. The `tif_path` shape change is internal-only.

5. Driver re-exports validation primitives via `navigator_expert.driver.__init__.py`: `wait_all_stable`, `validate_files`, `check_ome_tiff`, `check_ome_xml_file`, `fix_ome_tiff`, `detect_new_files`, `read_relative_path`. No driver code modification needed to *use* them.

6. The driver's `_build_image_name` / `_build_xml_name` / `rename_and_move` build the **old SMART naming** (`G00000_P00000_T00000_J08_V00_C00_Z00000.ome.tiff` in `Carrier_000/Compartment_Z00_Y00_X00/` folders, timestamp-first dir). These functions will be **deleted** as part of this work — replaced by the new vendor-neutral builders. This is the part of the driver that's deliberately being restructured (the user's call, 2026-05-11). Calibration logic remains off-limits.

7. Current `cfg.output_root` is `...\output\target_acquisition` (per v3 notebook config cell). Will be replaced by `Z:\smart-data\` (Q1).

8. No existing tests touch `save_acquired` or workflow output layout. Test infra: `test/conftest.py` adds `sys.path`; `test/test_focus_map_unit.py` shows the import pattern.

9. **Legacy `confirm_acquisition` consumer:** `driver/notebook_workflow.py:357` imports and calls `confirm_acquisition`. Status of this file (active / legacy / deprecated) is unknown — see Q9. Must enumerate before deleting `confirm_acquisition`.

10. **Driver public re-exports of soon-to-be-deleted symbols:** `driver/__init__.py` re-exports `_build_image_name`, `_build_xml_name`, `rename_and_move`, `predict_manifest`, `confirm_acquisition`, `next_position_index` (lines 159, 162, 435, 440, 442 per Source 2 review). Commit 6 must update these exports or the package fails to import — violates "each commit runnable."

11. **`next_position_index` (`driver/file_confirmation.py:177-197`) and `_RE_TARGET_IMAGE` (line 165) parse the old SMART format.** Not in the original deletion list. After Commit 6 they're dead code parsing a format that no longer exists. Either delete or migrate (probably delete; grep for callers first).

12. **`summary.json` write is non-atomic** (`workflow/summary.py:111-112`: `out_path.write_text(...)`). A crash mid-acquisition leaves acquired TIFFs on disk with no `summary.json` → operator has no way to know which pick is which. Since `summary.json` carries load-bearing lineage (Q4), this is a single point of failure.

13. **Only external consumer of acquisition files** (per Source 2 grep): `smart-analysis/workflows/target_acquisition/steps/segment_tile.py:80-81` reads `image_path` opaquely via `tifffile.imread`. No filename parsing, no path-shape assumptions. Migration safe for current consumers.

## Proposed design

### New module: vendor-neutral output layout

Location per Q2 (`controller/output_layout/` recommended). Pure functions + dataclasses, no I/O except path math.

```python
# output_layout/naming.py

import time
from dataclasses import dataclass
from pathlib import Path

EPOCH = 1767225600  # 2026-01-01 00:00:00 UTC, seconds since unix epoch
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"  # base36 lowercase

def run_hash(start_time: float | None = None) -> str:
    """6-char base36 hash of seconds-since-convention-epoch.
    Lexicographically sortable, chronologically meaningful."""
    t = start_time if start_time is not None else time.time()
    n = int(t - EPOCH)
    if n < 0:
        raise ValueError(f"start_time {t} is before convention epoch {EPOCH}")
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = ALPHABET[r] + s
    return s.rjust(6, "0")

@dataclass(frozen=True)
class Naming:
    acquisition_type: str   # kebab-case, e.g. "overview-scan"
    hash6: str              # 6-char base36
    k: int = 0              # carrier (5 digits)
    m: int = 0              # compartment (5 digits)
    g: int = 0              # group (5 digits)
    p: int = 0              # position (5 digits)
    t: int = 0              # time (5 digits)
    v: int = 0              # view (2 digits)
    c: int = 0              # channel (2 digits) — present in schema even when packing
    z: int = 0              # z-slice (5 digits) — present in schema even when packing

def build_image_name(n: Naming, *, packed: bool = True) -> str:
    """Build the canonical image filename.
    packed=True: omits c, z (multi-channel/multi-z inside the file). Default.
    packed=False: includes c, z (per-slice files)."""
    base = (f"{n.acquisition_type}_{n.hash6}"
            f"_k{n.k:05d}_m{n.m:05d}_g{n.g:05d}_p{n.p:05d}_t{n.t:05d}_v{n.v:02d}")
    if not packed:
        base += f"_c{n.c:02d}_z{n.z:05d}"
    return base + ".ome.tiff"

def build_xml_name(n: Naming) -> str:
    """Build the canonical XML companion filename. Always omits c, z."""
    return (f"{n.acquisition_type}_{n.hash6}"
            f"_k{n.k:05d}_m{n.m:05d}_g{n.g:05d}_p{n.p:05d}_t{n.t:05d}_v{n.v:02d}.ome.xml")

def parse_image_name(filename: str) -> Naming | None:
    """Inverse of build_image_name. Returns None if filename doesn't match schema."""
    # Regex-based parse; returns Naming dataclass.
    ...
```

```python
# output_layout/layout.py

@dataclass(frozen=True)
class LayoutPlan:
    output_root: Path
    experiment: str
    hash6: str

    @property
    def run_dir(self) -> Path:
        return self.output_root / f"{self.experiment}_{self.hash6}"

    def acquisition_dir(self, kind: str) -> Path:
        return self.run_dir / kind

    def data_dir(self, kind: str) -> Path:
        return self.acquisition_dir(kind) / "data"

    def metadata_dir(self, kind: str) -> Path:
        return self.data_dir(kind) / "metadata"

    def analysis_dir(self, kind: str) -> Path:
        return self.acquisition_dir(kind) / "analysis"

    def feedback_dir(self, kind: str) -> Path:
        return self.acquisition_dir(kind) / "feedback"

def build_layout(output_root: Path, experiment: str, start_time: float | None = None) -> LayoutPlan:
    return LayoutPlan(
        output_root=Path(output_root),
        experiment=experiment,
        hash6=run_hash(start_time),
    )
```

Acceptance: `build_image_name(parse_image_name(name)) == name` round-trip for any well-formed name. Workflows that don't use a slot leave it at default 0.

### New module: validated save

Location: `controller/vendor/leica/navigator_expert/notebooks/workflow/_save.py` (v3-specific consumer). The save logic itself uses driver validation primitives that are vendor-portable; only the discovery (LAS X-specific `detect_new_files`) is Leica-specific.

```python
def save_acquired_validated(
    image: np.ndarray,
    lasx_path: Path | None,
    lasx_xml_path: Path | None,
    destination_image: Path,
    destination_xml: Path | None,
    *,
    stability_timeout_s: float = 30.0,
    min_size: int = 1024,
    fix_ome: bool = False,
) -> SaveResult: ...
```

Steps:
- If `lasx_path` is given: `drv.wait_all_stable([lasx_path] + ([lasx_xml_path] if xml else []), timeout=stability_timeout_s)`. Unstable → raise.
- `drv.check_ome_tiff(lasx_path)`. If corrupted and `fix_ome` → `drv.fix_ome_tiff`. If still bad → raise.
- `mkdir(parents=True, exist_ok=True)` on parents.
- `shutil.copy2` image and XML. On `OSError`, fallback to `tifffile.imwrite(image)` and log warning.
- Verify destination exists and is non-zero (mini `confirm_arrival`).
- Return `SaveResult(image_path, xml_path, validation_issues, fallback_used)`.

### `acquire_with_artifacts` wrapper

`drv.acquire_frame` returns only the image path. The XML companion has to be located via `drv.detect_new_files` (or a slim variant that looks in `<source_dir>/metadata/` given the source TIFF path — see Risk 3).

```python
def acquire_with_artifacts(ctx, job, x, y, z) -> tuple[np.ndarray, Path, Path | None]:
    """Acquire and locate both image + companion XML."""
    ...
```

### Driver changes

The driver's old SMART naming functions get **deleted**:
- `driver/file_confirmation.py:_build_image_name` — delete
- `driver/file_confirmation.py:_build_xml_name` — delete
- `driver/file_confirmation.py:_parse_target_name` — delete (was for old SMART target format)
- `driver/file_confirmation.py:predict_manifest` — refactor or delete (it predicted old SMART filenames)
- `driver/file_confirmation.py:rename_and_move` — delete or rewrite using new builders

Kept:
- `parse_lasx_filename` (parses LAS X source segments — vendor-specific, still needed)
- `read_relative_path`, `detect_new_files`, `wait_all_stable`, `validate_files`, `check_ome_*`, `fix_ome_*` (vendor-neutral or LAS X-specific but still useful)

`confirm_acquisition` orchestrator is refactored: still does 8 steps (detect → wait → validate → rename → confirm), but the rename step calls the new `build_image_name`/`build_xml_name` from `controller/output_layout/` instead of the old SMART builders.

### v3 wiring

`overview.py:122-129`:
```python
# before:
image, lasx_path = acquire(ctx, cfg.acquisition_job, x_um, y_um, zwide_um)
tif_name = f"tile_R{rid:>02s}_r{tile['row']:02d}_c{tile['col']:02d}.tif"
tif_path = save_acquired(image, lasx_path, ctx.out_dir / "overview" / tif_name)

# after:
image, lasx_path, lasx_xml = acquire_with_artifacts(ctx, cfg.acquisition_job, x_um, y_um, zwide_um)
naming = Naming(
    acquisition_type="overview-scan",
    hash6=ctx.layout.hash6,
    g=int(rid),
    p=_overview_tile_seq(tile, ctx),  # 0..N within round
)
image_dst = ctx.layout.data_dir("overview-scan") / build_image_name(naming, packed=True)
xml_dst = ctx.layout.metadata_dir("overview-scan") / build_xml_name(naming)
result = save_acquired_validated(image, lasx_path, lasx_xml, image_dst, xml_dst)
tif_path = result.image_path
```

`target.py:135-142` analogous, with `acquisition_type="target-acquisition"` and `p=_target_pick_seq(pick, ctx)`.

### Config / Context

`Config`:
- Add required `experiment: str` (no default)
- Update docstring: `output_root` is parent dir of `[experiment]_[hash6]/`

`Context`:
- Add `layout: LayoutPlan` (built in preflight)
- Add `media_path: str` (cached LAS X export root, for `detect_new_files`)
- Keep `out_dir` as `layout.run_dir` for backward compat with `summary.py`, `focus.py`, `template.py`

`preflight.py:115-119`:
```python
# before:
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir = Path(cfg.output_root) / timestamp
(out_dir / "overview").mkdir(...)
(out_dir / "target").mkdir(...)

# after:
layout = build_layout(cfg.output_root, cfg.experiment)
out_dir = layout.run_dir
for kind in ("overview-scan", "target-acquisition"):
    layout.data_dir(kind).mkdir(parents=True, exist_ok=True)
    layout.metadata_dir(kind).mkdir(parents=True, exist_ok=True)
    layout.analysis_dir(kind).mkdir(parents=True, exist_ok=True)
    layout.feedback_dir(kind).mkdir(parents=True, exist_ok=True)
out_dir.joinpath("logs").mkdir(parents=True, exist_ok=True)
```

### `summary.json` update

- `rec.tif_path.relative_to(out_dir)` keeps working (both still exist). Relative path string just gets longer and structured.
- `summary.py:47` `"timestamp": ctx.out_dir.name` becomes `[experiment]_[hash6]`. Split into separate fields: `"experiment": cfg.experiment`, `"hash6": ctx.layout.hash6`, `"acquired_at": iso_timestamp(ctx.layout.start_time)`. The last gives wall-clock for human inspection.
- Add per-record canonical-coord fields so summary.json carries the decoding of the integer slots: `{"k": 0, "m": 0, "g": 0, "p": 3, ...}` alongside `tif_path`. Loses nothing, gains: any downstream tool can read summary.json instead of parsing filenames.

### Path-length sentinel + input caps

Both inputs to the path need explicit bounds (Source 2 review #5):

```python
# In Naming / LayoutPlan validators:
MAX_EXPERIMENT_LEN = 40        # operator-typed string
MAX_ACQUISITION_TYPE_LEN = 25  # workflow-defined kebab-case token

if len(experiment) > MAX_EXPERIMENT_LEN:
    raise ValueError(f"experiment name too long ({len(experiment)} > {MAX_EXPERIMENT_LEN})")
if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", acquisition_type) or len(acquisition_type) > MAX_ACQUISITION_TYPE_LEN:
    raise ValueError(f"acquisition_type must be kebab-case lowercase, ≤{MAX_ACQUISITION_TYPE_LEN} chars")
```

Then the preflight sentinel checks against the documented caps, not hand-crafted worst cases:

```python
longest_acq_type = "x" * MAX_ACQUISITION_TYPE_LEN
worst_filename = build_image_name(Naming(longest_acq_type, layout.hash6, k=99999, m=99999, g=99999, p=99999, t=99999, v=99))
worst_path = layout.metadata_dir(longest_acq_type) / worst_filename.replace(".ome.tiff", ".ome.xml")
if len(str(worst_path)) > 250:
    raise ValueError(
        f"Worst projected path {len(str(worst_path))} chars exceeds 250 — "
        f"shorten output_root. Path: {worst_path}"
    )
```

Fails fast on the first run with a too-long config, rather than mid-acquisition.

## Migration ordering — proposed commits (REVISED)

Each commit independently runnable, ends at green tests. **Key change vs prior revision:** `summary.json` schema is now in Commit 1, not optional Commit 8 — it carries load-bearing lineage and must be atomic from day one.

**Commit 1 — vendor-neutral path-builder + summary schema, no callers**
- Add `controller/output_layout/`. Files: `__init__.py`, `naming.py`, `layout.py`, `summary.py`.
  - `Naming`, `LayoutPlan`, `build_image_name`, `build_xml_name`, `parse_image_name`, `run_hash`, `build_layout`.
  - Input validators: experiment ≤40 chars, acquisition_type kebab-case ≤25 chars.
  - `build_layout` uses atomic `mkdir(exist_ok=False)` + bump-retry-loop for collision handling (see Risk 5). Persists `start_time` so the hash is computed once and never recomputed.
- Define `summary.json` schema (frozen dataclasses + JSON serializer): `experiment`, `hash6`, `acquired_at_utc`, `schema_version`, per-record canonical-coord fields (`k`, `m`, `g`, `p`, `t`, `v`, `c`, `z`), lineage fields (source-tile pointer for target picks).
- Add `write_summary_atomic(path, data)` helper using tempfile + `os.replace`.
- Unit tests: `test_naming.py`, `test_layout.py`, `test_summary_schema.py`. Round-trip, base36, kebab-case validation, length caps, layout helpers, atomic write under simulated crash, collision-bump correctness.
- Old `tile_R00_*.tif` / `pick_R00_*.tif` paths still used. Notebook unaffected.

**Commit 2 — Config / Context / preflight plumbing**
- `Config.experiment: str` required (validated against length cap).
- `Context.layout`, `Context.media_path`, `Context.start_time_utc` (persisted from preflight, **never recomputed** — protects against `time.time()` step-back; see Risk 8).
- `preflight` builds layout, creates new tree, caches media path, runs path-length sentinel.
- Notebook config cell updated to set `experiment="..."` and shallow `output_root`.
- `overview.py` / `target.py` still write old flat names, just one level deeper. Half-migrated on purpose.

**Commit 3 — `save_acquired_validated` + `acquire_with_artifacts`**
- New `notebooks/workflow/_save.py`.
- **Image+XML treated as atomic unit:** both arrive or both fail. If XML expected but missing → raise (per spec "fail loudly if XML is missing when expected").
- If Q4 chose option (d), also writes per-image `.lineage.json` sidecar atomically.
- Unit tests with mock driver: stability passes/fails, OME ok/corrupted+fix/corrupted+nofix, fallback to numpy, **XML missing → raises**, **XML corrupt → raises**, **image without XML → raises**, **XML without image → raises** (the atomic-unit contract that Source 2 #13 flagged as untested).
- Not yet wired into `overview.py`/`target.py`.

**Commit 4 — switch `overview.py`**
- `acquire_with_artifacts` + `save_acquired_validated` + new naming.
- Per-acquisition summary record written incrementally (using `write_summary_atomic`) rather than batched at end of run.
- Update `engine.submit`'s `image_path` to new path.

**Commit 5 — switch `target.py`**
- Same transformation, `acquisition_type="target-acquisition"`.
- Source-tile lineage written per-record (Q4 outcome).

**Commit 5b — enumerate and migrate/preserve legacy `confirm_acquisition` callers** (gating, only if Q9 finds them)
- Grep results for callers go in this commit message.
- For each caller: migrate to new builders, or document why preserved.

**Commit 6 — driver SMART-naming removal**
- Delete from `driver/file_confirmation.py`: `_build_image_name`, `_build_xml_name`, `rename_and_move`, `predict_manifest`, `_parse_target_name`, `_RE_TARGET_IMAGE`, `next_position_index` (all SMART-naming-bound; grep confirms no callers after Commit 5b).
- Decide `confirm_acquisition`: refactor to call new builders, OR delete if no callers remain (per Q9).
- **Update `driver/__init__.py` re-exports**: remove the deleted symbols from `__all__` and import lists (lines 159, 162, 435, 440, 442 per Source 2 #7). Without this, the package fails to import after Commit 6.
- Run `python -c "import navigator_expert.driver"` as part of the commit's test suite.
- Verify no remaining importers via grep across all repos.

**Commit 7 — integration smoke test + drop old `save_acquired`**
- Remove `_acquire.py:save_acquired` (old unsafe version).
- Add integration test against `test/mock_lasx_api.py`: run preflight → overview → target → summary. Assert file tree matches schema, `parse_image_name` round-trips, `summary.json` is well-formed, lineage records reconstructable.
- Add crash-recovery test: kill workflow mid-acquisition, assert `summary.json` is still parseable (atomic write held), already-acquired files retain their per-image lineage.

## Validation reuse — exact functions to import

From `navigator_expert.driver` (re-exports, vendor-neutral or vendor-specific-but-portable):

- `wait_all_stable(files, timeout=, poll_interval=, stable_readings=)` — file stability gate. `driver/file_confirmation.py:486`.
- `check_ome_tiff(path)` — OME-XML check inside TIFF. `driver/ome_tiff.py:179`.
- `check_ome_xml_file(path)` — same for companion. `driver/ome_tiff.py:211`.
- `fix_ome_tiff(path)` / `fix_ome_xml_file(path)` — schema fix-up.
- `detect_new_files(client, baseline, media_path, acquire_start=...)` — finds image + XML for just-finished acquisition. `driver/file_confirmation.py:340`.
- `read_relative_path(client)` — for the baseline string. `driver/file_confirmation.py:204`.

**Deleted in Commit 6, do not import:** `_build_image_name`, `_build_xml_name`, `rename_and_move`, `predict_manifest` (old SMART naming).

## summary.json compatibility

Confirmed by grep: no in-repo Python code reads `tif_path` from summary.json. Hard cut, no transitional `legacy_tif_path` field needed.

What changes:
- `tif_path` strings get longer and structured (~100 chars relative).
- Dir name `ctx.out_dir.name` becomes `[experiment]_[hash6]` instead of `[ts]`. Code parsing it as a strict timestamp would break — grep finds no such consumers.

## Tests

Location: `controller/output_layout/test/` for the vendor-neutral module; `controller/vendor/leica/navigator_expert/test/` for v3-side tests (matches existing pattern).

1. **`test_naming.py`** — pure path-builder, no I/O. Round-trip parse/build, base36 encode/decode, padding correctness, reject non-kebab-case `acquisition_type`, reject experiment > 40 chars, reject acquisition_type > 25 chars, reject adversarial `acquisition_type` containing underscores (Source 2 #12).

2. **`test_layout.py`** — `LayoutPlan` helpers, hash determinism for fixed start_time, path-length sentinel against documented worst case, atomic `mkdir(exist_ok=False)` collision-bump loop (simulate parallel-process collision via thread or subprocess).

3. **`test_summary_schema.py`** — `summary.json` schema serialization, `write_summary_atomic` correctness under simulated crash (kill mid-write, assert file is either old version or new version, never partial).

4. **`test_save_acquired_validated.py`** — mocked driver. All-good, stability-fails, OME corrupted+fix succeeds, OME corrupted+fix fails, fallback to numpy.
   **Atomic-unit contract tests (the safety-critical claim Source 2 #13 flagged):**
   - `XML expected but missing → raises with clear message`
   - `XML corrupt (fails schema check) → raises`
   - `Image copy succeeds, XML copy fails → both rolled back (image removed)`
   - `XML copy succeeds, image copy fails → XML removed`
   - `Per-image lineage sidecar (.lineage.json) atomic with image+XML if Q4(d) chosen`

5. **Integration smoke** (Commit 7) — `preflight` → `overview` → `target` → `summary` against `mock_lasx_api.py`. Assert file tree shape, `parse_image_name` round-trips on every file, `summary.json` is well-formed, lineage records reconstructable from filename + sidecar (no `summary.json` needed for reconstruction).

6. **Crash recovery** (Commit 7) — simulate process kill at three points: (a) after preflight before any acquisition; (b) mid-acquisition (image saved, summary update in-flight); (c) after acquisition before summary flush. Assert in each case: run dir is in a parseable state, no half-written files, lineage reconstructable from what exists.

## Risks and uncertainties

1. **Slot mapping (Q4) is a workflow-level decision.** If the v3 mapping turns out to be wrong, only `_overview_tile_seq` / `_target_pick_seq` in v3 needs to change — the convention itself is stable.

2. **OME companion XML location varies.** `acquire_frame` returns only image path; XML is at `<source_dir>/metadata/<name>.ome.xml` with the same `--L--J--E--T--` segments. Where it's at depends on LAS X export config. Mitigation: try standard location first, fall back to `detect_new_files`, log + skip XML validation if not found.

3. **`detect_new_files` polling cost.** Up to `path_poll_timeout=5s` per acquisition. At 100 tiles, 8 minutes overhead. Mitigation: a slim helper `_find_companion_xml(image_path) -> Path | None` that just looks in `<source_dir>/metadata/` given the source TIFF path — no LAS X API polling required. Use this instead of `detect_new_files` since `acquire_frame` already gives us the image path.

4. **Operator's `output_root` hardcoded path needs updating.** Notebook config cell currently has `...\output\target_acquisition`. Preflight should validate and bail with a useful error if the path is too deep.

5. **Concurrent runs colliding (TOCTOU-safe fix).** Hash is derived from `start_time` at 1-second resolution. Two runs starting in the same UTC second collide. **Mitigation (chosen):** use atomic `Path.mkdir(exist_ok=False)` inside a retry loop — `FileExistsError` triggers a 1-second bump and retry, up to a safety cap (60 attempts). This is **TOCTOU-safe** because the OS-level `mkdir` is atomic (per-filesystem semantics on NTFS; verify behavior on the Z:\ SMB share). Pseudocode:
   ```python
   for offset in range(60):
       try:
           candidate = output_root / f"{experiment}_{run_hash(start_time + offset)}"
           candidate.mkdir(parents=False, exist_ok=False)
           return LayoutPlan(output_root, experiment, run_hash(start_time + offset))
       except FileExistsError:
           continue
   raise RuntimeError("60 consecutive 1-second slots already taken — clock/disk pathology")
   ```
   Hash semantics drift from "literal start time" under collision. Document explicitly: **hash is an opaque-ID derived from preferred-start-time, with disambiguation bumps; operators must use `summary.json:acquired_at_utc` for true wall-clock**.

6. **The driver's `fix_ome_tiff` rewrites source in place.** Default `fix_ome=False` (Q6) avoids this; opt in only when known-bad export is being repaired.

7. **`ctx.out_dir.name` no longer parses as a timestamp.** Code doing `datetime.strptime(ctx.out_dir.name, "%Y%m%d_%H%M%S")` would break. Grep finds no such consumers.

8. **Clock non-monotonicity (Source 2 #9).** `time.time()` on Windows can step backward — NTP adjustments, manual clock changes, VM resume from snapshot. If preflight calls `time.time()` at run start and again later, second call may be earlier. The lexicographic-sort = chronological-sort invariant breaks if two consecutive runs see the clock step. **Mitigation:** call `time.time()` exactly once at the top of preflight, persist to `Context.start_time_utc`, use that value everywhere downstream. Never call `time.time()` for hash purposes mid-run.

9. **Network share latency in acquisition hot loop (Source 2 #11).** `shutil.copy2` from local LAS X path to `Z:\smart-data\` synchronously copies each acquisition over SMB. For high-rate time-lapse (1 fps × 100 MB frames = 100 MB/s sustained), network bandwidth becomes the acquisition-rate ceiling. **Mitigations to consider:** (a) write locally to `C:\ProgramData\MinicondaZMB\home\t.de\smart-data\` then async-rsync to Z:\ at end of run; (b) measure copy latency at chosen root in preflight and warn if > acquisition cycle time; (c) accept the limit and document it. Default recommendation: (b) — measure and warn, don't silently stall.

10. **Source-tile lineage loss (Source 2 #3).** If lineage lives only in `summary.json`, a corrupt or non-atomically-written summary destroys reconstruction of "which overview tile produced this pick." **Mitigation:** Q4(d) — per-image `.lineage.json` sidecar, written atomically with the image+XML. The atomic unit becomes 3 files (image, XML, lineage), all-or-nothing. Reconstruction is possible from any single image's sidecar without consulting `summary.json`.

11. **`pick_sequence` instability (Source 2 #3).** Analysis non-determinism reorders the same physical cell's `p` value across re-runs. Mitigation per Q4: (b) make cellpose deterministic (CPU + fixed seed + sorted detections) AND (d) write per-image lineage sidecar so cross-run identity falls back on `(source_tile, label_within_tile)` rather than `p`.

12. **Image+XML companion atomic-unit contract is the spec's safety-critical claim, untested in the original test plan.** Source 2 #13: the spec says "fail loudly if XML is missing when expected" but no test exercises that path. Mitigation: Tests #4 above explicitly covers each atomic-unit failure mode.

13. **Schema version not in `summary.json`.** Future schema changes (e.g. adding `r` slot per Q8) need a way to be detected by consumers. Mitigation: `summary.json` carries `schema_version: 1` from Commit 1; bumped on any breaking change. Parsers can refuse unknown versions loudly.

## Critical files for implementation

- `controller/output_layout/` (new) — vendor-neutral convention module
- `controller/vendor/leica/navigator_expert/notebooks/workflow/_acquire.py` — current `save_acquired` to replace
- `controller/vendor/leica/navigator_expert/notebooks/workflow/_save.py` (new) — validated save
- `controller/vendor/leica/navigator_expert/notebooks/workflow/overview.py:126-129` — call site
- `controller/vendor/leica/navigator_expert/notebooks/workflow/target.py:138-142` — call site
- `controller/vendor/leica/navigator_expert/notebooks/workflow/preflight.py:115-134` — out_dir construction
- `controller/vendor/leica/navigator_expert/notebooks/workflow/context.py` — Config + Context fields
- `controller/vendor/leica/navigator_expert/notebooks/workflow/summary.py:47, 111-112, 295-310` — `summary.json` writer; line 111-112 is the **non-atomic write** that Risk 10/12 fixes
- `controller/vendor/leica/navigator_expert/driver/file_confirmation.py` — remove old SMART naming functions in Commit 6. Specific line refs from Source 2 review:
  - Lines 124-145: `_build_image_name`, `_build_xml_name` (delete)
  - Lines 165, 177-197: `_RE_TARGET_IMAGE`, `next_position_index` (delete — dead code post-migration)
  - Line 282: `parse_lasx_filename` (keep — vendor-specific source parser, still needed)
  - Line 340: `detect_new_files` (keep)
  - Line 486: `wait_all_stable` (keep)
  - Line 929: `confirm_acquisition` (refactor or delete per Q9)
- `controller/vendor/leica/navigator_expert/driver/__init__.py:159, 162, 435, 440, 442` — re-exports of soon-to-be-deleted symbols; Commit 6 must remove these or import fails
- `controller/vendor/leica/navigator_expert/driver/notebook_workflow.py:357` — legacy caller of `confirm_acquisition`; Q9 must resolve this before Commit 6
- `smart-analysis/workflows/target_acquisition/steps/segment_tile.py:80-81` — only external consumer of acquisition image files (per Source 2 grep); reads opaquely via `tifffile.imread`, no parsing — migration safe, no action needed
