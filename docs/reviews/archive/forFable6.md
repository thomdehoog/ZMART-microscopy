# Review request: corrective web hardening and full controller-to-website workflow audit

Review branch `claude/forfable4-document-11mxsx` in
`thomdehoog/ZMART-microscopy`. First review the corrective changes after
commit `9f13398` with `git diff 9f13398..HEAD`. Then evaluate the complete
active target-acquisition workflow end to end: controller contract, Leica
adapter boundary, both v4 notebooks, React widgets/protocol, simulation,
and the plain-browser website. Do not review the retired pre-controller
pipeline. This drives a real Leica Stellaris 5; review adversarially and do
not implement fixes.

## Corrective diff in scope

The changes after `9f13398` should be limited to:

- `workflows/target_acquisition/workflow/webapp/_flow.py`
- `workflows/target_acquisition/workflow/webapp/_host.py`
- `workflows/target_acquisition/workflow/webapp/_server.py`
- `workflows/target_acquisition/workflow/webapp/_page.py`
- `workflows/target_acquisition/workflow/webapp/README.md`
- `workflows/target_acquisition/workflow/react/_widgets.py`
- `workflows/target_acquisition/tests/test_webapp.py`
- `workflows/target_acquisition/tests/test_webapp_browser.py`
- `workflows/target_acquisition/tests/test_react_widgets.py`
- `workflows/target_acquisition/README.md`
- `docs/reviews/forFable5.md`
- this prompt

The corrective diff answers every finding from the forFable5 review. Verify
the fixes themselves and look for regressions introduced by them.

## 1. Coordinate-frame and step-order state machine — highest priority

`RunFlow` now enforces this prerequisite chain:

```text
connect -> set_origin -> capture_overview_job -> capture_target_job
        -> load_positions -> measured focus -> run_overview
        -> discover_targets -> acquire/curate -> save_results
```

Disconnect remains available immediately after connect so the operator can
always release a partial session. Every other completed hardware step is
one-shot; `save_results` may repeat so later verdict edits can be saved.

Attack all orderings, especially setting/re-setting the origin after positions
or focus coordinates exist, queuing later steps before earlier queued steps
finish, disconnecting early, retrying a failed step, acting after disconnect,
and refreshing the page midway through the chain. No reachable sequence may
apply coordinates computed in one origin frame after the origin changes.

## 2. Duplicate actions, queue pressure, and immediate cancel

The host work queue is bounded. `RunFlow` coalesces a duplicate pending step;
the widget host coalesces queued/running `acquire`, `acquire_selected`,
`measure`, and `sync` messages per widget. The page disables a step button
synchronously, but Python is the authority. Cancel remains the only immediate
request-thread mutation and must work even when the worker queue is full.

Try double-clicks and thousands of concurrent/local-client requests before,
during, and after a long hardware run. Confirm no second overview, focus, or
target run can emerge later from stale queue entries; no unbounded memory
growth occurs; queue-full responses are actionable; browser-optimistic traits
recover from Python truth; and cancel cannot mutate anything except the
private cancellation flag plus its honest status sentence.

## 3. Snapshot/SSE ordering and multi-tab truth

An SSE client is registered before EventSource can report `open`. The page
buffers live events while `/state` is captured/applied, then replays them in
order, both at first boot and reconnect. The widget registry is locked while
its item list is copied for a snapshot.

Force trait, message, widget-created, and flow events into every boundary:
before snapshot capture, during capture, between widget mounts, during replay,
and immediately after replay. Test two tabs, dropped/reconnected streams,
simultaneous `sync` requests, a run starting while a new tab boots, and a run
ending while it boots. An old snapshot must never overwrite newer `busy`,
`read_only`, gate/pick/acquired truth, status, completed steps, or streamed
images. Look for object-URL leaks and expired-buffer holes during catch-up.

## 4. HTTP validation and hostile local clients

