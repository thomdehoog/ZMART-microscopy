# Review: Leica Stellaris5 driver — `scanfields/`, `experimental/lrp_edits/`, `acquisition/`, `_file_utils.py` (+ their unit tests)

- **Scope**: `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` — subpackages `scanfields/` (parsers.py, planning.py, strip_restore.py, lrp.py, files.py, transaction.py, _convert.py, `__init__.py`), `experimental/lrp_edits/` (roi.py, scan.py, z.py, focus.py, general.py, _primitives.py), `acquisition/` (ome_canonical.py, navigator_expert_export.py, ome.py, lasx_native_autosave.py, save.py, capture.py, materialize.py, product.py, files.py), `_file_utils.py`, and the unit tests pinning these modules (`tests/unit/test_scanfield_parsers.py`, `test_scanfield_strip_restore.py`, `test_lrp_edit_primitives.py`, `test_acquisition.py`, `test_native_autosave.py`; fixtures under `tests/data/`). Base `__init__.py`, `utils.py`, and `commands/commands.py` entry points skimmed for wiring context only.
- **Date**: 2026-07-03
- **Reviewed commit**: `c7964dd` (working tree == origin/main)
- **Review 3 of 4** for this driver; commands/connection/readers were review 2; calibration/config/motion/zmart_adapter are review 4.
- Verification: all in-scope unit tests were run (`132 passed, 1 skipped in 67.98s`; the skip is an optional `ome_types` validation test). One test alone accounts for 60 of those 68 seconds (LS-31).

All paths below are relative to `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` unless prefixed with `tests/`.

---

## Executive summary

