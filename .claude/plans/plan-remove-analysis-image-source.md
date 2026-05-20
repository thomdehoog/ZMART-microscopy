# Plan: remove `analysis_image_source` end-to-end (one mock mechanism)

**Status**: drafted, pending review and precondition resolution.
**Author**: claude (continuation of Plan 2 / D1 cleanup).
**Predecessor commits**: `ef4d2a2`, `e827219`, `c419b02` (Plan 2 phase 1 +
robustness follow-up, shipped on `try/all-four`).
**Cross-repo**: touches `smart-microscopy` and `smart-analysis`.

---

## Design intent

Plan 2 shipped a new dry-run mechanism (hijack: `cfg.simulate=True` swaps
the saved `.ome.tiff`'s pixel content with mock content under the LAS X
simulator's real OME envelope). The pre-Plan-2 dry-run mechanism
(`cfg.analysis_image_source="skimage_human_mitosis"` → engine ignores the
file path and loads a hardcoded skimage image) is still wired through
the codebase, even though Plan 2's submit-dict override
(`"acquired" if cfg.simulate else cfg.analysis_image_source`) makes the
old mechanism operationally unreachable from the current notebook.

The current state — two coexisting dry-run mechanisms, one canonical and
one vestigial — is the "two ways to do the same thing" anti-pattern. The
codebase reads as if both are supported; only one is.

**End state**:

- Single operator-facing dry-run knob: `cfg.simulate` (+ `cfg.mock_image_source`).
- Single engine code path: `tifffile.imread(image_path)`. No branch on
  source. The engine's response schema also drops `image_source` —
  the concept is gone from both the input *and* the output of the
  engine, not just the input branch.
- Single mock concept: hijack the file. New mock variants are new
  providers (a parameter to one mechanism), not parallel code paths.
- `analysis_image_source` does not exist as a concept anywhere in the
  active codebase — not in Config, not in the submit dict, not in the
  NPZ writer, not in TileEvent, not in visualize's `is_mock`, not in
  the v3.1 notebook, not in any active-path test, not in any
  active-path doc file.
- The **only** traces of the old concept after the cut are:
  1. A load-boundary back-compat read in `_load_tile_npz`: a
     pre-Plan-2 NPZ on disk that carries `analysis_image_source` but
     no `simulated` key still rebuilds `is_mock` correctly. Reading
     old artifacts at the load boundary is not bloat; it is the
     legitimate seam for forward-compatible code.
  2. The back-compat *test fixture* in `test_overview_persistence.py`
     that pins (1).
  3. History — commit messages, prior plans under `.claude/plans/`.
     History is history; the plan does not rewrite or scrub it.

This pattern — *contract changes happen everywhere at once; back-compat
lives at the load boundary, not in the active code path* — is the
maintainability precedent we want this commit to set.

## Precondition (blocker on user action)

The `smart-analysis` worktree on branch `v4-engine` has uncommitted
changes in `workflows/target_acquisition/steps/pick_targets.py` and
`segment_tile.py`. D1 (engine cleanup) cannot land from this state —
Plan 2 §3's worktree-hygiene rule. If D1's diff is anything other
than "remove the mock branch + remove its fixtures + remove its
tests," we re-introduce the patchwork pattern this plan exists to
delete.

**Implementer's audit of the dirty diffs** (read against HEAD):

- `pick_targets.py` (+11 / -5): adds an `n_picks=None` code path
  that "returns all cells sorted by label" for downstream sampling,
  plus a `SUPPORTS_NONE_NPICKS = True` capability flag. Docstring
  updated to reflect the `n_picks: int | None` signature. Looks
  feature-complete and orthogonal to D1 — does **not** touch
  `analysis_image_source`. Proposed disposition: commit as its own
  feature commit (`pick_targets: support n_picks=None for
  downstream sampling`) before D1.
- `segment_tile.py` (+1 / -1): single-line environment swap from
  `SMART--target_acquisition--main` to `dino3_test`. Local dev
  override or intentional environment change — operator should
  confirm. Proposed disposition: operator chooses one of
  (a) commit standalone if `dino3_test` is the intended env on
  this machine; (b) discard if `SMART--target_acquisition--main`
  is canonical; (c) commit with a "WIP: env override" message on
  a side branch if it's exploratory.

Neither dirty change is entangled with the mock branch D1 deletes,
so D1's diff stays clean either way. **The implementer does not
decide disposition on changes they did not make** — operator
confirms each, the implementer executes.

## Audit step (before either commit)

**(a) Engine internal shape (completed).**
Read of `smart-analysis/workflows/target_acquisition/steps/segment_tile.py`:
the mock branch is a clean `if/else` in `_load_image(source, inp)` at
lines 79-89. Confirmed: no parameter chain, no dataclass field, no
fixture-loading code path.

**(b) Engine surface beyond the branch (completed — flagged by rev2).**
`segment_tile.py` carries `analysis_image_source` / `image_source`
beyond the immediate branch decision in four places that must also
go in Commit A:
- Line 3-12: docstring `Inputs` describing
  `pipeline_data["input"]["analysis_image_source"]`.
- Line 31-32: docstring `Outputs` describing the
  `image_source` return key.
- Line 48: `source = inp.get("analysis_image_source", "acquired")`.
- Line 64: `print(f"  [segment_tile] source={source}, ...")`.
- Line 71: `"image_source": source` in the returned dict.

`_load_image` helper (lines 76-89) goes entirely; the call site
becomes `image = tifffile.imread(inp["image_path"])`.

**(c) Engine public-surface API contract.**
The workflow ↔ engine contract is a plain `dict` (`pipeline_data`),
not a dataclass / TypedDict / schema with a generated stub. After
Commit A, `grep -r "analysis_image_source\|image_source"` in
`smart-analysis` returns matches only in history (commit messages,
prior docs) and in the test fixture(s) about to be migrated. Verify
after Commit A's diff is drafted, before commit.

**(d) Non-notebook consumers in smart-microscopy (completed).**
`grep -r analysis_image_source` in smart-microscopy returns 14
matches across 14 files. After excluding the two history files
(`.claude/plans/plan-remove-analysis-image-source.md`,
`.claude/plans/notebook-restructure.md`) and the operator's
dirty `smart_microscopy_v3.ipynb` (off-limits), the 11 active-code
files are all enumerated in §"Commit B" below. **One non-notebook
consumer that needs explicit treatment**:
`controller/.../notebooks/smoke_visualization.py:82` — sets
`analysis_image_source` directly outside a `Config(...)`
construction. Migration target: rewrite to use
`simulate=True, mock_image_source="skimage_human_mitosis"` if the
script's purpose was exercising the mock path; or delete if Plan 2
phase 1 already supersedes its purpose. Operator should confirm
intent before the migration shape is locked.

If any audit finding changes the plan's structure (vs. its file
list), revise the plan before any code changes. The revision is
part of this plan, not a separate ad-hoc decision.

