# Review: v4 calibration validation, review fixes, 3-pass backlash, live widgets, React edition

Response to `v4_calibration_check_and_fixes_review_prompt_for_fabel2.md`. Scope:
the three commits after the hardening commit `2230501` (`ae8bc3f` calibration
check + review fixes + 3-pass backlash, `d8ee29d` live widgets + React edition,
`6f784f5` incremental focus re-measure), sanity-checked against `origin/main`,
with the prior round's fixes (`v4_notebook_hardware_proof_review.md` findings
1–5) re-verified.

Deviating from the prompt's "do not implement fixes" on the maintainer's
explicit instruction (as last round): every finding marked **FIXED** below was
implemented, tested, and pushed in the follow-up commit on this branch. File:line
references are to the tree as reviewed (commit `6f784f5`), before the fixes.

Verification baseline before fixes: full offline suite
(`zmart_controller/tests`, `workflows/target_acquisition/tests`,
`navigator_expert/tests/unit`) → 1153 passed, 4 skipped in one process; ruff
clean. After fixes: 1174 passed, 4 skipped; ruff clean on every changed file;
both notebooks parse as valid JSON and pass their structural guard tests.

---

## Findings

### 1. blocker — the recommended limits notebook publishes an envelope the v4 preflight refuses — FIXED

`navigator_expert/motion/stage_config.py:196` (`adopt_limits(source=LIMITS_SOURCE_DEFAULTS)`)
with `limits/notebooks/set_stage_limits.ipynb` cell 1 (no `source=` argument),
against the v4 jobs cell's new check `limits.get("source") != "machine"`.

The prior round's finding 1 was fixed by requiring `source == "machine"`, and
the error message tells the operator to "publish this machine's measured
envelope with limits/notebooks/set_stage_limits.ipynb". But that notebook calls
`adopt_limits` without `source=`, and the default was `"defaults"` — so the
published limits.json still reads `source: "defaults"`, the preflight refuses
again, and the message sends the operator back to the same notebook, forever.
Concrete scenario: a correctly configured rig, measured envelope published
exactly as instructed → the v4 notebook cannot pass step 3a at all. No other
production writer of the exotic source tags exists (checked: `boundary_markers`,
`scan_field`, `migration`, `cfg_fallback` are vocabulary only), so the fix has
no side effects.

Why tests missed it: no test ran the publish → handshake → preflight chain;
`test_stage_config.py` and `test_limits_adversarial.py` never asserted the
published `source` value at all.

