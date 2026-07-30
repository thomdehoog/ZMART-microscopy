# webapp-ui

Front end for the target-acquisition operator page. Prototyping stage: it runs
against a synthetic sample and is not yet wired to
`workflow/webapp/_server.py`.

## Running it

Node lives in the project conda env, not on PATH. Everything must stay under
`C:\ProgramData\MinicondaZMB\` — AppLocker refuses to run executables from
user-writable paths, which is why `node_modules` and the Playwright browsers
live there too.

```bash
E="C:/ProgramData/MinicondaZMB/envs/zmart-microscopy"
export PATH="$E:$PATH"

npm install
npm run dev      # http://127.0.0.1:5174, hot reload on save
npm run build    # one self-contained file -> ../workflow/webapp/static/
npm test         # Playwright smoke suite, ~26 s
```

## Why a single-file build

`vite-plugin-singlefile` inlines the JS and CSS into one `index.html`. Three
reasons:

- The microscope PC has no toolchain and no network. The build happens on a
  developer machine; Python hands out the result.
- It is the shape `workflow/webapp/_page.py` already serves, so wiring it in
  later replaces a string rather than introducing an asset pipeline.
- One file can also be published as a Claude artifact when a shareable link is
  wanted.

`build.outDir` points at `../workflow/webapp/static/`, currently gitignored.
Whether the built file ships in the repo is decided when the page is wired up —
given the scope PC cannot build, it probably has to, the way `workflow/react/
vendor/` already ships built React.

## Watching a scan fill in

The scan step can show the overview being acquired rather than only counting it.
Give the page the address of a run and it draws that run's OME-Zarr images,
reading them again as tiles are written, so the picture fills in position by
position while the stage is still moving.

There is no microscope on a developer machine, so there is a stand-in that writes
a run exactly the way an acquisition does — through `zmart_storage`, the
project's own writer — and serves it over HTTP:

```bash
python ../live_overview_demo.py
```

It prints the address to open. Roughly:

```
http://127.0.0.1:5174/?overview=http://127.0.0.1:8788/overview.ome.zarr
```

Walk the page to **Scan the overview** and the picture appears where the plan
was. A few options are worth knowing:

- `--pattern scattered` images five places far apart and leaves the room between
  them unwritten, which is what imaging a handful of marked targets looks like on
  disk. `--planes 5` makes each position a small stack, and the canvas grows a
  slider for stepping through it.
- `--survey-underneath` writes a second acquisition: a finished low-power survey
  of the whole area, with the scan drawn over it. Add `&targets=…` to the address
  and the two are drawn as one picture — that is the shape a real run has, one
  image per acquisition type.
- `?ground=1e3a5f` paints the room the run declared underneath the picture, and
  `&seethrough=1` lets the dark parts of the image be see-through so that ground
  shows in the gaps.

**One thing to know about that last option.** Viv draws an image as a solid
rectangle covering everything the run declared room for, whether or not anything
was ever imaged into it — so by default a run that declared a whole carrier and
imaged five places in it hides everything underneath. `src/live/overview.js`
carries a dozen lines of shader code that make the dark parts see-through, which
is what lets the acquisition sit as a layer over the operator's own drawing. Its
one cost is that a place imaged and found empty then looks the same as a place
nobody has visited. Both behaviours are measured in
`tests/live-overview-sparse.spec.js`.

## Testing, at prototyping pace

`tests/operator-page.spec.js` is a smoke net, not a specification: the layout
rules everything else rests on, plus one walk of the whole run. The page is
nearly all canvas, and driving it has repeatedly caught what reading the source
did not — a toolbar that reflowed and moved the canvas 47 px under the cursor
mid-click, one camera shared between two differently-sized canvases, collinear
points collapsing to a constant instead of a plane.

`tests/live-overview*.spec.js` are a different kind of test and the reason
`tests/pixels.js` exists: they photograph the canvas and measure the photograph.
They assert that the lit part of the screen *rises* as tiles land, that a
scattered run draws its tiles in the right places and nothing between them, and
what happens to anything drawn underneath. Nothing is asserted about a loader
resolving or the console staying quiet — a viewer that reports itself perfectly
loaded while drawing nothing is the failure this project keeps meeting, and every
one of those checks passes while it does it. Setting
`LIVE_OVERVIEW_SABOTAGE=stalled` stops the demo run writing anything, which is
how to check that these tests can still go red.

Deliberately not covered yet, because each costs a full run through the UI: the
focus model ladder (constant / plane / spline by geometry), the metric legend,
the drag override. Those want unit tests on the pure functions once the maths
stops moving and it is worth extracting them into their own modules.

## State of the code

`src/main.js` is still the prototype as one module — around 2100 lines. Splitting
it is the next structural job: the pure parts (surface fitting, sweep and peak
picking, the synthetic sample) come out first, then a panel per file, with a
small store so panels never import each other.
