# Handoff — operator page layout prototype

Paste this into a fresh session to pick the work up. It is written to be
self-contained: nothing in it depends on the conversation that produced the
prototype.

---

Continue work on the ZMART operator-page layout prototype.

## Where it is

- Clone: `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_main`
- Branch: `design/operator-page-prototype`, pushed to
  `github.com/thomdehoog/ZMART-microscopy` — **public repo**
- `git` is not on PATH: `C:\ProgramData\MinicondaZMB\Library\bin\git.exe`

**The live prototype is a Vite project at
`workflows/target_acquisition/webapp-ui/`.** Start there, and read its
`ARCHITECTURE.md` first — it states the layers, the contracts between them,
and honestly which parts are built versus still waiting.

```bash
E="C:/ProgramData/MinicondaZMB/envs/zmart-microscopy"     # node lives here
export PATH="$E:$PATH"
cd workflows/target_acquisition/webapp-ui
npm install
npm run dev        # http://127.0.0.1:5174, hot reload
npm run build      # one self-contained file -> ../workflow/webapp/static/
npm run test:unit  # vitest, ~0.2 s
npm run test:ui    # playwright, ~26 s
```

`docs/design/prototypes/operator-page-layout.html` is the **frozen snapshot**
of the design as it stood when it was one hand-authored file. It is not the
working copy and will drift; keep it or delete it, but do not edit it.

The real operator webapp this feeds is on `main` at
`workflows/target_acquisition/workflow/webapp/` (`_server`, `_page`, `_flow`,
`_host`). The prototype is **not** wired to it yet and should not pretend to be.

## What it is

A working mock of a proposed layout, driving a deterministic synthetic sample
(7×5 grid of 2662 µm tiles, ~1250 cells) so that every control does something.
It is a design artifact for arguing about shape before building.

## Design decisions already locked — do not relitigate without asking

1. Narrow left rail (260–320 px), **navigation only**: number, title, ✓, and the
   one-line result of each step. Workflow selector in a box above it.
2. **The step list is data.** Each workflow declares its steps: `id`, `n`,
   `title`, `why`, `btn`, `panels`, `mode`. Three workflows exist to prove it.
3. **The canvas is permanent** and holds **acquired data only** — tiles,
   detected cells, the gate, acquired targets. It is blank until the scan; that
   is correct, not an oversight.
4. **Every other tab belongs to the active step** and appears only while that
   step is selected. Clicking a step in the rail opens its tab.
5. **The run button lives in an action bar above the panel it operates**, never
   in the rail.
6. **Nothing auto-advances.** Completing a step leaves the operator where they
   are. The rail still gates order: only the next step is enabled.
7. **Simplicity is the priority.** Few options. Better to add an option later
   than to ship one that has to be removed. The base must stay clean.

## The two substantive panels

**Focus strategy** — its own tab, because planning is not acquired data. Shows
the position list as the microscope software reports it; the operator drops
focus points onto it. The model is chosen by geometry, matching
`workflows/target_acquisition/workflow/_focus_surface.py`: a flat sample or one
point gives a constant, four or more non-collinear points give a thin-plate
spline, anything else gives a least-squares plane. `SPLINE_SMOOTHING = 0.1`, so
the spline passes near the points rather than through them and the residual
still means something — the panel reports rms and names the worst point, which
is how a single autofocus that landed on dust gets caught.

Beneath it, the z-sweep for the selected point with **both sharpness metrics on
one plot** (Brenner and DCT, each normalised to its own maximum). The legend is
the control: click a metric to let it decide. A peak narrower than 4.5 µm is not
tissue and is not a candidate — rejected peaks stay drawn. Dragging the vertical
line overrules the pick, and the square preview beside the plot defocuses as you
drag, so a peak that was really a speck of debris becomes visible rather than
asserted. Colormap is viridis; the surface is a smooth field, not per-tile
blocks.

**Detection** — tune on one tile before running the sample. Cellpose or a plain
threshold, that algorithm's parameters, a tile stepper, and *Test on this tile*.
The step cannot run until it has been tested, and changing a parameter or moving
to another tile clears the test.

## How to test it