## Commit A — `smart-analysis`: delete engine mock branch (D1)

**Why this can land first**: after Plan 2 phase 1, the workflow already
sends `analysis_image_source="acquired"` in both notebook modes
(`simulate=True` overrides; `simulate=False` uses Config's `"acquired"`
default). The engine's mock branch is operationally unreachable from
the notebook today. Landing D1 first keeps Commit B's diff free of
engine concerns.

**File changes**:

- `workflows/target_acquisition/steps/segment_tile.py`:
  - Docstring `Inputs` block: drop the
    `pipeline_data["input"]["analysis_image_source"]` line and the
    "acquired or mock" framing in the module summary (lines 1-6,
    11-12).
  - Docstring `Outputs` block: drop the `image_source` entry
    (lines 31-32).
  - Body: drop `source = inp.get("analysis_image_source", "acquired")`
    (line 48).
  - Body: replace `image = _load_image(source, inp)` (line 50) with
    `image = tifffile.imread(inp["image_path"])`. (Or call
    `tifffile.imread` inline if no helper survives.)
  - Log line (line 64): drop `source=...` from the format string.
  - Returned dict (line 71): drop `"image_source": source`.
  - Helper `_load_image` (lines 76-89): delete entirely — no
    longer called. The `import tifffile` moves to the file head.
