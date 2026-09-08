# The focus step's Interrupt, and who orchestrates a run

Written 2026-09-08 on branch `claude/smart-operator-workflow-review-ehw3c5`.

## The complaint

Pressing **Interrupt** while the focus map is being measured does nothing
visible. On a one-point map it can never do anything at all.

## Why

The button is wired correctly end to end:

1. The page sets the button to "stopping…" and posts to
   `POST /api/focus/measure/stop` (`parts/microscope/live.js`).
2. The bridge sets `_stop_asked["focus"] = True` and returns
   (`framework/bridge.py`, `_stop_focus`).
3. The Python loop `measure_focus` in `parts/microscope/focus_run.py`
   receives that flag as `cancel()`.

The flag is read **once per point, before the drive** (line ~238). Drive,
the whole z-stack capture and the scoring of one point are a single
uninterruptible block. On the real stand a stack takes tens of seconds,
so a press looks ignored. With one point the flag is checked before point 1
and never again, so the run completes and the page treats it as a normal
finish.

The scan step and the target acquisition use the same between-fields flag
pattern. A field is quick, so it merely feels responsive there.

## Who runs the loop today

On the real stand the whole loop is Python, in a bridge worker thread that
holds the instrument lock for the duration. The page posts the point list
once and polls for progress.

There are two paths, and they disagree:

| Button              | Unit sent to the bridge | Where the loop runs | Interrupt lands   |
|---------------------|-------------------------|---------------------|-------------------|
| Run / Rerun         | the whole point list    | Python worker       | between points, via the flag |
| Run new points      | one point per request   | JS loop on the page | between points, in JS |

A single point is never interruptible once started, on either path.

## Assessment: the operator page should be the orchestrator

The one-point route already exists and "Run new points" uses it. The Run
button just bypasses it. Making every run go point by point gives:

- **One primitive in Python:** "measure this point". No list handling,
  no cancel flag, no worker-owns-the-run state to poll.
- **Interrupt for free:** the page simply stops sending the next point.
  The same applies to the scan and the target acquisition.
- **Order, retries, skipping, resume** all live in one place, in JS,
  next to the operator's state.

Cost: the stage lock is held per point instead of per run, and each point
pays one HTTP round trip (milliseconds against a stack of seconds).

What does not change: stopping **mid-stack** needs the driver's own abort of
a running acquisition, because the capture call blocks until LAS X reports
the stack done. That is needed under either design.

## Proposed work

1. Route Run and Rerun through the per-point path that "Run new points"
   already uses.
2. Delete the list-based focus worker, `_stop_asked["focus"]`, the
   `cancel` argument of `measure_focus`, and the polling for the worker.
3. Keep "stopping…" on the button until the point in flight has actually
   returned, then leave the step runnable again (not marked done).
4. Add a driver-level abort for a running acquisition, so a press lands
   mid-stack as well.
5. Apply the same shape to the scan and the target acquisition afterwards.
