# Review request: calibration-check fixes, limits provenance, backlash contract, React streaming protocol, widget expansion

You are reviewing the commit(s) on branch `claude/leica-calibration-review-qlgzcq`
in `thomdehoog/ZMART-microscopy` that follow `6f784f5` ("Focus step: incremental
re-measure and heatmap-tinted tile markers"). Review them against `6f784f5`,
then sanity-check the whole branch against `origin/main`. The round you are
checking is documented in `docs/reviews/v4_calibration_check_and_fixes_review.md`
(findings 1–18 claim fixes in these commits, and two further expansion commits follow; verify each fix is faithful and
introduces no new defect). The round before that is
`docs/reviews/v4_notebook_hardware_proof_review.md`.

This is safety-adjacent code for a real Leica Stellaris 5. Do an adversarial
code review. Do not implement fixes. Prioritize wrong stage coordinates,
unsafe or surprising hardware actions, silent failures, and misleading
operator-facing state over style. Anything outside the listed scope that is
worth mentioning: mention it.

## What the commit contains

### A. Calibration-check corrections (highest priority — the math changed)

`workflows/target_acquisition/workflow/_calibration_check.py`.

1. **The resampler rewrite.** `_pair_offset_um` no longer crops whole pixels;
   both images are resampled about their exact centres onto the fine grid via
   `map_coordinates`, deliberately in the PIPELINE's pixel convention
   (`index − size/2`, matching `overview_pixel_to_frame`) rather than the
   physical pixel-centre convention (`(size−1)/2`). The review doc argues this
   makes the report "exactly the error the workflow's targeting experiences".
   Re-derive that argument independently. Is it right for both even and odd
   image sizes? Does `mode="nearest"` at the window border, or `order=1`
   interpolation smoothing, bias `register_voting`'s estimate in any direction?
   Is `int(round(window/fine_ps))` safe against float representation for
   realistic pixel sizes?
2. **The new pre-move guards.** `_refuse_wild_focus_extrapolation` (raises
   before any motion when the ring's predicted z leaves the measured focus
   range by more than max(10 µm, half the span)) and `_capture_ring`'s
   refusal re-wrap. Can the guard refuse a legitimately curved sample? Can the
   re-wrap mask a non-limits RuntimeError in a way that misleads? Does the
   guard's `getattr(focus, "measured", None)` behave with every focus object
   the notebook can produce (constant/plane/spline, and `focus=None`)?
3. **NaN → null.** Untrusted sites now carry `None`; summary statistics and
   the plot filter on `trusted AND has values`; `json.dumps(...,
   allow_nan=False)`. Hunt for any remaining path where NaN/None can reach
   the JSON, the plot, or arithmetic (e.g. a vote that is trusted but carries
   a non-finite value; `confidence` values; a report re-read by other code).
4. The docstring/comment/notebook-markdown sign language ("how far objective 2
   LANDED") — is it now unambiguous and consistent everywhere it appears
   (module docstring, negation comment, both notebooks' 5b cells, README)?

### B. Limits provenance flip

`navigator_expert/motion/stage_config.py::adopt_limits` now defaults to
`source="machine"`; the new chain test in `test_limits_adversarial.py` pins
adopt → limits.json → handshake → `describe()` → the notebook's exact refusal
expression. Hunt for anything that RELIED on the old `"defaults"` default:
other callers, snapshots carried forward, migration paths, tests, docs, the
`set_stage_limits` notebook's markdown. Confirm a fresh-seeded machine (bundled
defaults copied into ProgramData) still reports `source: "defaults"` so the
preflight still refuses unmeasured rigs — the flip must not weaken the check it
exists to satisfy.

### C. Backlash contract tightening

`navigator_expert/motion/movement.py::correct_backlash`: every leg now requires
`success` AND `confirmed` (resolving LM-02 for this helper), a settle sleep at
pass boundaries, and a whole-number `passes` check. On the real profiles
(`success_on_unconfirmed=True`, 3 s confirm windows, 20 µm tolerance), estimate
the false-refusal rate this adds to EVERY capture (6 legs × every tile) — is a
sluggish-but-fine rig now unable to acquire? Check the mock CAM used by
`run_ci`/validator confirms moves, and that nothing upstream catches the new
RuntimeError and continues. Verify the new tests (interleaved move/sleep pin,
unconfirmed-leg refusal, mid-pass failure propagation, fractional refusal)
actually pin what they claim.

### D. Widget honesty fixes (both editions)

1. Gallery stale-commit fix: `picked`/`records` now clear at run start
   (matplotlib `_acquisition_widget.py::acquire`, React `_widgets.py::_acquire`).
   Is there any path that reads `picked`/`records` DURING a run and now sees
   them empty where it used to see the old run (simulation hijack callbacks,
   `after_acquire`, notebook cells)?
2. matplotlib streamed overview: `_widen_full_ranges` grows slider bounds per
   tile and rebuilds the active slider. Does rebuilding the slider mid-stream
   fight the operator's in-progress drag? Does the batch path double-init
   safely? Is the "window stays put" behaviour still pinned?
3. The `_begin_gallery`-inside-try move and the guarded old-controller
   disconnect in both notebooks' setup cells.
4. `measure(fresh=True)` (matplotlib) — check cache-clear interacts correctly
   with `_measured_points`/invalidations.

### E. The React streaming protocol (second-highest priority — new design)

`workflow/react/_support.py` (`useStream`, the vendored React runtime,
`NumBox`, `useWheel`), `workflow/react/_widgets.py` (messages + `sync`
snapshots, `_hardware_run`, gate recompute-at-use, sanitizers, crop cache),
`workflow/react/PROTOCOL.md`, tests in `test_react_widgets.py`.

1. **Protocol races.** A view mounts mid-stream: messages sent before its
   `msg:custom` listener attached are lost, and its `sync` request is only
   served when the kernel is free. Walk the orderings (mount before / during /
   after a stream; two tabs; a `sync` snapshot arriving between two `tile`
   messages) — can a view end up PERMANENTLY missing or duplicating a tile or
   row? The JS keys streamed items by `index` into a sparse array and filters
   holes — check index collisions across a `reload()`/`_retile()` that shrinks
   or reorders entries.
2. **Trust boundary after the rework.** `gated` recomputes from the raw gate
   and heals the mask trait; gate/channel contents are sanitized at use;
   non-dict messages dropped; hover index bounds + OverflowError. Try to
   construct any remaining browser-driven sequence that acquires ungated
   targets, starts overlapping hardware runs (note `_hardware_run` is not a
   lock — messages serialize on the kernel, but verify nothing re-enters), or
   wedges a widget.
3. **The `_hardware_run`/debounce unification.** Validation raises before the
   stamp (so refused runs don't eat the corrective click) — but a run that
   fails ON HARDWARE still stamps. Is that the right asymmetry everywhere
   (gallery, focus, both editions)? The busy flag is a synced trait — can the
   browser write `busy=false` mid-run and re-enable the button, and does
   anything break if it does (the kernel serializes messages, but check the
   status/state consequences)?
4. **Payload budgets.** `_step_for` now counts channels; gallery rows shrink
   via `shrink_to_budget`. Estimate the worst remaining single message and the
   full `sync` snapshot for 25 tiles / 10 rows — acceptable? The `channels`
   edit path still recomposites and resends ALL tiles in one trait set —
   bounded enough after the budget?
5. **History note:** an intermediate commit used a dynamic CDN import with a
   visible offline fallback; the follow-up commit replaced it with the
   vendored runtime (section F.1). Review the FINAL state, but check the
   intermediate commit introduced nothing that outlived it (e.g. stale docs
   or tests still speaking of esm.sh).
6. **Expansion features.** Fit button + user-interaction latch (does a
   streamed tile still refit when the operator HASN'T interacted — and stop
   when they have?), cursor µm readout (correct under pan/zoom math?),
   `NumBox` commit semantics (can a stale `value` prop overwrite a fresher
   Python-side value?), focus "Measure fresh" (cache cleared even when the
   subsequent run fails?), the React focus map's documented +y-down caption.
7. The notebooks' rewritten markdown (React cells 0/11/17/20, both 5b cells)
   against the actual UI and behaviour — no remaining drift.

### F. Expansion wave 2 (a further commit on the same branch — review it with the same severity)

The maintainer asked for a broad usability expansion. New surface to attack:

1. **Vendored React** (`workflow/react/vendor/`, `_support.py::_vendored_react_js`).
   The official UMD builds are evaluated inside a function whose
   `window`/`self`/`globalThis` parameters shadow the page globals with a
   private object, `.call`-ed so `this` is that object too. Verify the
   isolation argument (can react-dom 18.3.1's UMD reach the real page
   `window` any other way — event handling, scheduler, `MessageChannel`,
   `requestAnimationFrame`? those APIs resolve through the scope chain to
   real globals: is that correct and safe?), the licensing hygiene, and
   whether `_esm` strings of ~150 KB per widget class cause any
   notebook-side problem. Check the SHA-pinned files match the npm
   originals if you can.
2. **Binary buffers** (`png_bytes`, `buffer_keys`, `useStream`'s object-URL
   lifecycle). Hunt leaks (URLs revoked on snapshot replace and unmount —
   but what about an entry replaced by a LATER message at the same index?),
   ordering (buffers vs `buffer_keys`), and the empty-buffer path
   (`b""` for a missing pair image).
3. **Cooperative cancel** (`_capture_run.RunCancelled`, `cancel=` through
   `capture_positions`/`measure_focus`/`run_overview`/`acquire_targets`,
   the base widget's `request_cancel`, the Cancel buttons). Is the
   "cancelled run reads as unfinished, never as a shorter success"
   contract airtight on every path (gallery, focus, calibration check,
   scripted)? Is the Jupyter honesty caveat (queued click may arrive after
   the run) stated everywhere an operator could form the wrong belief?
4. **Observer mode** (`make_read_only`). The lock is a private attribute;
   the synced `read_only` trait is display only. Try to drive hardware
   from a read-only widget by any path (message, trait write, scripted
   call, `handle_message` direct). Note `sync` and `cancel` are still
   routed — is answering `cancel` from an observer view correct policy?
5. **Targets on the map** (`show_targets`/`marks`/`mark_hover`, both
   editions; the React edition recolours live via an observer on the
   explorer's `gated_mask`). Check the observer lifecycle (re-calling
   `show_targets` must not stack observers), coordinate correctness
   against tile extents, and the crop-cache behaviour.
6. **Focus residuals** (`_focus_surface.residuals_um`/`worst_residual_um`,
   surfaced in both editions). For the spline model the fit passes near
   the points by construction — do the residuals still mean anything
   (smoothing=0.1), and is the operator language honest about that?
7. **Curation** (`verdicts`, `set_verdict`, `save_curation`, ✓/✗ buttons),
   **gate presets** (`save_gate`/`load_gate`, both editions — check the
   matplotlib slider clamping on out-of-range loads), **display persistence**
   (`save_display`/`load_display`), **histograms** (`hist` trait), the
   **run-status checklist** (`_run_status.py`, `RunStatusReact`,
   `print_run_status` — is every row's detection honest, e.g. can
   "Microscope: connected" show for a session whose connection died?), and
   the **calibration report panel** (`CalibrationReportReact` — check the
   arrow exaggeration math and the verdict text against the report's sign
   conventions).
8. **UX wave 3 (a further commit).** Attack the targeted-acquisition path
   hardest: `toggle_pick`/`picked_gated`/`acquire_selected` (both editions)
   — can any sequence (forged `picked_indices` trait, gate edited between
   pick and acquire, picks surviving an axis switch, note_acquired's
   value-equality matching on duplicate targets) image a cell the gate
   excludes, or mis-mark the acquired set? Also: the `_eta_text` honesty
   rules; scale-bar arithmetic (map: screen-px from `view.scale`; rows:
   percent of `width_um`); the lightbox (verdict clicks must not open it —
   check the stopPropagation); Enter-to-acquire vs the busy flag; the
   explorer↔map cross-highlight loop (can hover ping-pong?); the
   lasso-vs-click discrimination (`moved` ref) on the scatter and the
   double-click pick in matplotlib (conflicts with the LassoSelector?);
   crops rendered with the viewer's display window (stale cache when the
   window changes is accepted — is that documented enough?); the
   colour-blind palette plumbing.
9. **Notebook execution harness** (`tests/test_notebooks_run_end_to_end.py`):
   every code cell of both notebooks executes offline against a simulated
   session/engine, with operator actions scripted between cells. Check what
   it can and cannot prove: the connect/engine boundary is monkeypatched
   (so the setup cell's failure paths never run here), `exec` differs from
   IPython (no display of trailing expressions, no magics), and the scripted
   actions could mask an ordering bug a real operator would hit (e.g. a
   button pressed before a cell finishes). Is the injected-calibration
   assertion tolerance (±0.5 µm) tight enough to catch a sign regression?
10. Both notebooks gained a status cell and inline wiring
   (`viewer.show_targets(targets, explorer)`, the React 5b cell now ends
   with `wreact.calibration_report(...)`). Confirm the guard tests still
   pin what matters and that no cell depends on a variable defined later.

### G. Cross-cutting

- `docs/reviews/v4_calibration_check_and_fixes_review.md` itself: spot-check
  its claims against the code — a review doc that overstates a fix is worse
  than no doc.
- `workflow/react/PROTOCOL.md` against the implementation — every trait,
  message, and rule listed must be real, and nothing load-bearing missing.
- Suites: ruff clean on changed files; `pytest zmart_controller/tests
  workflows/target_acquisition/tests navigator_expert/tests/unit` = 1193
  passed, 4 skipped in one process. Say what those numbers still cannot prove.
- The residual-risk list at the end of the review doc — challenge it: is
  anything listed there actually verifiable offline after all, and is
  anything missing from it?

## Deliverable

Findings ordered blocker / major / minor / nit, each with exact `file:line`,
a concrete failing scenario, why existing tests miss it, and the smallest fix.
Then a short verified-correct section and a residual-risk list containing only
claims that require the real microscope or a live browser.
