# Plan: the viewer becomes its own product

> Written 2026-08-26, after a day that renamed `viz_studio/` to `zmart-viewer/`,
> settled several design questions that had been open for weeks, and found two
> faults worth naming. This is the sequence from here to a repository of its
> own.

## The sentence the whole plan serves

**The viewer is pointed at a folder. It draws what's there, and if the folder
moves, the picture moves. That is all it does.**

Everything below either makes that true or makes it visible. Anything that does
neither is in "Not doing" at the end, with the reason.

## What the operator decided, 2026-08-26

These are settled and the plan does not reopen them.

| | decision |
|---|---|
| scope | The viewer, not an operator page. It may be embedded later; nothing is built for that now. |
| live vs finished | **The same case.** A folder is sometimes growing and sometimes stopped; the viewer never needs to know which. There are no two modes to build. |
| replay | A convenience, not a product feature. It leaves the viewer and becomes a script. |
| pointing | **Important.** Zero-copy reopening of a finished experiment is what it is for. Not dead, not going. |
| the four ways of finding bytes | plain, pointed-at, built, governed — all permanent. The goal is legible, not fewer. |
| the repository | `ZMART-viewer`, its own. |

## Phase 0 — landed today

- `viz_studio/` → `zmart-viewer/`; 429 files sorted by the question they answer;
  the root from ~70 entries to 12 (`1b828b28`)
- the demos find the built page again (`fed6f915`)
- a replay finishes its run; the axis box settled on one rule; the restructure's
  last stale paths (`e7538529`)

## Phase 1 — remove before rearranging

Nothing here is rearrangement. Every step deletes.

1. **Replay leaves the viewer.** *Measured 2026-08-26 and it is a chapter, not
   a step: ~400-500 lines removed across three layers (a tab in `App.jsx`,
   ~150 lines of `server.py`, `watchTheReplay` in `engine.js`, seven test
   files), plus 268 moved. Half a day with its gates, not an hour. Awaiting the
   operator's go with that number in hand.* `app/server/rehearsal.py` becomes `replay/`
   with a `__main__`. The Replay door goes, and with it three API routes
   (`replay`, `replay-status`, `replay-cancel`), ~132 lines of
   `app/server/server.py`, `_StoppedByTheOperator`'s replay arm, and — the
   point — the `LivePublisher` and `plan_the_writing` imports. `app/` stops
   being able to write. It becomes a more faithful rehearsal, not a worse one:
   driven from outside it goes through the same door a microscope would, which
   is exactly the shape `demos/show_thy1_one_source.py` already proves.
2. **`app/picture/server.py` merges into its one user.** ~~Moves beside~~ —
   **done 2026-08-26.** It was not a second viewer server but an instrumented
   one, and its ledger (pieces and milliseconds per level) is the point of it.
   Its only caller is `demos/serve_a_transfer.py`, which prints that ledger, so
   the server went *inside* it rather than beside it: one self-contained script
   of 219 lines, and the `import server` collision gone with the file.
3. **The orphans go.** `measure_a_transfer_scattered.py` and
   `measure_ten_thousand_overlapping.py` are referenced by nothing — no doc, no
   test, no script. **Needs the operator's yes before anything is deleted.**
4. **Re-measure `app/server/server.py`.** Phase 3 sizes are wrong until this
   runs.

**Gate:** full viewer suite.

## Phase 2 — unify

Each of these makes one thing where there are two.

1. **Knowing whether a source is still being written.** Today it is a `live=`
   flag passed at launch, read in about four places, deciding what the browser
   may keep. The server already asks the source directly on the same code path
   (`answer_from_a_live_run`, `server.py:479`). One server serving a running
   experiment *and* a finished one has to pick one answer for both today — which
   is precisely the "watch it, then open it again later" case.
   **Measure before touching.** Caching is where this project's worst faults
   live; a stale piece on screen is the exact failure the suite exists to catch.
2. **The shared test harness stops hiding.** `measure_a_governed_run_at_scale`
   is imported as `harness` by ~15 files and called at hundreds of sites;
   `measure_the_frame_rate_of_a_linked_view` gives `a_browser` and
   `BROWSER_ARGS` to 21. Both are libraries wearing a measurement's name. They
   move to `tests/harness.py` and `tests/driving.py` — the latter already
   exists for this job. Only the import lines change; the call sites keep their
   binding.
3. **The four ways of finding bytes sit together.** They stay four. They stop
   being scattered through a 2,731-line file, and each gets named for the case
   it serves rather than being called a "door" — a word with fourteen referents
   across this repo, covering HTTP routes, byte-finding branches and interface
   tabs indiscriminately.

**Gate:** full viewer suite, and for (1) a measured comparison of cold and warm
opens before and after.

## Phase 3 — split what is still big

Sizes below are today's; step 1.4 re-takes them.