This slice of the driver solves three genuinely hard problems — parsing the undocumented LAS X `.lrp`/`.rgn`/XML template triple, doing transactional file edits against a live instrument that holds exclusive locks and rewrites files behind your back, and producing schema-valid canonical OME output from two very different vendor export shapes — and it mostly solves them well. The strongest work is in `acquisition/`: the exporter→`ExportedAcquisition`→`save` seam is a clean, writer-agnostic contract with fail-closed collection (refuses ambiguous candidates, validates XML-declared grids, catches missing whole channels), honest metadata authority (vendor OME is provenance; live job geometry is truth, with a loud warning when it can't be read), and atomic materialization with correct tmp-file hygiene. The transactional core (`transaction.py`, `strip_restore.py`, `_primitives.py`) is honest about its limits (documented no-rollback), preserves the vendor prolog deliberately, and carries regression tests for previously-found corruption bugs.

The criticisms fall into three groups. First, **test gaps exactly where the risk is highest**: the 380-line `parse_lrp` job-settings parser has zero tests, and the binary TIFF patcher in `ome.py` — raw `struct` surgery with three relocation branches — is never exercised by any test (it is only ever mocked). Second, **the `experimental/` package is a misnomer hiding both load-bearing code and dead code**: `commands.move_galvo_to_pixel` depends on it in production, ~60 names are re-exported from the driver facade, yet `pixels_to_roi`/`center_vertices` have no callers at all and half a dozen exported helpers (`make_line`, `make_ellipse`, `roi_to_pan_zoom`, `mask_contour_to_roi`, `disable_roi_scan`, `reset_pan`) are called by nothing in the repo. Per the maintainer's own rule — promote it or delete it — both actions are overdue. Third, **drift between parallel implementations of the same concern**: the two export collectors disagree on backslash normalization, the ROI editors destroy the LRP prolog that `reorder_jobs` painstakingly preserves, two geometry→tiles planners coexist with different tile orderings, and a comment promises a 120 s completion budget while the constant says 60.

No Critical findings. 3 High, 14 Medium, 19 Low.

---

## What works well

1. **The exporter/save seam is a real contract, not a convention** — `product.py:1-6` states it ("`Exported*` types are exporter → save inputs and are writer-agnostic"), `save.py:55-58` dispatches through a flat `_EXPORTERS` table, and both collectors produce the identical `ExportedAcquisition` shape (`navigator_expert_export.py:334-383`, `lasx_native_autosave.py:96-106`). Adding the native-AutoSave path did not touch persistence. `test_native_autosave.py:325-377` proves a multipage native TIFF materializes through the same `save()` as the flat export.
2. **Fail-closed collection everywhere ambiguity could silently corrupt a run** — multiple fresh native candidates refuse to guess (`lasx_native_autosave.py:188-195`); multiple source X/Y groups fail with an explanation of *why* (`navigator_expert_export.py:271-277`); duplicate repeat suffixes are a hard error while newer repeats supersede older ones with a debug trail (`navigator_expert_export.py:285-294`). All three are pinned by tests (`test_native_autosave.py:173-190`, `test_acquisition.py:1017-1048`, `860-904`).
3. **Completeness validation against the XML-declared grid, not just what showed up** — `_validate_complete_grid` (`navigator_expert_export.py:422-445`) uses declared SizeC/SizeZ when available so a missing *whole channel* is caught (observed-only inference cannot see it); `test_acquisition.py:941-978` pins exactly that case, and `906-939` pins the partial-grid case.
4. **Honest metadata authority with a loud fallback** — `ome_canonical.metadata_with_job_physical_sizes` (`ome_canonical.py:110-134`) documents the observed vendor bug (native AutoSave writes PhysicalSizeZ as range/sections), prefers live job geometry, and when the bounded read times out it *says so out loud* instead of silently keeping known-wrong values (`ome_canonical.py:126-134`). The timeout fallback is tested with a real slow reader (`test_acquisition.py:293-321`).
5. **Atomic materialization done right** — unique tmp suffix with a comment explaining why a fixed `.tmp` is unsafe (`materialize.py:131-134`), cleanup on `BaseException`, `os.replace` last (`materialize.py:15-64`); the failure path is tested with a simulated mid-write disk-full (`test_acquisition.py:1103-1128`). `save.py:167-170` batches summary I/O with the O(n²) rationale written down, and the `finally` still persists records for planes materialized before a mid-save failure.
6. **`reorder_jobs` preserves what ElementTree cannot represent** — the vendor prolog (XML declaration + Leica header comments) is spliced back verbatim with the reasoning documented (`transaction.py:83-89`), comments inside the document survive via `insert_comments=True` (`transaction.py:45`), and UTF-8 is forced so non-ASCII job names can't be corrupted by locale encoding. All of it pinned: `test_lrp_edit_primitives.py:117-131`.
7. **The text-edit primitives carry their own regression history** — the whitespace lookbehind that stops `Zoom` matching inside `BaseZoom` is commented at the fix site (`_primitives.py:55-57`) and pinned both ways (sibling before and after) in `test_lrp_edit_primitives.py:55-75`; `_verify_job_attr` explicitly rejects the vacuous pass ("absent means the edit silently did nothing", `_primitives.py:104-116`), also pinned (`test_lrp_edit_primitives.py:77-90`).
8. **`apply_lrp_change` is honest about being non-transactional** — "There is no rollback: a failure after the edit leaves the on-disk LRP modified…" (`transaction.py:126-129`), and a falsy `edit_result` is surfaced instead of laundered into success (`transaction.py:150-155`).
9. **Recovery-minded strip/restore** — `restore_template` deletes stale `.lrp.bak` from crashed prior runs before starting (`strip_restore.py:289-295`), and on final failure *keeps* the backups with a log message naming them for manual recovery (`strip_restore.py:353-365`). `find_scanning_templates_dir` refuses to guess between multiple LAS X user profiles rather than alphabetically editing someone else's templates (`files.py:63-70`). `save_and_read_lrp` refuses to hand back a stale parse after a failed save, with the reason in a comment (`files.py:285-288`).
10. **Ground-truth fixture pairs for the planner** — `tests/unit/test_scanfield_parsers.py:774-808` parses the *same* RGN geometry in its unassociated form and compares tile centres against the LAS X-materialized associated form (real template bundles in `tests/data/scanfield_parsing/`), and `test_scanfield_parsers.py:334-446` proves the grid-spec and materialized representations coincide. This pins behavior against the instrument, not against the implementation.
11. **The mtime-skew allowance is a documented, bounded risk** — `acquisition/files.py:87-93` states the SMB clock-drift problem, the allowance, the residual risk, and what bounds it. This is the standard every magic constant in the package should meet.
12. **Native TIFF plane mapping is cross-validated three ways** before any pixel is trusted: series axes vs OME-declared SizeT/Z/C, page counts vs expected, per-axis shape asserts (`lasx_native_autosave.py:252-301`, `370-421`), with a fail-closed test for junk axes (`test_native_autosave.py:245-254`).
13. **Tombstone test for the removed legacy API** — `test_acquisition.py:1163-1173` asserts the old workflow helpers are *gone* from the facade, preventing silent resurrection.

---

## Findings

### scanfields/ — parsers, planning, files, strip/restore, transaction

**LS-01 — High — `scanfields/lrp.py:309-380` — `parse_lrp` has zero unit tests.**
The 380-line LRP parser is the single reader for the job/hardware-settings tree and is load-bearing for verification (`experimental/lrp_edits/roi.py:646,675` — `lrp_verify_roi_count`/`lrp_verify_roi` gate `apply_lrp_change` success) and for `save_and_read_lrp` (`scanfields/files.py:290`). No test in the suite imports or exercises it, not even against the real `.lrp` fixtures already sitting in `tests/data/scanfield_parsing/` (five bundles) and `tests/data/general_workflow/`. A regression here (e.g. the `BlockType` filter at `lrp.py:354-356`, or the `_`-prefix convention) would break ROI verification silently.
**Action**: add a fixture-driven test parsing at least one real `.lrp`, asserting job names, the Master/Sequential/AutoFocus split, `_Detectors`/`_Lasers`/`_ROIs` presence, and the duplicate-job-name warning path (`lrp.py:358-359`).

**LS-02 — Medium — `scanfields/parsers.py:345-441` — `_derive_positions_from_geometry_grid` applies the single global MatrixData count to *every* Rectangle geometry.**
`n_cols`/`n_rows` come once from `MatrixData/CountOfData` (parsers.py:360-364) but the loop stamps that same grid onto each Rectangle in the RGN (parsers.py:368-439), synthesizing `section_y=region_index` per geometry. With two rectangles of different sizes, both get the full ScanFieldsX×Y grid — almost certainly not what LAS X meant by a global count. The only fixtures for this path have exactly one rectangle (`test_scanfield_parsers.py:187-261`), so multi-geometry behavior is unpinned and probably wrong.
**Action**: either restrict this derivation to the single-Rectangle case (fail loudly with >1) or document the LAS X semantics that justify per-geometry replication, and add a two-rectangle fixture either way.

**LS-03 — Medium — `scanfields/planning.py:152-218, 269-282` — planned regions flatten the 2-D grid and use a different scan order than every other region source.**
`_generate_from_geometries` emits tiles column-major (`ix` outer, `iy` inner, planning.py:269-275) and `_make_region` then declares `num_rows=1`, `row=0`, `col=i` (planning.py:199-205) — so a 3×5 planned region reports 1×15 and its `acquisition_order` runs down columns, while XML-materialized regions report true rows/cols sorted row-major (parsers.py:249-253) and `_derive_positions_from_geometry_grid` iterates row-major (parsers.py:392-394). Any consumer that uses `row`/`col`/`acquisition_order` for stitching or stage-motion ordering gets three different contracts depending on which template representation happened to be on disk. The equivalence tests mask this by comparing *sorted* centre sets (`test_scanfield_parsers.py:761-771`).
**Action**: emit real row/col indices and row-major order from the planner (the grid structure is known at generation time — `nx`, `ny`, `ix`, `iy` are right there), and tighten the fixture-pair test to compare ordered sequences, not sorted sets.

**LS-04 — Medium — `scanfields/planning.py:102-122` — overlap inference brute-forces 501 full tile generations over all geometries.**
`infer_overlap_pct_from_geometry_counts` regenerates tiles for *every* geometry (including ones with no expected count) at each of 501 overlap steps; each generation runs rect/ellipse/polygon intersection tests per candidate tile (planning.py:229-283). For a large region (hundreds of tiles) with polygon clipping this is hundreds of thousands of intersection tests per parse. It runs on the hot `parse_scan_positions` path whenever XML lacks job-associated tiles.
**Action**: at minimum, generate only the geometries that carry expected counts inside the search loop; better, binary-search the monotone per-axis count function instead of a linear sweep, or memoize `_grid_count` inputs. Keep the midpoint/integer-preference tie-break (it is at least documented, planning.py:112-121).

**LS-05 — Low [PATCHWORK] — `scanfields/planning.py:19, 81, 221-226`; `scanfields/parsers.py:1091` — undocumented magic tolerances and defaults.**
`_OVERLAP_TOL = 0.005`, `_grid_count(..., tol=0.05)` ("LAS X-like tolerance"), and the `5.0` default overlap (appearing independently in `planning.py:81` and `parsers.py:1091`) have no provenance: no note of which LAS X behavior was measured, on what template, when. Review 2 praised the driver's measured-constant provenance elsewhere; these constants don't meet that bar and are exactly the kind of value that silently stops matching after a LAS X update.
**Action**: one comment each stating the observed LAS X behavior and the fixture that pins it; hoist the duplicated `5.0` into a single named constant.

**LS-06 — Low [PATCHWORK] — `scanfields/parsers.py:85-113` — `_parse_size_string` mojibake patch and digit-filter parsing; `_tile_size_from_image_size_str` silently averages X and Y.**
Line 85 strips a double-encoded `Â µ` (`"Âµm"`) with no comment saying which API/locale produced it — a one-quirk workaround future readers can't validate. The value parse filters to digits and dots (parsers.py:89-90), so an exponent-format size (`"2.9e-05 m"`) would silently misparse rather than fail. And `_tile_size_from_image_size_str` (parsers.py:103-113) averages X and Y into one "tile size" — a non-square FOV yields bounding boxes that are wrong in both axes with no warning.
**Action**: comment the mojibake's origin; parse with a real regex (`[\d.eE+-]+`) that fails loudly on surprise formats; log a warning when X≠Y instead of silently averaging.

**LS-07 — Low [PATCHWORK] — `scanfields/parsers.py:470, 639, 763` — the `findtext("Name") or findtext("n")` fallback appears three times, unexplained.**
Some RGN serialization apparently writes `<n>` instead of `<Name>`; nothing says which LAS X version or path does this, and the same two-key lookup is copy-pasted into `parse_base_grid`, `parse_rgn_geometries`, and `parse_rgn_tile_colors`.
**Action**: one `_shape_name(item)` helper with a comment naming the producer of `<n>` (or delete the fallback if no fixture exhibits it — none of the five checked-in RGN fixtures use `<n>`).

**LS-08 — Low — `scanfields/files.py:167, 180-194, 222-224` — save confirmation trusts raw mtime `>` and a blanket `except Exception`.**
`save_experiment` confirms via `st_mtime > old_mtime` with no skew/granularity allowance, while the acquisition side of this same driver documents 2 s of mtime skew as a real hazard (`acquisition/files.py:87-93`); a coarse-resolution rewrite within the same tick times out as "save failed". Meanwhile the whole body sits under `except Exception → return None` (files.py:222-224), so a programming error (e.g. `AttributeError` on a changed client API) is indistinguishable from a save timeout.
**Action**: narrow the except to the client-call block (as `load_experiment` effectively risks the same, files.py:253-255); accept `>=` with a size-change or stability check, or reuse the documented skew allowance.

**LS-09 — Low — `scanfields/files.py:93-96` — `get_template_state` reports "fresh" when the environment is unknowable.**
When `%APPDATA%` is unset or the templates dir can't be found, the function returns `"fresh"` — the same answer as "the operator genuinely has no template". A misconfigured host looks like a clean state and invites a workflow to proceed. The function otherwise takes care to distinguish `"unreadable"` from `"stripped"` for exactly this reason (files.py:88-92).
**Action**: return a distinct `"unknown"`/raise when the directory cannot be located, mirroring the `"unreadable"` rationale.

**LS-10 — Low — `scanfields/strip_restore.py:40-47` — `_strip_xml` does raw-string surgery on XML.**
`text.find("<ScanFields")` would also anchor on any element whose name merely starts with `ScanFields`, and a `<ScanFields>` occurrence inside a comment or CDATA would corrupt the splice. Today the post-strip guard at strip_restore.py:127-128 catches residual `<ScanFieldData`, which limits the blast radius — but the module's own sibling `_strip_rgn` shows the safer pattern (parse, rebuild).
**Action**: match `"<ScanFields>"`/`"<ScanFields "` explicitly, or strip via ElementTree like `_strip_rgn` does.

**LS-11 — Low — `scanfields/transaction.py:105, 117-119, 156-157` — `confirm_delays` are timeouts, and `reorder_jobs` failure is ignored.**
The parameter is named `confirm_delays` while the docstring has to clarify "Per-attempt save *timeouts*" — rename it and the clarification disappears. Two lines later, `reorder_jobs`' boolean result is dropped (transaction.py:156-157): on failure the template loads with a different job selected and the transaction still reports success (reorder_jobs logs an error, but the caller's result dict carries no trace).
**Action**: rename to `confirm_timeouts`; propagate reorder failure into the result (`"reordered": bool`) or log at error level from the transaction with the job name.

