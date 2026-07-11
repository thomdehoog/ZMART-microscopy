# Review: bounded React replay, model-wide read-only state, curation integrity, duplicate targets, and thin notebooks

This report answers
`v4_streaming_read_only_and_notebook_guards_review_prompt_forFable4.md`.
Scope reviewed: `git diff 6e93a99..HEAD` (one commit, `5b8d9a7`), adversarially
and without implementing fixes in this review pass. Every finding below was
either reproduced with running code (marked **confirmed**) or traced through
the exact source lines (marked **plausible**). Line numbers refer to the
tree at `5b8d9a7`.

## Findings

There are no blockers: the read-only lock holds against every browser-origin
route that was tried, and no finding lets the browser drive hardware. Both
majors are ways the curation record can stop matching what the operator
sees.

(A first draft of this report contained an additional major claiming that a
view mounting mid-run crashes on its second out-of-order live message. That
was a misreading of unchanged diff context: `useStream` copies with
`prev.slice()`, which preserves array holes, and returns
`items.filter(...)`, which compacts them before render — verified in Node.
Sparse delivery is handled correctly, and `stream_index` correctly decouples
verdicts from the compacted render position. The claim is retracted.)

### major 1 — the freeze does not cover scripted `set_verdict`, and healing it desynchronises the displayed verdicts from the saved ones

`workflows/target_acquisition/workflow/react/_widgets.py:1727`
(`set_verdict` has no `_hardware_allowed` check) interacting with
`:135` (`_reject_read_only_input`) because `verdicts` is in the gallery's
`_read_only_input_traits` (`:1533`).

Failing sequence (confirmed):

```python
gallery.acquire(2)
gallery.set_verdict(0, "good")
gallery.make_read_only()
gallery.set_verdict(1, "bad")        # accepted — no RuntimeError
gallery._verdicts                    # ['good', 'bad']   (private truth)
gallery.verdicts                     # ['good', None]    (what every tab shows)
gallery.save_curation(root)          # writes ['good', 'bad']
```

What happens inside: `set_verdict` updates the private list and calls
`_publish_verdicts`, which sets the synced trait. That write triggers
`_reject_read_only_input` (the widget is frozen), which restores the trait
to its freeze-time snapshot. The nested restore is silently absorbed by
`_heal_verdict_trait` because `_publishing_verdicts` is still `True`. Net
result: `_verdicts` and `curation.json` say one thing, every browser view
says another — precisely the divergence area 3 requires to be impossible.
It also contradicts the new `make_read_only` docstring, which promises
that "hardware messages **and scripted calls** are refused": `acquire`,
`acquire_selected`, `measure`, and now `request_cancel` all refuse when
frozen, but the QC record stays writable.

Impact: a frozen gallery's curation record can be changed while all views
keep displaying the old verdicts; the saved `curation.json` no longer
matches what anyone on screen approved.

Why the present tests miss it: `test_read_only_view_refuses_hardware...`
tries `acquire`, cancel routes, and forged traits, but never a scripted
`set_verdict` after `make_read_only()`, and no test compares
`gallery.verdicts` with `gallery._verdicts` after a frozen write.

