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

## Testing, at prototyping pace

`tests/operator-page.spec.js` is a smoke net, not a specification: the layout
rules everything else rests on, plus one walk of the whole run. The page is
nearly all canvas, and driving it has repeatedly caught what reading the source
did not — a toolbar that reflowed and moved the canvas 47 px under the cursor
mid-click, one camera shared between two differently-sized canvases, collinear
points collapsing to a constant instead of a plane.

Deliberately not covered yet, because each costs a full run through the UI: the
focus model ladder (constant / plane / spline by geometry), the metric legend,
the drag override. Those want unit tests on the pure functions once the maths
stops moving and it is worth extracting them into their own modules.

## State of the code

`src/main.js` is still the prototype as one module — around 2100 lines. Splitting
it is the next structural job: the pure parts (surface fitting, sweep and peak
picking, the synthetic sample) come out first, then a panel per file, with a
small store so panels never import each other.
