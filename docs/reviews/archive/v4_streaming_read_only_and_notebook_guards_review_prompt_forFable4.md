# Review request: bounded React replay, model-wide read-only state, curation integrity, duplicate targets, and thin notebooks

Review only the changes on branch `claude/leica-calibration-review-qlgzcq`
after commit `6e93a99`. Use `git diff 6e93a99..HEAD` as the authoritative
scope. Do not reopen unrelated findings from earlier branch history or review
the repository generally. This is safety-adjacent code used to drive a real
Leica Stellaris 5, so review the scoped changes adversarially and do not
implement fixes.

The changes under review are limited to:

- `zmart_controller/layer.py`
- `zmart_controller/tests/test_layer.py`
- `workflows/target_acquisition/workflow/_discovery_widget.py`
- `workflows/target_acquisition/workflow/_run_status.py`
- `workflows/target_acquisition/workflow/react/_support.py`
- `workflows/target_acquisition/workflow/react/_widgets.py`
- `workflows/target_acquisition/workflow/react/PROTOCOL.md`
- `workflows/target_acquisition/tests/test_discovery_widget.py`
- `workflows/target_acquisition/tests/test_react_widgets.py`
- `workflows/target_acquisition/tests/test_v4_notebook.py`
- `workflows/target_acquisition/tests/test_v4_react_notebook.py`
- `docs/reviews/v4_calibration_check_and_fixes_review.md`
- this review prompt

The two v4 notebook files themselves are not changed in this diff. The new
notebook tests are in scope: verify that their assertions accurately enforce
the intended property that notebooks stay thin orchestration and demonstrate
the public `zmart_controller` lifecycle, without embedding workflow or driver
implementation.

## Intended fixes to verify

### 1. Bounded React catch-up and object-URL ownership

`workflow/react/_support.py`, `workflow/react/_widgets.py`, and `PROTOCOL.md`
replace image-bearing base64 snapshot traits with metadata traits plus
`tile:reset` / `row:reset` and indexed binary replay. Live overview images use
the existing 1.5-million-pixel budget; catch-up tiles and gallery images use a
250,000-pixel budget. Browser object URLs are owned by `index:key` and revoked
when that entry is replaced, on reset, and on unmount.

Walk the actual orderings for one and multiple views:

- mount before, during, and after a hardware run;
- a `sync` handled between two live messages;
- two tabs whose `sync` requests cause broadcast reset/replay messages;
- replacement of the same index and a replay that shrinks a prior list;
- empty image buffers and partial/sparse lists.

Look for permanent missing/duplicated entries, stale images, unbounded payloads,
or object-URL leaks. Confirm the protocol document describes the implementation
exactly and does not retain the old base64-snapshot model.

### 2. Model-wide read-only freeze

`_ZmartWidget.make_read_only()` now explicitly freezes the anywidget model,
not one browser tab. A private Python flag is the authority; the synced
`read_only` trait is only a display mirror. Browser-writable input traits are
snapshotted and restored, forged `read_only = false` is healed, hardware calls
are refused, and direct or message-driven cancellation is refused.

Try to bypass the freeze through every scoped route: custom messages, direct
`handle_message`, direct scripted hardware methods, trait writes, channel
recompositing, focus-point edits, explorer axis/gate edits, verdict edits, and
cancel. Check observer registration/re-entrancy and repeated
`make_read_only()` calls. Distinguish trusted Python-side display updates needed
to keep an observer current from untrusted browser input. Flag any claim of
per-tab permissions; this design intentionally cannot provide them.

### 3. Gallery curation truth and sparse row identity

The gallery now owns verdict truth in private `_verdicts`; the synced trait is
healed if forged, and `save_curation()` uses strict row/verdict alignment.
Every streamed row carries `stream_index`, which the UI uses for verdicts even
when a mid-run view temporarily renders row 5 as the first nonempty item.

Attack forged truncation/extension, invalid verdicts, failed or cancelled
runs, a second run with fewer rows, sparse delivery, replay after a completed
run, and lightbox-versus-verdict indexing. Check that private verdict state,
records, row metadata, displayed verdicts, and `curation.json` cannot diverge.

### 4. Duplicate-valued target reconciliation

Both explorer editions now use `_matching_target_indices()`. Original object
identity wins; copied records fall back to equality; one source index is
consumed at most once per call; previously acquired indices are excluded only
from equality fallback so repeating an original object remains idempotent.

Exercise distinct equal-valued targets in one call and across calls, mixtures
of originals and copies, repeated originals, more copies than source entries,
unknown targets, and changed ordering. A defect here can leave a cell available
for accidental reacquisition or mark the wrong cell as acquired.

### 5. Honest lifecycle status

`zmart_controller.Session.closed` exposes only whether `disconnect()` closed
the local session. `_run_status.py` uses it and no longer claims a live probe;
engine status likewise says what was and was not checked.

Verify the wording for open, closed, absent, legacy/unknown session objects,
and engines whose shutdown flags are present. It must not claim transport or
worker liveness that it did not test. Confirm disconnect remains idempotent and
the new property does not alter the controller/Leica adapter contract.

### 6. Thin-notebook guard tests and documentation claims

The new notebook tests reject function/class definitions and pin these public
examples in both v4 notebooks:

- `workflow.connect("leica")`
- `zmart_controller.set_origin()`
- `zmart_controller.get_state()`
- `zmart_controller.run_procedure({"name": "get_positions"})`
- `zmart_controller.disconnect()`

Decide whether these checks meaningfully prevent implementation from drifting
back into notebooks while allowing concise operator orchestration. Confirm the
notebooks still execute through the existing end-to-end harness and do not call
Leica driver internals directly. Review only the new guards and claims, not
unrelated notebook UX.

## Validation to reproduce

Use Python 3.10. The active controller/workflow suite should report:

```text
pytest -q zmart_controller/tests workflows/target_acquisition/tests
297 passed
```

The Leica driver's canonical offline gate is unchanged by this diff but is the
cross-layer regression proof:

```text
cd zmart_drivers/leica/stellaris5_y42h93/navigator_expert
python run_ci.py --mock
1030 passed, 1 skipped; 83.21% coverage; ruff check clean
```

The single skip is expected off the microscope PC because the LAS X CAM API
DLLs are unavailable. Independently syntax-check all six generated React ESM
modules with Node, run ruff check/format on the changed Python files, and run
`git diff --check`.

Do not attribute these known out-of-scope baseline items to this diff unless
you can show the scoped changes caused them:

- `ruff format --check` on the entire Leica driver reports three untouched
  files (`motion/movement.py`, `test_limits_adversarial.py`, and
  `test_stage_backlash.py`);
- the retired pre-controller workflow suite has stale import/API tests. The
  active `workflow` package and both v4 notebooks are the subject here.

## Deliverable

Report findings ordered blocker / major / minor / nit. Every finding must have
an exact `file:line`, a concrete failing sequence, impact, why the present tests
miss it, and the smallest safe fix. Then give a short verified-correct section
and a residual-risk section containing only what genuinely requires a live LAS
X microscope or a real Jupyter browser/websocket session. If there are no
findings, say so explicitly without inventing style work.