- `workflows/target_acquisition/tests/test_target_acquisition.py`:
  - Fixture around line 62 — drop the `analysis_image_source` key
    from any submission payload that constructs one.
  - Test around line 410 — **rev2's call**: this test currently
    exercises the real cellpose + human_mitosis path via the
    `analysis_image_source="skimage_human_mitosis"` branch. Don't
    delete it — convert it so the test writes `human_mitosis()` to
    a temp `.ome.tiff` and passes `image_path` pointing at it.
    Preserves the useful end-to-end cellpose-on-real-image
    coverage while removing the old mechanism. Document the
    intent in a comment so a future contributor understands why
    the temp-file dance exists.
  - Any other test asserting on the `image_source` return key —
    drop the assertion.

**Commit message tag**:
`feat(engine): D1 — remove analysis_image_source mock branch`

**Verification**: `smart-analysis` test suite green.

## Commit B — `smart-microscopy`: end-to-end deletion of the concept

**File changes**:

- `workflow/context.py` — drop
  `analysis_image_source: str = "acquired"` from `Config`.
- `workflow/overview.py`:
  - Submit dict: drop the `"analysis_image_source"` key entirely.
    Engine no longer reads it.
  - `_save_single_tile_analysis` `save_kwargs`: drop the
    `"analysis_image_source"` NPZ key. New NPZs do not carry it.
  - `_fire_on_tile`: drop `analysis_image_source` from the
    `TileEvent(...)` construction.
  - `TileEvent` dataclass: drop the `analysis_image_source` field.
- `workflow/visualize.py`:
  - `display_tile` (around line 452):
    `is_mock = event.simulated`. No second clause; the legacy
    `event.analysis_image_source != "acquired"` is gone.
  - `TileNpz` NamedTuple: drop the `source` field.
  - `display_selection` loop (around line 1368): drop `source` from
    the tuple unpacking; `is_mock = simulated`.
  - **`_load_tile_npz` — the single back-compat seam**:
    ```python
    if "simulated" in data.files:
        simulated = bool(data["simulated"])
    elif "analysis_image_source" in data.files:
        # Pre-Plan-2 NPZ: derive simulated from the dropped field.
        # This is the ONLY remaining reference to analysis_image_source
        # in the active codebase; do not extend it elsewhere.
        simulated = str(data["analysis_image_source"]) != "acquired"
    else:
        simulated = False
    ```
- `controller/.../notebooks/smoke_visualization.py` (line 82) —
  rewrite to use `simulate=True, mock_image_source="skimage_human_mitosis"`
  if the script's purpose was exercising the engine-side mock branch;
  or delete if Plan 2 phase 1 already covers its scope. **Operator
  intent required** — see Audit step (d).
- `controller/.../notebooks/docs/OPEN_QUESTIONS.md` (line 62) —
  update the prose to reflect the new single-mechanism model
  (`simulate` + `mock_image_source`), or remove the stale reference.
  Quick sweep of `controller/.../docs/*.md` for any other matches
  the focused grep didn't surface; treat all the same way.
- `smart_microscopy_v3.1.ipynb`:
  - Config cell: drop the `analysis_image_source=...` line and its
    comment block.
  - Markdown intro: drop the `analysis_image_source` table row.
- Tests (all enumerated explicitly, per rev1):
  - `workflow/test/test_visualize.py::test_mock_mode_title_contains_mock`
    — switch the assertion driver from `analysis_image_source` to
    `simulated=True`.
  - `workflow/test/test_save_tile_analysis.py` — drop any
    `analysis_image_source` references from fixtures / payloads.
  - `workflow/test/test_summary_schema.py` — drop any
    `analysis_image_source` references from fixtures / payloads /
    asserted serialized dicts.
  - `workflow/test/test_selection.py` — drop any
    `analysis_image_source` references from fixtures / payloads.
  - **New test** in `workflow/test/test_overview_persistence.py`
    (alongside the existing NPZ persistence tests, which is the right
    owner): `_load_tile_npz` derives `simulated=True` from a
    synthetic pre-Plan-2 NPZ that carries
    `analysis_image_source="skimage_human_mitosis"` but no
    `simulated` key. Pins the back-compat seam against future
    deletion.
  - **New "single-trace" structural test** (also in
    `test_overview_persistence.py`, alongside the back-compat test):
    walks the `controller/vendor/leica/navigator_expert/notebooks/`
    source tree (workflow/ + smoke scripts + notebook .py modules)
    and asserts the string `analysis_image_source` appears only in
    the two allowed sites — `_load_tile_npz` and the back-compat
    test itself. Allowlist by file path; fail-loud on any new
    match. Catches accidental re-introduction in future PRs cleanly.
    rev1's framing: structural enforcement, not a magic-constant
    obfuscation. Notebook `.ipynb` files are skipped (their JSON
    structure would produce noisy matches; the v3.1 cleanup is
    pinned by the operator's manual verification, and v3.ipynb is
    explicitly off-limits).