**LS-12 — Low [YAGNI] — `scanfields/parsers.py:56-58`; `experimental/lrp_edits/roi.py:101` — compatibility re-export shim for an import one directory away.**
`parsers.py` re-imports `parse_lrp`/`_get_job_names` from `lrp.py` "so the (untouched) experimental lrp_edits package can keep importing it from scanfields.parsers" — but lrp_edits is in-repo, one `sed` away, and the "(untouched)" premise is stale (the package is actively maintained and tested).
**Action**: change `roi.py:101` to `from ...scanfields.lrp import parse_lrp` and delete the shim + comment.

### experimental/lrp_edits/

**LS-13 — Medium [YAGNI] — `experimental/` is a misnomer for load-bearing production code.**
`commands/commands.py:1165-1166` (the `move_galvo_to_pixel` production command) imports `galvo_pan_for_pixel`, `lrp_get_pan`, `lrp_set_pan` from it; the driver facade re-exports ~60 of its names (`__init__.py:430-525`); the README itself instructs readers to treat it as "offline template editor, not unstable" (`README.md:290-292`). Under the maintainer's stated rule — load-bearing experimental code gets promoted — the name now only misleads: it signals "may break, don't depend" to exactly the readers who must depend on it, and it licenses the dead code documented in LS-14/LS-15 to accumulate.
**Action**: rename `experimental/lrp_edits/` → `lrp_edits/` (a mechanical move; `connection/session.py:91` and `scanfields/parsers.py:56` comments reference it and would be updated in the same pass), and delete the now-empty `experimental/` package.

