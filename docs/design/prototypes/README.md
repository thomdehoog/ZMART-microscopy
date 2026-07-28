# Operator page layout prototype

`operator-page-layout.html` is a working mock of a proposed layout for the
target-acquisition operator page. Open it in any browser — it is one
self-contained file with no build step, no server and no network access, and it
drives a synthetic sample so every control does something.

It is a design artifact, not a component. Nothing here is wired to
`workflows/target_acquisition/workflow/webapp/`; the point is to argue about
shape before writing the real thing.

## What it proposes

**A narrow rail on the left, a wide working area on the right.** The rail is
navigation only — number, title, ✓, and the one-line result of each step. The
workflow selector sits above it, and choosing a workflow loads that workflow's
steps.

**The step list is data.** Each workflow declares its steps — id, number, title,
one sentence, button label, and which panels the step needs. The rail renders
that declaration, and an ordering guard would read the same one, so the flow
lives in a single place rather than being asserted separately by the page and
the server. Three workflows are included to show the difference: target
acquisition, overview only, and a focus surface check.

**The canvas is permanent; every other tab belongs to the active step.** The
canvas holds *acquired data* — tiles as the scan writes them, detected cells,
the gate, acquired targets — with real pan and zoom. Planning surfaces are not
data, so they are their own tabs and appear only while their step is selected.

**The run button lives with the thing it operates**, in an action bar above the
panel, not in the rail.

**Nothing advances by itself.** Completing a step marks it done and leaves the
operator where they were; the rail still gates the order, so only the next step
is enabled.

## The two panels worth looking at

**Focus strategy** shows the position list as the microscope software reports
it, and you drop focus points onto it. The model is chosen by geometry, matching
`workflows/target_acquisition/workflow/_focus_surface.py`: a flat sample or one
point gives a constant, four or more non-collinear points give a thin-plate
spline, anything else gives a least-squares plane. Smoothing is 0.1, so the
spline passes near the points rather than through them and the residual still
means something — the panel reports rms and names the worst point, which is how
a single autofocus that landed on dust gets caught.

Beneath it, the sweep behind the selected point is drawn with both sharpness
metrics on one plot (Brenner and DCT, each normalised to its own maximum). The
legend is the control: click a metric to let it decide. A peak narrower than
4.5 µm is not tissue and is not a candidate — rejected peaks stay drawn so you
can see what was turned down. Dragging the vertical line overrules the pick, and
the preview beside the plot defocuses as you drag, so a peak that was really a
speck of debris is visible rather than asserted.

**Detection** tunes the algorithm on a single tile before running the sample.
Choose Cellpose or a plain threshold, set its parameters, step to whichever tile
you want, and test — found objects get label colours, rejected ones stay dim.
The step cannot run until it has been tested, and changing a parameter or moving
to another tile clears the test.

## What is fake

The sample, the microscope and the analysis. Positions are a 7×5 grid of 2662 µm
tiles (2048 px at 1.30 µm/px, a 5× overview), the tissue is a handful of
gaussian blobs, and ~1250 synthetic cells carry an area and an intensity. Focus
sweeps are generated per point, with debris added at 45% of positions because
that is the failure the panel exists to catch. Everything is deterministic, so
the mock looks the same on every load.