Fix applied: `adopt_limits` now defaults to `"machine"` (an adopted envelope IS
the machine's measured truth; the docstring says when to pass `"defaults"`),
and `test_adopted_limits_report_machine_source_to_the_notebook_preflight` pins
the whole chain, ending on the exact refusal expression the notebook evaluates.

### 2. major — the calibration check reported a fake systematic error of up to half an overview pixel — FIXED

`workflow/_calibration_check.py:236-254` (`_pair_offset_um`'s window math).
Two independent bias sources, both constant across sites, so they biased the
MEAN — the exact number the check exists to measure:

- `crop_overview_at_target_fov` floors `cx − w/2`, so whenever the coarse
  window width came out odd, the coarse crop sat half an overview pixel off
  centre while the fine crop sat exactly centred. Same shapes every site →
  same shift every site → reads as calibration error.
- The crop centred on the physical pixel-centre convention while the rest of
  the pipeline (`overview_pixel_to_frame`) maps pixels to stage positions with
  the `index − size/2` convention — a second constant offset of half the
  pixel-size difference.

Measured (synthetic world, ZERO injected error): mean offset **+1.11 µm** with
odd-geometry shapes, **+0.55 µm** with realistic Stellaris shapes (512² overview
at 1.516 µm / 1024² target at 0.379 µm) — the same order as the errors the
check hunts. An operator would have "corrected" a perfectly calibrated rig.

Why tests missed it: the synthetic test's shapes (100²@1.0 / 120²@0.5) happen
to produce an even, exactly-centred coarse window, and its ±0.5 µm tolerance
absorbed the convention term.

Fix applied: both windows are now resampled in exact sub-pixel coordinates
about each image's centre, in the pipeline's own pixel convention (one shared
rule, `scipy.ndimage.map_coordinates`, coarser image interpolated up, finer
sampled 1:1). Residual bias measured ≤ 0.02 µm on all probe geometries.
`test_a_perfect_stage_reports_no_systematic_error` pins the hostile geometry.
Measuring in the pipeline's convention is deliberate: the reported offset is
then exactly the error the workflow's own targeting would experience.

### 3. major — the sign the operator is told is the OPPOSITE of the sign reported — FIXED

`workflow/_calibration_check.py:28-31` (module docstring) and `:271-275` (the
negation comment) both said a site's `(dx_um, dy_um)` is "where the objective-2
image found the sample relative to the objective-1 image". The value actually
reported (and pinned by the test, whose comment is correct) is where objective 2
**landed** — the two differ by sign: when the stage lands +3 µm too far in x,
the sample appears at −3 µm in the image. An operator (or maintainer) applying
a correction per the docstring would move the calibration the wrong way and
double the error instead of cancelling it. The driver math confirms the landing
error is the actionable number: `set_xyz` commands `origin + frame + ΔT`
(`zmart_adapter.py:509-512`), so a mean of +e means T[objective 2] is too large
by exactly e.

Why tests missed it: prose cannot fail a test; the numbers themselves were
right.

Fix applied: docstring, negation comment, and both notebooks' 5b markdown now
state the landing-error meaning, what a positive value means physically, and
what to do about it (re-run the objective-pair calibration; the mean is what
the objective-2 translation is off by).

### 4. major — six unconfirmed stage moves per capture: 3-pass takeup tripled a known contract gap — FIXED

`navigator_expert/motion/movement.py:161,165` checked only `r.get("success")`,
while the sibling `move_xy_with_backlash` requires `confirmed` on both legs
with an explicit rationale (`movement.py:100,107`). The MOVE_XY profile ships
`success_on_unconfirmed=True`, so a leg whose readback never confirms still
returns success. This is the long-open LM-02 finding
(`docs/reviews/findings_verification.md`) — and the 3-pass loop tripled the
exposure right before every capture: a sluggish final return leg hands the
stage to `acquire` while it may still be travelling back from the overshoot
point, and the record then says `settle: "backlash-corrected"`.

Why tests missed it: no `TestCorrectBacklash` case fed `confirmed: False`.

Fix applied: every leg now requires `success` AND `confirmed`, mirroring the
sibling's contract; plus a settle pause at pass boundaries (without it, a
controller that blends consecutive commands could run pass N's return straight
into pass N+1's overshoot, and the extra passes would settle nothing), a
whole-number check on `passes` (3.9 no longer silently truncates), and the
module header no longer describes the old single-pass sequence. New tests pin
the full move/sleep interleaving, unconfirmed-leg refusal, mid-pass failure
propagation (no further moves fire), and fractional-pass refusal.

### 5. major — a failed re-run left the PREVIOUS run committed as "the result" (both editions) — FIXED

matplotlib: `workflow/_acquisition_widget.py:111-168` — `acquire()` assigned
`self.picked`/`self.records` only on success and never cleared them at entry.
React: `workflow/react/_widgets.py` gallery, same shape. Scenario: run 1
acquires 5 targets successfully; run 2 fails at target 2. The figure/gallery
shows run 2's honest partial rows, but `gallery.records` still holds run 1 —
the summary cell's `if not gallery.records` guard passes and the run report
describes targets the operator is not looking at.

Why tests missed it: both failure tests started from a fresh gallery where
"nothing committed" and "previous result" coincide (both empty).

Fix applied: both galleries clear `picked`/`records` the moment a new hardware
run starts, so a failed re-run always leaves an honestly empty result that the
summary guard refuses. Pinned by success-then-failure tests in both suites.

### 6. major — streamed overview contrast (and its slider bounds) froze on the first tile — FIXED

`workflow/_overview_widget.py:210-212` initialised the display window AND the
slider's fixed bounds (`full_range`, `:277`; `RangeSlider` construction
`:388-397`) from tile 1 alone on the streamed path; batch construction pools
all tiles. Scans commonly start in a dim, empty corner: the whole growing map
is then mis-contrasted, and because the slider bounds were frozen too, the
operator **could not reach** the bright cells of later tiles with any control
on the figure.

Why tests missed it: every test tile is spatially uniform, so first-tile stats
equal all-tile stats.

Fix applied: the display window deliberately stays put (a growing map must not
re-brighten under the operator's eyes — documented), but the slider bounds now
widen with every arriving tile, and the docstring says the initial contrast is
seeded from the first tile. Pinned by
`test_streamed_slider_bounds_grow_to_reach_brighter_tiles`.

### 7. major — React streaming resent the whole map on every tile (quadratic), gallery rows unbudgeted — FIXED

`workflow/react/_widgets.py:244` (`self.tiles = self.tiles + [...]`), `:839`
(rows), `:861-881` (`_row_entry` with no pixel budget — full-resolution target
images), `:223-230` (`_step_for` ignored the channel count), and every
keystroke in a channel min/max box retransmitted every tile. A trait update
always resends the entire list, so tile k's arrival retransmitted k tiles:
for a real 25-tile 2-channel scan, on the order of hundreds of MB of cumulative
websocket traffic with single messages in the tens of MB — enough to stall the
operator's "live" view mid-hardware-run, which is precisely the state this
design exists to avoid.

Why tests missed it: only a single tile's downsample step was pinned; nothing
measured cumulative payload or serialization.

Fix applied: a streaming protocol (documented in `workflow/react/PROTOCOL.md`):
each new tile/row travels once as a custom message; the trait holds the full
snapshot, refreshed when a browser view mounts (it sends `sync`) and at commit
points (run end, reload). Every image — tiles AND gallery rows — is kept under
a per-image pixel budget that now counts channels, and the channel min/max
boxes commit on blur/Enter instead of per keystroke. Traffic is proportional
to the data. Pinned by `test_overview_tiles_stream_as_messages_not_trait_resends`
and `test_gallery_streams_rows_and_commits_on_success`.

### 8. major — the React gate mask was browser-writable and trusted — FIXED

`workflow/react/_widgets.py:550,665-668`: `gated_mask` is a synced trait, and
`explorer.gated` read it directly. Any JS in the notebook page could send a
state update `{"gated_mask": [true]*N}` without touching `gate`; Python never
recomputes, the next Acquire samples targets outside the drawn thresholds and
lasso, and the dots even recolour to match the forged mask. (Hardware exposure
stays bounded by the session's limits gating, but it is a genuine gate bypass.)

Why tests missed it: tests set `gate` and read `gated`; none wrote the mask.

Fix applied: `gated` recomputes the mask from the raw `gate` every time it is
read (and heals the display trait if something scribbled over it);
`gated_mask` is documented as display output only. Pinned by
`test_forged_gated_mask_cannot_widen_the_gate`.

### 9. major — React scripted runs skipped the busy/debounce bookkeeping — FIXED

`workflow/react/_widgets.py:824-859`: public `acquire()` never set `busy` or
`_last_run_ended` (only the message path did, `:72-84`). Scripted
`gallery.acquire(5)` in a cell — a documented pattern — left the browser button
enabled and the debounce unarmed: a click queued during the scripted run
started a second full hardware acquisition the instant the cell finished. The
matplotlib gallery does its bookkeeping inside `acquire()` itself, so this was
also a parity break.

Fix applied: one `_hardware_run` helper carries the busy flag and the debounce
stamp for every hardware path, button or script, in both the gallery and the
focus picker (which also gained the public `measure()` the matplotlib picker
always had). Validation failures raise BEFORE the stamp, fixing the related
divergence where "the gate is empty" armed the debounce and then ate the
operator's corrective click with a misleading "queued click" message. Pinned by
`test_gallery_scripted_run_arms_the_click_debounce` and
`test_gallery_refused_run_does_not_arm_the_debounce`.

### 10. minor — NaN leaked into `calibration_check.json` (not valid JSON) — FIXED

`workflow/_calibration_check.py:263-268,277-282`: untrusted sites carried
`float("nan")`, and `json.dumps` happily writes `NaN` — which strict JSON
parsers (a browser's `JSON.parse`, `jq`) refuse, so any downstream tool
choking on the report would be a silent failure of the check's own record.
Fix applied: untrusted sites carry `null`, the dump runs with
`allow_nan=False` as a guard, and the summary statistics/plot filter on
"trusted AND has values". Pinned by
`test_untrusted_sites_write_null_not_nan_into_the_json`.

### 11. minor — the check could waste a hardware run and then blame the sample — FIXED

Two operator-facing failure modes of section 5b, both now caught before or
explained at the point of failure:

- **Focus extrapolation** (`start_calibration_check` + `steps.with_focus_z`):
  the ring (default radius 1000 µm) usually sits far outside the measured
  focus points, and the thin-plate-spline surface extrapolates wildly out
  there. The moves stay inside the stage's safety envelope, but the images
  are hopelessly defocused → sites untrusted → the error message blamed
  "texture". Fix: `_refuse_wild_focus_extrapolation` raises before ANY stage
  move when the predicted ring z leaves the measured z range by more than a
  generous margin, naming the real cause and both remedies (focus points that
  cover the ring, or a smaller `radius_um`). Pinned by
  `test_a_ring_far_outside_the_focus_points_is_refused_before_moving`.
- **Stage-limits refusal mid-pass** (`capture_positions` → gated `set_xyz`):
  a ring site outside the measured envelope refuses at move time, mid-run —
  unavoidable without a driver-side dry-run API (the workflow is
  controller-only and cannot convert frame to absolute coordinates itself),
  so the wrapper now explains what happened, that nothing wrong was acquired,
  and to re-run with a smaller `radius_um`. The trusted-site failure message
  now mentions defocus alongside texture.

### 12. minor — malformed browser input could freeze React widgets in a stale state — FIXED

`workflow/react/_widgets.py:698-705` (gate contents), `:275-280` (channel
contents), `:57` (non-dict messages), `:716-718` (hover index overflow). A
half-typed threshold reaching Python as `null`, a bogus colour string, a
non-dict message, or `{"index": 1e999}` raised inside a trait observer or
message handler — leaving `gated_mask` stale relative to the stored gate (the
next Acquire samples a gate the operator is not seeing) or the tiles frozen,
with nothing on the status line. Fix applied: gate and channel contents are
sanitized at use (unparseable pieces simply do not gate / fall back to
defaults), non-dict messages are dropped, and `OverflowError` joined the hover
index guard. Pinned by four new tests.

### 13. minor — a failed React measure exposed a partial focus surface — FIXED

`workflow/react/_widgets.py:463-475`: `_show_fresh_point` streams
`self.focus = fit_focus_surface(...)` per point; a mid-run exception left that
partial fit on `picker.focus` (the matplotlib picker invalidates on exception).
`require_focus()` still refused, so the notebook path was safe — but any script
reading `picker.focus` directly got a plausible-looking surface fitted to a
partial point set. Fix applied: invalidate-and-reraise, matching matplotlib.
Pinned by `test_focus_failed_measure_does_not_expose_a_partial_surface`.

### 14. minor — a drawing hiccup could wedge the matplotlib gallery — FIXED

`workflow/_acquisition_widget.py:131-137`: `_busy = True` was set before
`_begin_gallery`/`force_draw`, which ran OUTSIDE the try/finally that resets
it — an ipympl draw failure there left `_busy` stuck True and every later
Acquire refused with "already running". Fix applied: the drawing moved inside
the try.

### 15. minor — a broken old controller blocked a setup re-run (both notebooks) — FIXED

Setup cell: the re-run path shut the old ENGINE down best-effort (prior
finding 4) but called `zmart_controller.disconnect()` unguarded — a raising
teardown aborted the cell before the new engine was created. (`Session`
marks itself closed before calling the driver, so the second re-run would
proceed — one wasted round and a confusing error.) Fix applied: the old
controller's disconnect is best-effort with a printed warning, exactly like
the engine's, in both notebooks.

### 16. minor — the React notebook described controls its widgets do not have — FIXED

`zmart_microscopy_v4_react.ipynb` cells 17 and 20 were copied from the
matplotlib notebook: "pan and zoom with the toolbar", "drag the display range
slider", "the radio lists", "the two range sliders" — none of which exist in
the React UI (drag/scroll, min/max boxes, dropdowns). Wrong instructions for
exactly the audience CLAUDE.md protects. Fix applied: both cells rewritten for
the real controls; the focus cell also documents the map's +y-down orientation
(it matches the overview maps; the matplotlib focus picker draws y up — noted
on the figure caption so an operator switching editions is not surprised).

### 17. minor — offline, a React cell just stayed blank — FIXED

`workflow/react/_support.py:86-87`: React loaded via static ESM imports from
esm.sh; with no internet in the browser the module itself fails and anywidget
shows nothing — "the notebook is broken", mid-run, with the truth only in the
devtools console. The docs disclosed the requirement but the failure mode was
invisible. Fix applied: dynamic imports with a visible plain-language note in
the cell (what happened, and that `zmart_microscopy_v4.ipynb` is the offline
edition). *Addendum: the follow-up expansion commit on this branch went
further and vendored React outright — the official MIT builds now ship in
the package and load into a private scope, so the React notebook works
fully offline and no third-party code is fetched at all.*

### 18. nit — assorted, all FIXED

- `_calibration_check.py:48-49`: the comment above `_MIN_TRUSTED_SITES`
  described a different constant (voting tolerance). Rewritten.
- `_plot_report` never closed its figure when only saving; repeated runs piled
  figures up in matplotlib's registry. Closed when `show=False`.
- React hover crops re-read the full-resolution tile from disk on every event
  (matplotlib caches). Cached, pinned by test.
- `movement.py` module header still described the single-pass takeup and
  "one fewer move". Updated.

### 19. worth mentioning — noted, deliberately not changed

- **Per-tile hardware time**: with `backlash_correction` on, every capture now
  runs 8 backlash-related moves (2 transit + 6 takeup) where v3 ran 4; the
  24-acquisition calibration check gains on the order of a minute. Visible
  only at DEBUG log level. Acceptable for correctness-first, but worth knowing
  when sizing a session.
- **matplotlib streamed-path memory**: the streamed overview viewer keeps
  full-resolution stacks (no auto-downsample on that path, unlike batch);
  a 25-tile 2048² 2-channel scan holds roughly 1.6 GB with display copies.
  Pass `downsample=` for very large live scans.
- **Focus AF-cache reuse is coordinate-exact and never expires** on its own;
  the new `measure(fresh=True)` / **Measure fresh** button is the operator's
  tool for drift. Reuse counts were already shown in the title/status.
- **matplotlib focus picker draws +y up** while both overview maps and the
  React focus map draw +y down. Left as-is (operators know the figure; the
  coordinates sent to hardware are correct either way) but now annotated.
- The smart-analysis v4 contract remains unverifiable offline — finding 6 of
  the prior review stands unchanged.

## Also added on maintainer instruction (same follow-up commit)

Beyond the fixes, a bounded usability expansion of the widgets, designed
around the maintainer's stated plan to embed them in a website later:

- **`workflow/react/PROTOCOL.md`** — the complete trait/message contract of
  every React widget (the seam a website front end builds against), including
  the streaming rule, the trust boundary, and the three things an embedding
  needs to know.
- **Overview (React)**: a **Fit** button; the view stops auto-refitting the
  moment the operator pans or zooms (a growing map no longer yanks the view
  away mid-inspection); a live cursor readout in frame micrometres; channel
  min/max boxes commit on blur/Enter; wheel zoom uses a native non-passive
  listener so the page no longer scrolls while zooming.
- **Focus (React)**: a **Measure fresh** button (forget the session's cached
  autofocus results and re-drive every point — for drift), a scriptable
  `measure()` with the same guards as the button, and the orientation caption.
- **Focus (matplotlib)**: `measure(fresh=True)` for the same drift case.

## Verified correct (with the reasoning that convinced me)

- **Sign chain end-to-end**: stub session models the landing error exactly as
  the driver realizes it (`set_xyz` commands origin + frame + ΔT; the stub
  renders at commanded + error); `register_voting` reports apparent content
  shift (TGT relative to REF); one negation yields the landing error; the
  ground-truth test recovers (+3, −2) sign-correct. The reported mean is what
  T[objective 2] is off by.
- **5b isolation**: `calcheck`/`calibration_report` feed no later cell; the
  check's acquisitions use their own `cal-check-ref`/`cal-check-cmp`
  acquisition types; nothing globs `calibration_check.*`; skipping 5b leaves
  the run intact.
- **Prior fixes 2–5 faithful**: debounce windows open only after a completed
  run (first clicks never eaten, programmatic matplotlib paths undebounced as
  documented, ignored clicks announced on the figure); engine shutdown in a
  `finally` on the setup failure path; re-run engine teardown best-effort;
  validator SKIPs an empty focus-point list with a plain-language reason while
  still requiring the procedure to exist (mock path exercised via run_ci).
- **3-pass call sites**: exactly two production callers (adapter acquire,
  `backlash_takeup` procedure), both bare-argument; no move counting,
  watchdogs, or expected-duration logic anywhere on the path; targets read
  once before the loop so an unconfirmed leg cannot accumulate positional
  error; adapter tests replace the helper wholesale; the hardware validator
  asserts only the settle label; the Zeiss driver's single-pass helper and
  its docs are untouched; retired flows use only `move_xy_with_backlash`.
- **Live-update honesty**: `capture_positions` returns records only on full
  completion, `on_record` exceptions abort loudly; a fresh gallery's failed
  run keeps honest rows and commits nothing; the focus picker invalidates on
  mid-measure failure and `require_focus` refuses; the analysis inputs come
  from `overview_inputs_from_records` (positions + returned records, length-
  checked), never from viewer state; the v4 overview cell's order —
  create viewer → stream pre-hijack pixels → hijack → `reload()` — re-reads
  the rewritten files.
- **Rendering cost**: all `force_draw` calls run synchronously on the kernel
  main thread (nothing is threaded); per-tile draws are dwarfed by per-tile
  hardware time on a 25-tile scan.
- **React notebook guards**: cell-by-cell diff against the v4 original —
  origin, limits `source == "machine"`, jobs distinctness, engine preflight
  before connect, setup-failure teardown, summary guard, cleanup cell are
  byte-identical or equivalent; only the matplotlib activation was removed
  (enforced by its structural test).
- **React parity**: gating semantics (thresholds AND lasso, degenerate lasso
  ignored, axis switch clears the gate), commit-only-on-success, count
  validation (`isdecimal`, rejects everything non-positive), hover index
  bounds, empty-gate/empty-target refusals, and the shared image math
  (`composite_channels`, `crop_for_target`, `pair_images`) — identical
  behaviour, most of it literally shared code.
- **Message paths cannot overlap hardware runs**: comm messages serialize
  behind the running handler; with the busy flag and debounce now shared by
  scripted paths, every double-run sequence we could construct is closed.

## Residual risks that only hardware (or a live browser) can retire

1. The smart-analysis v4 contract and the Cellpose environment (prior
   review's finding 6, unchanged).
2. Physical z additivity of z-wide + z-galvo, and the real LAS X
   native-AutoSave layout (prior review, unchanged).
3. The registration sign on the real optical path: the synthetic chain is
   pinned end-to-end, but one hardware run with a deliberately mis-set
   translation remains the definitive check.
4. The real LAS X images' pixel-centre convention: the check now measures in
   the pipeline's own convention (`index − size/2`), which makes its report
   exactly the error the workflow's targeting experiences — but whether that
   convention matches the optics to better than half a pixel is a hardware
   question.
5. Featureless-but-structured images: shared vignetting or fixed-pattern
   signal registers at zero offset with high agreement, so a dim sample can
   pull the calibration check's mean toward zero (under-reporting). Run the
   check on a textured region; the std guard only catches perfectly flat
   frames.
6. Backlash mechanics: whether three passes measurably beat one on the ZMB
   leadscrews; whether the 20 µm confirm tolerance can "confirm" a return leg
   short enough to matter against 3–5 µm backlash; LC-09 (a positionally
   stale but freshly timestamped readback instantly confirming a leg).
7. The focus-extrapolation guard's margins (10 µm floor, half the measured
   span) are conservative choices; hardware experience may want them tuned.
8. Browser-only behaviour: esm.sh availability and the offline note's
   rendering across JupyterLab versions, wheel/pointer-capture behaviour of
   the pan and lasso surfaces, `useStream`'s trait-vs-message ordering under
   a real websocket, ipympl draw latency with 25 large tiles, multi-tab
   sessions sharing one model.