**Commit message tag**:
`refactor(workflow): remove analysis_image_source — one mock mechanism (the hijack)`

**Verification**: `smart-microscopy` test suite green. Currently 208
passing; expected 209 after the new back-compat test.

## What's not in this plan (intentional)

- **No transitional code, no "hardcode acquired for now" intermediate.**
  The two commits are the migration.
- **No deprecation warnings.** The concept is gone, not deprecated.
  There are no external consumers to warn.
- **No migration script for old NPZs on disk.** They're read at the
  load boundary; their format does not need to change.
- **No touching `smart_microscopy_v3.ipynb`** (the operator's dirty
  working copy).
- **No touching the dirty `smart-analysis` files** beyond the audit
  read and the operator-confirmed disposition; D1's own changes to
  those files happen *after* the dirty diffs are resolved (commit /
  stash / discard), not on top of them.
- **No rewriting history.** Past commit messages, prior plans in
  `.claude/plans/`, the predecessor `notebook-restructure.md` — all
  retain references to `analysis_image_source` as a matter of
  historical record. The single-trace structural test allowlists
  the `.claude/plans/` directory; commit messages aren't searched.

## Order of operations

1. User resolves the dirty `smart-analysis` worktree (or hands the
   diffs over for a proposal).
2. Implementer does the audit step. Anything surprising → stop, surface,
   revise plan before any code changes.
3. Commit A on `smart-analysis`. Run engine tests.
4. Commit B on `smart-microscopy`. Run workflow tests
   (208 → 209 with the new back-compat test).
5. Cross-repo smoke: run v3.1 notebook against the simulator in
   `simulate=False` (real-data path sanity) and `simulate=True`
   (hijack-end-to-end path with the new file-read-only engine).
6. Optional: load a pre-Plan-2 NPZ from a past run through
   `_load_tile_npz` and confirm `is_mock` rebuilds correctly.

If anything is red at any step: stop, surface, decide. Do not paper
over a failure to ship the rest of the plan.

## Risks

- **Engine has a public-surface `analysis_image_source` argument**
  (something the workflow imports and calls by name with the kwarg).
  Deleting it between Commits A and B is signature-breaking. The audit
  step must check this; if found, revise plan so the kwarg removal
  happens atomically with the call-site removal.
- **The mock branch is wider than the audit reveals.** If
  `analysis_image_source` is threaded through engine fixtures or test
  scaffolding in ways the audit misses, Commit A's diff balloons. Stop
  and revise rather than expanding the commit in-flight.
- **The dirty `smart-analysis` changes touch the mock branch directly.**
  Unwinding them in-flight is exactly the kind of patchwork this plan
  rejects. The disposition decision must happen *before* Commit A
  starts.
- **NPZ back-compat seam gets deleted later by a contributor who
  doesn't read the comment.** Mitigation: the new back-compat test
  pins it structurally; the comment names it as the ONLY remaining
  reference.

## Reference: what stays after the cut

After Commits A and B, `grep -r analysis_image_source` across both
repos should return:

- One match in `_load_tile_npz` (the back-compat read).
- A small bounded number of matches in the new back-compat test
  (asserting the read works) plus the new "single-trace" structural
  test (the allowlist that names them).
- Matches in `.claude/plans/`, prior commit messages, and any other
  historical artifact. **History is history; the plan does not
  rewrite or scrub it.**

Anything else — `workflow/`, `notebooks/` (excluding history),
non-test source — is residue and means the plan was executed
incompletely. The new "single-trace" structural test enforces this
automatically.