| split | lines | kind |
|---|---|---|
| `App.jsx` → `LoadWindow.jsx` | 727 | **pure move** — props-driven component, cut at the function boundary |
| `LayerPanel.jsx` → `Histogram.jsx` | ~290 | **pure move** — the picture Auto acts on |
| `server.py` → `routes.py` + `opening.py` + `image_bytes.py` | 513 + 473 | **not a move.** One `_Handler` class; the pieces become plain functions taking what they need. ~1,336 lines remain behind. |

Do the two pure moves first. The third earns a review prompt before anything is
written — it is the only structural change in this plan that could be got wrong
quietly.

**Gate:** full suite, plus reading the browser screenshots. A panel passes every
assertion and still looks wrong.

## Phase 4 — ready for a repository of its own

The dependency arrow already points one way: nothing in `zmart_live` or
`zmart_storage` imports the viewer, only prose in docstrings refers to it.

1. **Promote the four fixtures.** Eight of the viewer's tests import
   `zmart_live.tests.test_coordinator` and `.test_gateway` for `FRAME`,
   `some_specimen`, `a_live_run`, `prepare_without_publishing`. A test suite
   importing another project's tests becomes "install their tests to run mine"
   across a repository boundary. They are fixture-builders, not tests: promote
   them into `zmart_live.fixtures`. **Not** copied into the viewer — a
   duplicated run-builder would drift from what the publisher actually writes.
2. **Declare the dependencies honestly.** `zmart_live` at **runtime** — a
   viewer that cannot follow a live run is pointless, and after Phase 1 it needs
   only the reader half (`gateway`, `live_state`, `omezarr`, `shardlink`).
   `zmart_storage` is **test-only**: zero imports in `app/`.
3. **One command to install.** Today running it means clone, venv, copy
   `node_modules`, two `npm run build`s, and set `PYTHONPATH`. That is a
   developer's checkout, not something handed to a colleague, and it is the
   difference between an instrument and a product.
4. **CI travels with it.** `.github/workflows/viewer.yml` already builds the
   page and runs the suite.
5. **The split.** `git subtree split` so history follows every file. **`parked/`
   stays behind** — 150 files of roads not taken, real history but not product.

**Gate:** a clone of the new repository, one install command, and the Thy1
spiral on screen.

## Phase 5 — the two faults that block the deferral

Independent of everything above, and worth more than any of it: about 13 seconds
off a 16-second publish at 12,769 positions, and a writer flat with scale.

1. **Auto goes dead on a live run.** Contrast measures a live picture through
   the LINKED view's members, and with the view deferred it is not there
   mid-run. It should follow the governed picture — which the live registry has
   served as the live source since 2026-08-12. Contrast never caught up with
   that move.
2. **Growth flickers.** "The lit canvas shrank while the spiral was landing."
   The fault `HANDOVER_the_flicker.md` exists for. Not understood.

Then flip `linked_view` to `"at_run_end"` and delete the paragraph on the
setting that explains why it is not the default.

**And one thing to write down now, before the real producer exists:** nothing on
a real live path calls `finish_the_run()`. Only the replay tool, one
measurement, and two tests. When the microscope-side producer is built it must
call it — or a finished experiment leaves no linked view, the zero-copy
reopening quietly does not happen, and **nothing says so**. The viewer will open
the run through the governed picture and draw it correctly. Guard it: either the
producer's contract makes the call mandatory, or the viewer says plainly when a
finished run has no linked view.

## Not doing, and why

| | why |
|---|---|
| splitting `governed.py`'s bake | 11 methods of `GovernedRun`; extracting them means inventing a `Bake` class. A redesign wearing a refactor's clothes. |
| splitting `engine.js` | 1,732 lines of which 996 are the prose explaining neuroglancer's traps. 659 lines of code. Leave it whole. |
| renaming `measure/measure_*.py` | cosmetic. 39 files renamed, every reference made stale, nothing works differently. |
| de-duplicating the measurements | each is frozen at the measurement it took. Sharing code makes old numbers unreproducible. |
| a dead-code hunt in `app/` | already screened: 87–99% coverage, two unreferenced symbols in the whole tree, zero `TODO`/`FIXME`. The weight is in the scaffolding. |
| regrouping `tests/` | 104 flat files; pytest does not care. |
| vendoring `zmart_live` into the viewer | it is the live path, not an inconvenience. |
| an abstraction between the viewer and the publisher | the boundary is already one-directional. Nothing needs it. |

## The order, in one line each

```
1  remove      replay out · the instrumented server home · orphans · re-measure
2  unify       live-from-source · the harness out of hiding · the four together
3  split       LoadWindow · Histogram · then server.py behind a review
4  repo        fixtures · dependencies · one-command install · CI · subtree
5  faults      contrast follows the governed picture · the flicker · flip
```

Phases 1–3 are reversible and inside today's repository. Phase 4 is the one-way
door. Phase 5 is independent and can start at any point.