**LS-14 — Medium [YAGNI] — `experimental/lrp_edits/roi.py:432-501` — `pixels_to_roi` and `center_vertices` are dead.**
Neither function has a single caller anywhere in the repo, neither is re-exported from any `__init__`, and neither appears in the README. `center_vertices` exists only to serve `pixels_to_roi`; `mask_contour_to_roi` (roi.py:901-940) independently reimplements the same pixel→centred-vertices+translation math and *is* exported. Two implementations of the coordinate contract is one more than can stay correct.
**Action**: delete both (70 lines), or if the `skimage.find_contours` row/col convention support is genuinely wanted, fold it into `mask_contour_to_roi` as a parameter.

**LS-15 — Medium [YAGNI] — seven exported lrp_edits helpers have zero callers.**
`make_line` (roi.py:412), `make_ellipse` (roi.py:331), `make_polygon` (roi.py:355), `roi_to_pan_zoom` (roi.py:868), `mask_contour_to_roi` (roi.py:901), `disable_roi_scan` (roi.py:169), and `reset_pan` (scan.py:304) are re-exported by the facade and marketed in the README, but nothing in `zmart_drivers/`, `workflows/`, `shared/`, or any notebook/doc calls them. The README's load-bearing justification ("used by `move_galvo_to_pixel`, `disable_roi_scan`, `reset_pan`", README.md:290-291) is partly circular: `disable_roi_scan` and `reset_pan` are themselves the uncalled functions. `make_polygon` in particular is a `list()` call whose docstring claims validation it does not perform (roi.py:355-366).
**Action**: delete the uncalled helpers (each is a two-minute re-add if a cookbook needs one), or move the ones that exist for interactive/cookbook use into a documented cookbook module so the driver facade stops advertising an API with no consumers. At minimum delete `make_polygon` or make it validate.