Drive it in a browser; do not just read it. Playwright lives in the `zmart-viz`
conda env, and AppLocker kills Chromium with `spawn UNKNOWN` unless the browsers
path is set to the whitelisted copy:

```bash
export PLAYWRIGHT_BROWSERS_PATH="C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright"
C:/ProgramData/MinicondaZMB/envs/zmart-viz/python.exe <script>.py
```

Write a small helper that clicks through the flow — nothing auto-advances, so
every step is an explicit click on the rail — assert on the readouts, capture
screenshots, and look at them. Three real defects were caught this way that
reading the code did not surface:

- a toolbar that reflowed to a taller row when its text changed, shifting the
  canvas 47 px under the cursor so clicks landed 0.89 mm from where they aimed;
- one shared camera between two differently-sized canvases, so a fit computed
  against one put the sample off the edge of the other and clicks near the edges
  silently missed;
- collinear points collapsing to a constant because the normal equations go
  singular where `np.linalg.lstsq` would still return a minimum-norm plane.

## Decisions taken, so they are not reopened by accident

**Widget extraction is deferred** (2026-07-29). The UI is still being designed;
a single file iterates faster for CSS and draw-function changes, and boundaries
drawn around a moving design get redrawn. Do it when a new widget appears or
when more than one person works on the page at once.

**Because of that, four facts are currently defined twice** — surface fitting,
the sweep and peak rules, the synthetic sample, and the workflow declarations
live both inline in `src/main.js` and in the modules beside it. `main.js` is
what runs; the modules are what the unit tests cover. **If you change a rule,
change it in both**, or do the de-duplication first: have `main.js` import them
and drop its runner's mode switch in favour of `step.run(ctx)`. That is a
contained change and does not touch any UI code. See `ARCHITECTURE.md`.

**Build served by Python** (2026-07-29). `vite-plugin-singlefile` inlines
everything into one `index.html`; the microscope PC never needs a toolchain.

## Open questions — ask before deciding

- Should the canvas show the planned tile grid faintly before the scan, or stay
  blank? Blank is what the "acquired data only" rule implies.
- A single click in the trace plot jumps the focus line; it is not drag-only. A
  stray click near the legend moves a measured height.
- The focus step requires ≥3 points, but `_focus_surface.py` accepts 1
  (constant).
- Two detection algorithms exist so the selector is meaningful; the smart-targets
  plan said Cellpose-only.
- The Playwright harness is not in the repo. Should it be?

## The north star — context only, explicitly out of scope

Eventually an agent should compose workflows: you talk to it and it assembles
the steps and the right-hand panels. That is why the step list and the panel
list are declarations rather than code.

The boundary to protect: **a workflow declares, the frame owns.** Declarations
get ids, titles, sentences, button labels, prerequisites, and which panels from
a **fixed registry**. The frame keeps the canvas projection, layer compositing,
selection state, the ordering guard, and every hardware call. An agent composing
from a registry is something you can let loose; an agent emitting widget code is
a different risk class.

**Decided (2026-07-29): build it with Vite.** The objection was that a
toolchain on an AppLocker'd microscope PC would not run. It does, provided the
toolchain and its `node_modules` live under `C:\ProgramData\MinicondaZMB\`,
which is whitelisted — install node/npm/vite from the MinicondaZMB envs rather
than into a user-writable path. Verify this before committing to it: install,
then actually start the dev server and load a page.

The real webapp today has no build step — React is vendored and modules are
served straight from Python at `/esm/<name>.mjs` — so moving to Vite is a change
to how the operator page is delivered, not just how the prototype is authored.
Worth deciding deliberately: whether the production page ships a Vite *build*
(static assets served by the existing Python server, no toolchain on the scope
PC at runtime) or whether the dev server is expected to run there too. The first
keeps the deployment story intact and is almost certainly what you want.

## Note on copies

A rendered copy also exists as a private Claude artifact. It and the repo file
are **independent copies**, not a synced pair. Treat the repo file as the source
of truth; publishing is a one-line step whenever a shareable link is wanted.

An artifact cannot make network requests (strict CSP) and must stay a single
self-contained file. Neither limit matters while the sample is synthetic; both
become blocking the moment the prototype wants real data from the webapp.