Smallest safe fix: refuse in `set_verdict` when `not
self._hardware_allowed` (matching `acquire`'s RuntimeError wording), so
truth and display cannot diverge and the docstring's promise holds.

### major 2 — after a cancelled or failed run, curation state is misaligned and `save_curation` raises a raw `zip()` error

`workflows/target_acquisition/workflow/react/_widgets.py:1855`
(`self._verdicts = [None] * len(picked)` at run start) versus `:1886`
(`self.records = records` only on commit) and `:1758`
(`zip(self.records, self._verdicts, strict=True)`).

Failing sequence (confirmed):

1. Acquire 3; cancel after the first pair. Per the cancel contract,
   nothing commits: `records == []`, `picked == []`. But the streamed row
   is still in `_row_entries` (and still on every screen — messages are
   not unsent), and `_verdicts` is still `[None, None, None]`.
2. The operator clicks ✓ on the visible row — `set_verdict(0, "good")` is
   accepted, because its bound is `len(self._row_entries)`.
3. `save_curation(root)` raises
   `ValueError: zip() argument 2 is longer than argument 1`.

Impact: no wrong data reaches disk (strict zip fails closed, which is an
improvement over the silent truncation it replaced), but the three lengths
that area 3 says must agree — records (0), row entries (1), verdicts (3) —
all disagree after every cancelled or failed run, verdicts can be recorded
against rows that were never committed, and the operator sees an
incomprehensible Python error instead of an explanation.

Why the present tests miss it: the cancel test asserts `records == []`
and the curation tests only run `save_curation` after a fully committed
run; nobody calls `set_verdict` or `save_curation` after a cancel.

Smallest safe fix: size `_verdicts` with the rows as they stream (append
`None` per committed pair in `_show_fresh_pair`) and clear it when the run
fails, so all three lengths always agree; bound `set_verdict` by
`len(self._verdicts)`; then `strict=True` can never fire and an empty
curation of a failed run saves as an honest `[]`.

### minor 3 — `_matching_target_indices` lets a copied record steal an index that an original in the same call owns by identity

`workflows/target_acquisition/workflow/_discovery_widget.py:70`.

The function resolves targets one at a time, so the equality fallback for
an early *copied* record can consume the index that a *later original* in
the same call would claim by identity. Confirmed:

```python
A = {...}; B = {...}          # distinct cells, equal-valued
_matching_target_indices([A, B], [copy_of_B, A])   # -> [0]
```

`copy_of_B` equality-matches index 0 first; `A`'s identity match then
finds index 0 already used and is dropped. Only cell 0 is marked
acquired — cell 1 (B, which *was* physically imaged) stays unfilled on
the map and available for accidental re-acquisition, the exact failure
the prompt warns about. With the reverse order `[A, copy_of_B]` the
result is the correct `[0, 1]`.

Impact: low reachability — the gallery passes originals, so a mixture of
copies and originals in one call takes a scripted caller (for example
replaying one target from a saved record alongside live ones) — but when
it happens a cell can be double-imaged (photodamage, wasted run time).

Why the present tests miss it: the new tests exercise copies across
*separate* calls and originals together, never a copy-then-original
mixture in a single call.

Smallest safe fix: two passes — resolve every identity match first
(reserving those indices), then run the equality fallback for the
remainder in order.

### minor 4 — a frozen widget refuses harmless display-only messages with a misleading status

`workflows/target_acquisition/workflow/react/_widgets.py:159`
(`_route_message` refuses everything but `sync` when frozen), versus the
explorer's `hover` (`:1476`) and the overview's `mark` (`:739`) handlers,
which only read state and update a Python→browser preview trait.

Failing sequence: freeze an explorer; move the mouse across the scatter.
Every dot entered sends `{"type": "hover", index}`; each one is refused
and stamps `status` with "this view is read-only — hardware actions are
disabled". The observer loses the crop preview — the main thing a
read-only reviewer would use — and the status line permanently shows a
warning about hardware that nobody touched.

Impact: usability of the observer mode this diff is building; no safety
effect (refusing is the fail-safe direction).

Smallest safe fix: a per-widget allowlist of display-only message kinds
(`hover`, `mark`) that `_route_message` still forwards when frozen —
`pick`, `verdict`, `acquire*`, `cancel` stay refused.

### minor 5 — freezing an empty overview viewer makes every later tile render black

`workflows/target_acquisition/workflow/react/_widgets.py:543`
(`_init_channels` ends in `self.channels = channels`) versus `:135`
(`_reject_read_only_input`).

Failing sequence (confirmed): `make_read_only()` on a viewer with no
tiles yet (snapshot of `channels` is `[]`), then feed it tiles —
`add_tile`/`add_acquisition` are correctly *not* hardware-locked, because
they are trusted Python-side display feeds. The first tile triggers
`_init_channels`, whose trait write is indistinguishable from a forged
browser write and is reverted; `channels` stays `[]`, so every composite
renders with zero channels (black tiles), and the browser cannot fix it
because the channel controls are frozen. The rejection status is then
overwritten by the tile-count status, so there is no trace of why the
map is black.

Impact: an observer view frozen before a scripted overview run shows a
black map for the whole run.

Why the present tests miss it: the freeze tests always freeze *after*
data exists.

Smallest safe fix: perform trusted Python-side trait writes under the
existing `_restoring_read_only_input` flag (and refresh the stored
snapshot), so the reject observer knows the write is not browser input.

### minor 6 — a forged `read_only = true` on an unlocked widget sticks

`workflows/target_acquisition/workflow/react/_widgets.py:118`
(`_heal_read_only_trait` returns early when `self._hardware_allowed`).

Failing sequence (confirmed): on a live, unlocked widget, browser code
sets `read_only = true`. The heal observer only defends the locked
direction, so the trait stays `true`, and every tab of that widget hides
its buttons (including Cancel — though the Python cancel path itself
still works, a browser view has no button left to send it with). Python
still allows hardware, so the display now lies in the safe-looking but
wrong direction.

Impact: a page script can blind every operator tab's controls mid-run;
recovery needs a scripted `widget.read_only = False`. Fail-safe
direction, but the trait is supposed to be an honest mirror both ways.

Smallest safe fix: heal both directions — when unlocked and the new
value is `True` (and the write did not come from `make_read_only`),
restore `False`.

### nit 7 — any tab mounting downgrades every other tab's live images

`push_snapshot` broadcasts `tile:reset`/`row:reset` plus a replay to
*all* views (anywidget custom messages are not addressed to one view).
Because catch-up tiles use the tighter 250 k-pixel budget
(`_widgets.py:54`), a view that has been watching full-budget live tiles
has them replaced by the smaller snapshot copies whenever any other tab
mounts, and the whole map briefly clears. Bounded and correct, just a
visible quality drop with no note in `PROTOCOL.md`. Worth one sentence in
the protocol (or replaying at the live budget when the tile count is
small).

### nit 8 — small documentation/test claims that do not match the code

- `PROTOCOL.md:44`: "the matching trait holds the full metadata
  snapshot" — the trait is only refreshed at sync/commit, so mid-run it
  lags the messages (the gallery's is `[]` during a run). One clause
  ("refreshed at sync and commit") would make it exact.
- The notebook guards allow `lambda` bodies (`ast.Lambda` is not in
  `implementation_nodes`), so logic can still drift into notebooks one
  expression at a time. Cheap to add if the guard is meant to be strict.

## Validation reproduced

- `pytest -q zmart_controller/tests workflows/target_acquisition/tests`
  → **297 passed** (after installing `nbformat`/`nbclient`/`ipykernel`,
  without which the three notebook tests — including the new guards —
  silently skip; worth adding to the dev-requirements note).
- Leica driver gate `python run_ci.py --mock` → **RESULT: PASSED**;
  junit shows 1049 tests, 0 failures, 1 skipped (the expected CAM-DLL
  skip). Note the prompt's stated baseline (1030 passed, 83.21 %
  coverage) is stale for this branch: the suite now reports 1048 passed +
  1 skipped and **85.94 %** coverage — higher on both counts, nothing
  regressed.
- `ruff format --check` over the driver flags exactly the three known
  baseline files (`motion/movement.py`, `test_limits_adversarial.py`,
  `test_stage_backlash.py`) — unchanged by this diff.
- All six generated React ESM modules pass `node --check`.
- `ruff check` and `ruff format --check` are clean on every changed
  Python file; `git diff --check 6e93a99..HEAD` is clean.

## Verified correct

- **Bounded replay**: live overview tiles are budget-bounded at load time
  by the downsample step (counting channels); catch-up and gallery images
  are shrunk to 250 k pixels; the worst-case-payload test's arithmetic is
  sound. `tile:reset`/`row:reset` precede every replay; indexed
  replacement plus reset handles shrinking lists and same-index
  replacement; object URLs are owned per `index:key` and revoked on
  replacement, reset, and unmount — I found no URL leak in any ordering I
  could construct (single or multiple views, sync between live messages,
  double sync).
- **Read-only freeze, browser side**: every browser-origin route tried —
  custom messages (acquire, acquire_selected, verdict, pick, cancel),
  direct `handle_message`, forged `read_only = false`, forged `channels`
  / `points` / `x_feature` / `y_feature` / `gate` / `verdicts` writes —
  is refused or healed; repeated `make_read_only()` is idempotent and does
  not re-snapshot; scripted `acquire`, `acquire_selected`, `measure`, and
  both cancel routes refuse. The docstrings and PROTOCOL.md correctly
  claim a model-wide lock and disclaim per-tab permissions.
- **Curation truth on the committed path**: forged truncation, extension,
  and invalid values in the `verdicts` trait are healed from `_verdicts`;
  `set_verdict` validates value and index; strict zip keeps
  `curation.json` aligned with records on every committed run, including
  a second, smaller run; `stream_index` rides every row message and
  snapshot entry, equals the wire index, and the gallery's verdict
  buttons use it rather than the compacted position.
- **Duplicate targets**: both editions share `_matching_target_indices`;
  distinct equal-valued originals in one call, copies across calls,
  repeated originals (idempotent), more copies than sources, and unknown
  targets all resolve correctly (minor 4 is the one ordering left).
- **Lifecycle honesty**: `Session.closed` reports only what
  `disconnect()` did, `disconnect` stays idempotent, and the property
  does not touch the controller/adapter contract. `run_status_rows` says
  "last known; no live probe", warns on `closed`/shut-down objects, and
  reports "connection health is unknown" for legacy objects without the
  property — it claims no liveness it did not test.
- **Notebook guards**: both v4 notebooks pass the AST guard (no function
  or class definitions) and pin the five public `zmart_controller`
  lifecycle calls; the end-to-end harness still executes both notebooks
  offline. The guards are a meaningful ratchet: implementation can only
  return to the notebooks as top-level statements, which the
  controller-only string checks and reviewers will see. (Lambda loophole
  noted in nit 9.)

## Residual risk (genuinely needs a live microscope or a real browser session)

- Real websocket ordering: whether a host that handles comm messages
  concurrently can interleave a live `row`/`tile` between a broadcast
  reset and its replay (transiently losing the newest item until the next
  sync), and whether `push_snapshot` iterating `zip(..., strict=True)`
  can race a concurrent `add_tile` append. Both need a threaded,
  non-Jupyter host to observe.
- Browser behaviour of revoking an object URL that an `<img>` is
  currently displaying (all mainstream browsers keep the decoded image,
  but this is unspecified), and `URL.createObjectURL` availability under
  restrictive notebook CSPs.
- ipympl/classic-Jupyter cancel latency (the PROTOCOL's honesty note) and
  actual wheel/pointer-capture behaviour of the pan/lasso surfaces.
- Whether the LAS X CAM DLL skip hides any driver/widget interaction that
  only exists on the microscope PC.