**LS-16 — Medium — `experimental/lrp_edits/roi.py:292, 625` vs `scanfields/transaction.py:83-89` — ROI editors destroy the LRP prolog that `reorder_jobs` exists to preserve.**
`lrp_clear_rois` and `lrp_add_roi` write via `ET.parse(...)` + `tree.write(...)`. Plain `ET.parse` drops all comments, and `tree.write` re-serializes without the pre-root Leica header comments — the exact artifacts `transaction.py:83-89` preserves "verbatim" with a comment explaining LAS X writes them. Inside one `apply_lrp_change` call the pipeline is: ROI edit strips the prolog and every in-document comment, then `reorder_jobs` carefully preserves what's left. Either the prolog matters (then ROI edits corrupt every template they touch) or it doesn't (then `reorder_jobs`' prolog machinery is unjustified complexity). The roi.py module docstring (roi.py:8-13) explains why structural edits use ElementTree but is silent on the comment/prolog loss.
**Action**: give roi.py the same treatment as `reorder_jobs` — parse with `ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))` and re-splice the prolog — or record evidence (a hardware round-trip) that LAS X regenerates the header on its confirm-save, in a comment at both sites.

**LS-17 — Medium — `experimental/lrp_edits/{scan,z,general,focus}.py` — ~40 near-identical set/verify wrappers invite drift.**
Every attribute editor is the same 10-line pattern: coerce value, call `_set_job_attr`, plus a mirror `lrp_verify_*` calling `_verify_job_attr`/`_verify_job_attr_float` (e.g. scan.py:30-46, 54-70, 158-176; z.py:75-95; general.py:29-47…). Review 2 credited this driver's `CONFIRM_SPECS` table for collapsing exactly this shape in the commands layer; the file-edit layer never got the same treatment. Concrete drift already exists: tolerance defaults are scattered ad hoc (0.01 zoom, 0.1 phase, 0.001 pan, 0.5 µm Z, 1.0 µm range) with no table to audit, and paired name attributes (`ScanDirectionXName`, `ZUseModeName`, `StackCalculationModeName`) are maintained by three separately hand-written enum dicts.
**Action**: a declarative spec table (`attr`, `coerce`, `verify kind`, `tolerance`, optional `name_attr`/`enum`) plus one generator, keeping only genuinely bespoke editors (`lrp_set_z_stack_size`, `lrp_set_stack_calculation_mode`, ROI structural edits) as code. This deletes several hundred lines and makes the tolerance policy auditable.

**LS-18 — Low [PATCHWORK] — `experimental/lrp_edits/roi.py:576, 582, 601, 607, 611, 619` — comments reference an untracked issue list; `MemoryBlockID` is a truncated UUID.**
"(issue 6)", "(issue 1)", "(issue 3)"… point at a numbering that exists nowhere in the repo — for a future reader these annotations are noise where they should be the hard-won LAS X format knowledge ("LAS X requires `<P>` elements, not `<Item>`" is the useful part). Separately, `mem_id = f"MemBlock_{uuid.uuid4().int % 100000}"` (roi.py:619) throws away the UUID's uniqueness: with dozens of ROIs the birthday collision odds are no longer negligible, and there is no reason not to use the full hex.
**Action**: replace issue numbers with the actual format facts; use `uuid.uuid4().hex`.

**LS-19 — Low — `experimental/lrp_edits/_primitives.py:43-46, 138-152` — job anchoring by first `BlockName="…"` substring match.**
`text.find(f'BlockName="{job_name}"')` finds the first occurrence anywhere: the sequence root also carries `BlockName` (see the fixture at `test_lrp_edit_primitives.py:48`), and a job name containing `"` silently never matches. The block-bounding that follows is careful (and the Sequential_Master cross-job bug is fixed and tested, focus.py:66-69, test_lrp_edit_primitives.py:139-156), but the anchor itself is the remaining soft spot shared by `_set_job_attr`, `_set_sequential_attr`, and `lrp_set_stack_calculation_mode` (focus.py:59-62).
**Action**: anchor on `<LDM_Block_Sequential` followed by the BlockName attribute (a small regex), or at least assert the match position is inside an `LDM_Block_Sequential` open tag; reject job names containing `"`.

**LS-20 — Low — stale docstrings from two package renames ago.**
`roi.py:90` claims "Imports: `_primitives`, `positions.parsers`" (the actual import is `...scanfields.parsers`, roi.py:101); `z.py:9` refers to "`templates.transaction.apply_lrp_change`" (now `scanfields.transaction`). Both dependency-direction footers are otherwise a genuinely good convention — which is why the stale ones actively mislead.
**Action**: fix both lines; grep the package for remaining `positions.`/`templates.` references.

### acquisition/

**LS-21 — High — `acquisition/ome.py` (entire module, 461 lines) — the OME check/fix layer, including the binary TIFF patcher, has no direct tests.**
`fix_ome_tiff` (ome.py:294-403) does raw `struct` surgery on TIFF IFDs with three distinct branches (in-place pad, tail extension, mid-file relocation with pointer rewrites) and endianness handling; `fix_ome_xml_bytes` (ome.py:241-291) does regex surgery with an infer-vs-remove fork. Every test that touches this layer mocks it (`test_acquisition.py:148-157, 594-618, 652-677` patch `check_ome_tiff`/`fix_ome_*`; `test_native_autosave.py:426-430` patches `_read_tiff_tag_270`). The one semi-real exercise (`test_acquisition.py:620-677`) runs the *canonical* pipeline where the violation never reaches the fixer (it asserts `fix_ome_tiff.call_count == 0`). So the code path that runs when a real Leica export carries `Wavelength="0"` — the module's entire reason to exist — is unpinned: a corrupted-offset regression would ship undetected and physically damage output TIFFs at save time (`materialize.py:96-100` repairs in place).
**Action**: unit tests that build small TIFFs (tifffile is already a test dep) with `Wavelength="0"` in tag 270 sized to hit all three patch branches, in both endiannesses; plus direct tests for `extract_wavelength_from_id`, `check_ome_xml_bytes`, and the remove-attribute fallback (ome.py:276-287).

**LS-22 — Medium — `acquisition/ome.py:387-391` — relocated tag-270 data can land on an odd offset.**
The mid-file relocation branch sets `new_offset = len(data)` with no alignment; TIFF 6.0 requires value offsets to be word-aligned ("must begin on a word boundary"). Most readers tolerate odd offsets, but the module's charter is producing *schema-valid* files, and strict validators/readers (and BigTIFF-era tooling) can reject them.
**Action**: pad one `\x00` when `len(data)` is odd before appending (two lines); cover in the LS-21 tests.

**LS-23 — Medium — `acquisition/ome_canonical.py:230-240` — `pixel_type_from_dtype` silently defaults unknown dtypes to `"uint16"`.**
A source plane with any unmapped dtype (int64, float16, a future tifffile dtype string) gets its OME `Type` declared as uint16 while the pixels written by `materialize.save_image_source_atomic` keep the true dtype — a self-inconsistent file that downstream readers will misinterpret quietly. This is the opposite of the fail-closed posture the collectors take.
**Action**: raise on unmapped dtypes; the mapping covers everything LAS X actually produces, so a miss means something upstream changed and must be looked at.

**LS-24 — Medium — `acquisition/lasx_native_autosave.py:160-172` vs `acquisition/navigator_expert_export.py:122-124` — the two collectors disagree on RelativePathName backslash handling.**
The navigator collector normalizes interior backslashes with a comment explaining exactly why (`'sub\\image.ome.tif'` is one filename component on a POSIX host); the native collector, written later against the same `read_relative_path` source, does only `lstrip("\\/")` (lasx_native_autosave.py:167). A relative value with an interior backslash silently fails the primary anchor and drops to the slower, more ambiguous mtime path (which then hard-fails on multiple fresh candidates). This is textbook copy-paste drift between parallel paths.
**Action**: extract one `_candidate_paths(rel, base)` normalizer into `acquisition/files.py` and use it in both collectors.

**LS-25 — Medium [PATCHWORK] — `acquisition/lasx_native_autosave.py:132-136` — the `.lcf` config is scraped with a global attribute regex.**
`re.findall(r'([A-Za-z0-9_]+)="([^"]*)"', text)` over the whole file collapses every attribute in the document into one dict — if `AutoSaveBaseFolder` (or `DoUseAutoSave`) appears on more than one element (multiple profiles, historical entries), the *last* occurrence silently wins with no warning. The file is XML; the driver parses far gnarlier XML elsewhere with ElementTree.
**Action**: `ET.parse` and select the specific element carrying the AutoSave settings; if the element name is unknown/unstable, at least detect duplicate keys in the findall and fail loudly.

**LS-26 — Medium — `acquisition/lasx_native_autosave.py:88-89, 316-323, 339-343`; `ome_canonical.py:201-206` — the anchor TIFF is fully re-read at least three times.**
`_positions_from_native_tiff` opens the TIFF (page mapping), `_metadata_from_native_tiff` opens it again *and* calls `extract_embedded_ome_xml`, and `_vendor_metadata_sources` calls `extract_embedded_ome_xml` a third time — and `extract_embedded_ome_xml` does `tiff_src.read_bytes()` (ome_canonical.py:203), loading the entire file into memory just to walk the first IFD. Native AutoSave stacks are the multi-gigabyte case this exporter exists for; three full reads (two of them whole-file memory loads) on a network share is real wall-clock and memory cost per acquisition.
**Action**: open the TiffFile once in `collect_lasx_native_autosave` and pass it (or the extracted XML bytes) down; make `_read_tiff_tag_270` read the header/IFD/tag region with seeks instead of requiring the whole file in memory (it already has all offsets it needs).

**LS-27 — Low — `acquisition/ome_canonical.py:356-387` — `_read_job_settings_bounded` swallows the worker exception and leaks a thread per timeout.**
`result["error"]` is captured (ome_canonical.py:378-379) and never logged or inspected; a reproducible reader crash looks identical to a slow read, and the caller's warning (ome_canonical.py:128-133) blames timing. Each timed-out call also abandons a daemon thread still holding the client. Bounded and deliberate, but the diagnostic is lost.
**Action**: log `result.get("error")` at warning level when present; note the thread-abandonment tradeoff in the docstring.

**LS-28 — Low [YAGNI] — `acquisition/save.py:309-313` — `_append_summary_atomic` is dead production code.**
After the batching refactor (save.py:167-170), `_persist_export` uses `_load_summary`/`_upsert_summary_record`/`_write_summary_atomic` directly; the composed helper's only caller is a test (`test_acquisition.py:1090-1101`).
**Action**: delete it and retarget the test at `_upsert_summary_record` + `_write_summary_atomic` (the behavior it actually pins).

**LS-29 — Low — three small truth-drift spots in `navigator_expert_export.py`.**
(a) The comment at lines 34-37 says the completion budget is "in the same regime as file stability (120 s)" while the constant is `60.0` (line 37) — one of them is wrong. (b) `collect_navigator_expert_export`'s `if not detected.source_files` check (lines 87-88) is unreachable: `_collect_positions_once` raises `_IncompleteExport` before ever returning empty positions (lines 265-268). (c) `_find_fresh_seed_by_mtime` sorts experiment dirs `reverse=True` by *name* (line 197) but then scans all of them and takes the global mtime max anyway (line 208) — the sort suggests a newest-first shortcut that doesn't exist.
**Action**: fix the comment or the constant; delete the dead check; drop `reverse=True` (or actually short-circuit).

**LS-30 — Low — `acquisition/ome_canonical.py:287, 306-313` — per-plane channel names are silently dropped for non-ASCII; UUIDs derive from bare filenames.**
`_ascii_channel` nulls any channel name that won't ASCII-encode (needed because tag 270 must be ASCII — the constraint is well documented at ome_canonical.py:443-445), but a name like `"DAPI µ"` could be preserved via XML character references (`&#181;` is pure ASCII) instead of vanishing from the per-plane file while surviving in the companion. Separately, `uuid5(NAMESPACE_URL, filename)` (line 287) means two different acquisitions producing the same canonical filename in different runs share the "unique" ID; within one companion it's consistent, but the OME UUID is meant to disambiguate file identity.
**Action**: escape non-ASCII names as character references (ElementTree does this automatically with `encoding="ascii"` on the plane XML); scope the uuid5 name to include the output-relative path or the acquisition hash.

**LS-31 — Low — `acquisition/save.py:162, 219` — the full `vendor_metadata` record list is duplicated into every plane record.**
A 12-plane native save writes the identical vendor-record array 12 times into `summary.json`; with T×Z×C in the hundreds this bloats the manifest for no information gain.
**Action**: write `vendor_metadata` once per acquisition (top level or first record) and reference it, or accept and document the denormalization.

**LS-32 — Low — cross-module seams in the OME pair.**
(a) `acquisition/ome.py:20-21` claims "Imported by: `__init__` (re-export)" but `acquisition/__init__.py` is empty (the re-export happens from the base `__init__.py:398-406`) — doc drift. (b) `ome_canonical.py:208` reaches into the sibling's private `_ome._read_tiff_tag_270`; if it's shared infrastructure, name it as such. (c) String-to-number converters now exist in triplicate: `scanfields/_convert.py`, `ome_canonical._int_or_none`/`_float_or_none` (ome_canonical.py:512-534), and ad-hoc parsing in ome.py.
**Action**: fix the docstring; either promote `_read_tiff_tag_270` to a public name in ome.py or move it to a shared `_tiff.py`; consider one converters module (low priority — the duplication is small and stable).

**LS-33 — Low — `_file_utils.py:14-27` — `_is_file_locked` requires write access, so read-only sources read as permanently locked.**
The probe opens `r+b`; on a file (or share) where the driver has read-only permission, `PermissionError` → "locked" → `_wait_file_stable` burns its entire budget and fails, even though the file is perfectly readable. The docstring frames PermissionError as "another process holds an exclusive lock", which is only one of its causes on Windows ACLs.
**Action**: fall back to an `rb` open when `r+b` fails with PermissionError — readable-but-not-writable should count as "not locked" for a collector that only reads sources; document the Windows-only semantics (on POSIX the function is always False, which is fine but worth a line).

### Tests

**LS-34 — High — `tests/unit/test_acquisition.py:577-592` — one test burns 60 s of real wall clock (88% of the in-scope suite).**
`test_missing_xml_raises` deletes the companion XML and then lets `_collect_positions` poll for the full default `DEFAULT_EXPORT_COMPLETION_TIMEOUT_S = 60.0` before the expected RuntimeError (measured: 60.06 s of the suite's 67.98 s). `test_uses_mtime_fallback_when_relative_path_is_empty` (test_acquisition.py:794-823) similarly eats the 5 s default `path_poll_timeout` because it forgets to shorten it while it *does* shorten `mtime_poll_timeout`. Every other completeness test in the file passes `export_completion_timeout=0.01` — these two just missed it. Review 2 flagged the same disease (uninjected real sleeps) in the commands suite; here it is two one-line fixes.
**Action**: pass `export_completion_timeout=0.01, export_completion_poll_interval=0.001` in `test_missing_xml_raises` and `path_poll_timeout=0.01` in the mtime-fallback test. Suite drops from ~68 s to ~3 s.

**LS-35 — Medium — `tests/unit/test_scanfield_strip_restore.py:39-48, 89-99` — strip/restore's failure machinery is untested; `_wait_file_stable` is never exercised anywhere.**
Both tests monkeypatch `save_experiment`/`load_experiment` to unconditional success, so the code that exists *because* LAS X misbehaves — the 4-attempt escalating-timeout restore ladder, backup-restore-on-timeout, object-count-mismatch rollback, and keep-baks-on-final-failure (strip_restore.py:310-365) — has zero coverage; a regression in the rollback copy order would only surface on a real instrument mid-failure, the worst possible place. Likewise `_wait_file_stable`/`wait_all_stable` (`_file_utils.py:29-66`, `acquisition/files.py:121-150`) are mocked in every consumer test and never run against a real changing file.
**Action**: add a strip/restore test where `save_experiment` fails N times then succeeds (asserting backups were restored between attempts and cleaned up after), and one where it always fails (asserting `.bak` files survive). Add a small `_wait_file_stable` test with a background writer thread and a locked-file simulation.

**LS-36 — Low — `tests/unit/test_scanfield_parsers.py:5, 15, 32ff`; `test_lrp_edit_primitives.py:14` — encoding corruption and redundant path hacks in test sources.**
The section-header comments in test_scanfield_parsers.py are mojibake (`â”€â”€…` — UTF-8 box-drawing characters double-encoded at some point), the module docstring still tells people to run `test_position_parsers.py` (a filename that no longer exists), and both files carry a `sys.path.insert` that `tests/conftest.py:10-14` already performs for every test.
**Action**: fix the header comments and the stale run instruction; delete the per-file `sys.path` inserts.

---

## Summary table

| ID | Severity | Title |
|-------|----------|-------|
| LS-01 | High | `parse_lrp` (380 lines, gates ROI verification) has zero unit tests |
| LS-02 | Medium | Global MatrixData grid count stamped onto every Rectangle geometry |
| LS-03 | Medium | Planned regions flatten 2-D grids; column-major order diverges from other region sources |
| LS-04 | Medium | Overlap inference brute-forces 501 full tile generations per parse |
| LS-05 | Low | [PATCHWORK] Unprovenanced magic tolerances and duplicated 5.0% default overlap |
| LS-06 | Low | [PATCHWORK] Mojibake patch + digit-filter size parsing; silent X/Y averaging |
| LS-07 | Low | [PATCHWORK] `Name`-or-`n` fallback tripled with no explanation |
| LS-08 | Low | `save_experiment`: raw mtime `>` without skew allowance; blanket `except Exception` |
| LS-09 | Low | `get_template_state` reports "fresh" for an unknowable environment |
| LS-10 | Low | `_strip_xml` raw-string surgery on XML |
| LS-11 | Low | `confirm_delays` misnomer; `reorder_jobs` failure ignored by the transaction |
| LS-12 | Low | [YAGNI] `parse_lrp` re-export shim for an in-repo import |
| LS-13 | Medium | [YAGNI] `experimental/` name is false: package is load-bearing — promote/rename |
| LS-14 | Medium | [YAGNI] `pixels_to_roi` + `center_vertices` are dead code |
| LS-15 | Medium | [YAGNI] Seven exported lrp_edits helpers have zero callers |
| LS-16 | Medium | ROI editors destroy the LRP prolog/comments `reorder_jobs` preserves |
| LS-17 | Medium | ~40 boilerplate set/verify pairs; needs the table-driven treatment commands got |
| LS-18 | Low | [PATCHWORK] Dangling "issue N" comments; truncated-UUID MemoryBlockID |
| LS-19 | Low | Job anchoring by first `BlockName=` substring match |
| LS-20 | Low | Stale docstrings (`positions.parsers`, `templates.transaction`) |
| LS-21 | High | Binary TIFF patcher and OME fix layer (461 lines) have no direct tests |
| LS-22 | Medium | Relocated tag-270 data can violate TIFF word-alignment |
| LS-23 | Medium | `pixel_type_from_dtype` silently mislabels unknown dtypes as uint16 |
| LS-24 | Medium | Native collector missing the backslash normalization the navigator collector documents |
| LS-25 | Medium | [PATCHWORK] `.lcf` config scraped with a global attribute regex; duplicates collapse silently |
| LS-26 | Medium | Native anchor TIFF fully re-read ≥3×, incl. whole-file `read_bytes` for one IFD |
| LS-27 | Low | Bounded job-settings read swallows the worker exception; thread leak per timeout |
| LS-28 | Low | [YAGNI] `_append_summary_atomic` dead in production, kept alive by a test |
| LS-29 | Low | Comment says 120 s, constant says 60; dead emptiness check; misleading reverse sort |
| LS-30 | Low | Non-ASCII channel names silently dropped per-plane; UUIDs from bare filenames |
| LS-31 | Low | Vendor-metadata records duplicated into every plane's summary entry |
| LS-32 | Low | OME pair seams: stale docstring, private cross-import, triplicated converters |
| LS-33 | Low | `_is_file_locked` treats read-only permission as a permanent lock |
| LS-34 | High | One test burns 60 s real time (88% of suite) via un-shortened default timeout |
| LS-35 | Medium | Strip/restore retry ladder and file-stability waiters have zero real coverage |
| LS-36 | Low | Mojibake headers, stale docstring, redundant sys.path hacks in test files |
