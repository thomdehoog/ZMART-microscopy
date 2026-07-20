# Consolidating the two widget editions of the v4 workflow

Status: proposed (not yet started). This document plans the work; nothing in
it has been implemented.

## The problem, in one paragraph

The interactive layer of the target-acquisition workflow exists twice. The
original edition draws its panels with matplotlib
(`workflow/_overview_widget.py`, `_discovery_widget.py`, `_focus_widget.py`,
`_acquisition_widget.py` — about 1,960 lines together) and drives the
`zmart_microscopy_v4.ipynb` notebook. The newer edition renders a React app
inside the notebook cell via anywidget (`workflow/react/_widgets.py` — 2,163
lines) and drives `zmart_microscopy_v4_react.ipynb` plus the browser
interface (`workflow/webapp/`, which builds on the React widgets). The
image math is shared — the React edition imports `composite_channels`,
`pair_images`, and friends from the matplotlib modules — but every stateful
*behavior* is implemented twice: what happens when you run autofocus, gate
cells, pick targets, acquire, and record verdicts.

## Why this needs fixing (evidence, not taste)

Two implementations that must stay in lock-step to be safe are already
drifting:

- The focus summary line reads "worst fit residual" in one edition
  (`_focus_widget.py:264`) and "largest fit residual" in the other
  (`react/_widgets.py:1060`). Harmless today; it shows edits land in one
  place and not the other.
- Error strings are byte-identical copies ("target count must be a positive
  whole number" appears verbatim in both editions), which only stays true
  until the next fix touches one copy.
- The duplication multiplies outward: 15 of the 27 notebook cells are
  byte-identical between the two v4 notebooks, there are two
  structural-guard test files, and the widget test surface is ~2,300 lines
  across five files.

Every behavioral bug found at the microscope must now be fixed twice, and a
fix applied to only one edition *looks* complete. For a codebase whose
stated bar is "as simple as possible, but very functional", this is the
single largest simplification available: roughly 3,000 lines.

## The options

### Option A — retire the matplotlib edition (recommended)

Delete the four matplotlib widget modules' *behavioral* classes, the
`zmart_microscopy_v4.ipynb` notebook, and their structural-guard tests.
Keep the pure image/geometry helpers those modules host today
(`composite_channels`, `pair_images`, ETA text, the channel palette) by
moving them into a small `workflow/_imaging.py` (they are already the shared
substrate the React edition imports).

Why this is the recommendation:

- The React edition is the strict superset: it powers both the notebook
  widgets and the website (`webapp/`), which is where operator use is
  heading anyway.
- Offline parity is already solved: the React runtime is vendored
  (`react/vendor/`, committed for microscope PCs without internet), so
  retiring matplotlib does not reintroduce a network dependency.
- The only extra requirement of the React edition over the matplotlib one
  is the `anywidget` package (its own docs say exactly this), which is
  already pinned in the environment and verified by `build_env.py`.

Cost: operators using the old `zmart_microscopy_v4.ipynb` must switch to
`zmart_microscopy_v4_react.ipynb` (the cells are mostly identical — 15 of
27 byte-for-byte). One session at the microscope to confirm the React
notebook covers the full run end to end is the gate for deleting anything.

### Option B — extract one headless controller, keep both faces

Pull the duplicated behavior into per-step controller classes with no
drawing code (focus run + cache + refit + invalidate-on-error; gate/pick
state; acquisition run + verdict recording + curation save), and make both
editions thin views over them. This is the classic fix when both frontends
must live.

Cost: a real refactor of ~4,100 lines into three layers, touching every
widget test; and afterwards the repo still carries two view layers, two
notebooks, and two test surfaces. Choose this only if there is a concrete
reason the matplotlib edition must survive (for example: a rig where
anywidget cannot run, or a strong operator preference discovered at the
microscope).

### Option C — status quo

Acceptable only short-term. The drift above shows the cost is already being
paid; every week adds interest.

## Recommended plan (Option A), in verifiable steps

1. **Confirm coverage at the rig** (the go/no-go gate): run one full v4
   session with `zmart_microscopy_v4_react.ipynb` — overview, focus,
   discovery/gating, acquisition, curation — and note anything the
   matplotlib notebook could do that the React one cannot. Nothing is
   deleted before this passes.
2. **Move the shared substrate**: relocate the pure helpers
   (`composite_channels`, `pair_images`, ETA/label text, `CHANNEL_COLORS`)
   from the `_*_widget.py` modules into `workflow/_imaging.py`; point the
   React edition and the webapp at it. While there, derive the React hex
   palette from the one matplotlib color table
   (`matplotlib.colors.to_hex` over `CHANNEL_COLORS`) so the palette exists
   once — today `react/_support.py` maintains a parallel hex copy by hand.
3. **Delete the matplotlib behavior layer**: the four widget classes, the
   old v4 notebook, its structural-guard test, and the matplotlib-specific
   widget tests. Port any test that pins *behavior* (not drawing) to the
   React controllers first — the drift examples above are exactly the
   assertions worth keeping.
4. **Sweep the docs**: the workflow README and the notebook markdown should
   name one notebook; remove the "future website front end" phrasing that
   still survives in `react/_widgets.py` and `react/__init__.py` (the
   website exists).
5. **Re-run everything**: the workflow suite, both notebook execution tests
   (now one), and one live simulated run (`simulate=True`) end to end.

Expected result: roughly −2,000 lines of production code, −1,000 lines of
tests, one notebook instead of two, and every future widget fix lands in
exactly one place.

## Risks and how the plan meets them

- **The React notebook misses a matplotlib-only affordance** → step 1 is a
  hard gate; nothing is deleted until a real session passes.
- **A behavior regression hides in the port** → step 3 ports the behavioral
  tests before deleting their subjects; the byte-identical error strings
  make good golden values.
- **An operator opens the old notebook from muscle memory** → leave a
  one-cell tombstone notebook for a release that says which notebook
  replaced it and why, then delete it the release after.
