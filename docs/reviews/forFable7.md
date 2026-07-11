# Review request: Fable 6 fixes and controller-only website launch

Review only the corrective diff from `b993203` to the tip of
`claude/forfable4-document-11mxsx`. This is a follow-up to
`docs/reviews/forFable6_review.md`; do not re-review unrelated repository
history.

The Leica driver is intentionally out of scope and is not modified. Treat it as
incomplete, user-owned work. You may verify controller call shapes at the
workflow boundary and confirm `git diff b993203..HEAD -- zmart_drivers` is
empty, but do not propose or make driver changes.

## Changed surface to review

- `workflows/target_acquisition/workflow/webapp/`
- `workflows/target_acquisition/workflow/react/_support.py`
- `workflows/target_acquisition/workflow/react/_widgets.py`
- `workflows/target_acquisition/workflow/viz.py`
- `workflows/target_acquisition/run_webapp.py`
- both `zmart_microscopy_v4*.ipynb` notebooks
- the changed target-acquisition tests and READMEs

## Required review

Verify every Fable 6 finding is actually closed, including adversarial timing
and failure sequences:

1. Local `model.set` changes notify React synchronously, so multiple edits made
   before a server echo compose rather than overwrite one another.
2. Position loading restores the captured overview state through
   `Session.set_state` before `get_positions`, in the website and both
   notebooks. No driver implementation is changed.
3. Website report generation is explicitly headless and repeated saves leave
   no open matplotlib figures.
4. Sync requests coalesce while queued but one follow-up sync can queue while a
   replay is executing.
5. Replay resets preserve good object URLs; missing binary buffers retry once,
   retain prior images, and report the refresh failure. Destructive new-run
   resets must still clear old images.
6. Loopback-bound HTTP rejects hostile `Host` headers on reads and writes.
7. A queue-full SSE client receives a close sentinel so EventSource reconnects.
8. Lasso input uses pointer capture, ignores sub-5-pixel slips, cleans up
   cancelled/lost pointers, and dot pointerdown does not also start a lasso.
9. Every state snapshot path is serialized against SSE events; a failed first
   snapshot retries and unwedges the page; events for dynamically importing
   widgets remain ordered until React subscribes.
10. Engine shutdown is attempted at most once, microscope disconnect still
    occurs on failure, and retries report the same honest failure.
11. Hardware messages older than the queue expiry are dropped with operator
    feedback; immediate cancel cannot be erased by run startup.
12. The live website launcher establishes package paths, registers the adapter
    in the same process, then uses only the public `zmart_controller.Session`
    surface. Demo launch must remain driver-free.
13. Both notebooks remain thin controller/workflow demonstrations: no direct
    driver calls, no function/class implementation, and only the documented
    one-line simulation-forwarding lambda.

Also inspect the fixes themselves for new races, resource leaks, stale-closure
bugs, false success states, replay duplication, unsafe HTTP assumptions, or any
path that could cause delayed/unexpected hardware motion. Trace the complete
affected path from browser action through `WidgetHub`, `RunFlow`, workflow
helpers, and `zmart_controller.Session`, while keeping driver internals out of
scope.

## Validation to reproduce

From the repository root in the Python 3.11 validation environment:

```text
python -m pytest -q -rs zmart_controller/tests workflows/target_acquisition/tests
```

Expected locally: `338 passed, 3 skipped`; all three skips are the known
network-blocked `skimage.data` mitosis download.

Run the real Chromium file at least three consecutive times:

```text
python -m pytest -q workflows/target_acquisition/tests/test_webapp_browser.py
```

Expected each run: `5 passed`. These tests include the full operator demo,
snapshot ordering/retry, rapid local edits while the worker is blocked, binary
replay failure with URL preservation, and real pointer-driven lasso gestures.

Also run:

- `ruff check` on `zmart_controller` and `workflows/target_acquisition`;
- `ruff format --check` on the changed Python files;
- `git diff --check b993203..HEAD`;
- nbformat validation and end-to-end execution of both v4 notebooks (included
  in the pytest command);
- `node --input-type=module --check` for all six generated widget ESM modules
  and the page module script;
- `python run_webapp.py --demo --port 0` from
  `workflows/target_acquisition`, followed by a successful `/state` request.

For compatibility evidence only, the unchanged Leica mock gate was run and
reported `1030 passed, 1 skipped`, 83.21% coverage. Its three existing
`ruff format --check` warnings are baseline and must not be fixed in this diff.

## Deliverable

Write findings by severity (`blocker`, `major`, `minor`, `nit`) with exact
file/line references and a concrete failing sequence. Separate verified-correct
areas from findings and state clearly what still needs real LAS X, the actual
analysis engine, or non-Chromium browser validation. Do not modify files.