The server rejects invalid Content-Length, malformed/non-object JSON,
unknown routes/widgets/steps, non-dict messages/changes, unknown traits, and
trait values that fail traitlets validation. Accepted work is still applied on
the single worker. Queue saturation returns 503; invalid input returns 400;
missing resources return 404. The browser reports request failures and
re-snapshots traits after rejected optimistic edits.

Attack every GET/POST with wrong types, oversized bodies, nested structures,
invalid JSON constants, path traversal, slow bodies, queue saturation, and
disconnects during writes. Confirm failures cannot reach hardware, kill the
worker/server, produce unbounded tracebacks, or leave the page displaying an
input Python rejected. Also reassess the localhost/no-auth threat model,
cross-origin request behavior, Host handling, and whether binding can be
accidentally broadened.

## 5. Curation transaction integrity

The gallery's rollback boundary now includes `acquire_targets`, the optional
`after_acquire` simulation/image-rewrite hook, and post-hook image rereading.
Until all succeed, `picked`/`records` do not commit. On any failure, private
verdict truth and its trait are empty while already-saved streamed rows may
remain visible but uncuratable.

Attack acquisition failure, cancel, hook failure, hook mutation of the records
list, image reread failure, snapshot/send failure, a smaller retry, forged
verdict traits, read-only mode, and saving after every state. At every public
boundary, `records`, committed targets, private verdicts, displayed verdicts,
and `curation.json` must agree; strict zip must be unreachable as an error.

## 6. Full workflow, notebooks, and website parity

Independently trace the production path:

```text
website/notebook
  -> workflow.connect("leica")
  -> zmart_controller Session
  -> Leica zmart_adapter
  -> origin/state/positions/focus/overview/discovery/target acquisition
  -> report + curation
  -> disconnect
```

Verify every workflow call exists on the controller and every controller op is
implemented by the Leica adapter. Check stage-limit provenance, state/job
capture, actuator selection, coordinate frames, focus extrapolation, gate and
pick revalidation, failure/cancel commit boundaries, image/report paths, and
idempotent teardown. The website must run the same science and safety gates as
the React notebook; simulation must be imported only in demo/test paths.

Both v4 notebooks must remain thin orchestration: no function/class or driver
implementation, no direct Leica API calls, explicit controller lifecycle, and
successful offline end-to-end execution. The removed calibration-validation
operator step must remain absent from the notebooks, status checklist, and web
flow while the standalone calibration module/tests remain usable.

Audit the complete generated browser UI as well: all six ESM modules, vendored
React isolation, light-theme contrast on light and black surfaces, object URL
lifetime, binary replay budgets, lasso/pan/hover/pick interactions, curation,
run status, multi-tab behavior, and zero external network dependencies.

## Validation to reproduce

Use Python 3.10 with the environment-declared notebook dependencies. The
corrected branch should report:

```text
pytest -q zmart_controller/tests workflows/target_acquisition/tests
329 passed
```

This includes two real-browser tests when Playwright and Chromium are present:
the complete operator demo and a deliberately blocked stale snapshot racing a
newer live `busy` event. Run the browser file at least three consecutive times.

The Leica driver's canonical unchanged offline gate should report:

```text
cd zmart_drivers/leica/stellaris5_y42h93/navigator_expert
python run_ci.py --mock
1030 passed, 1 expected CAM-DLL skip, about 83.2% coverage
```

Also run ruff check and format-check on every changed Python file,
`git diff --check`, parse both notebooks, syntax-check all six generated ESM
modules with Node, and confirm the page fetches no internet resource. The known
three whole-driver ruff-format warnings and retired workflow suite are
out-of-scope baseline debt.

## Deliverable

Report findings ordered blocker / major / minor / nit. Every finding requires
an exact `file:line`, concrete sequence, impact, why tests miss it, and the
smallest safe fix. Then provide a verified-correct section and residual risks
limited to real LAS X/smart-analysis deployment or behavior that genuinely
needs testing beyond local Chromium. If there are no findings, say so
explicitly; do not invent style work.
