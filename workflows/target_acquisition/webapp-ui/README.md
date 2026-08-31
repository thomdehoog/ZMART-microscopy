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
npm run build    # the page and two files beside it -> ../workflow/webapp/static/
npm test         # Playwright smoke suite, ~26 s
```

## What the build produces, and why it is three files rather than one

`npm run build` writes three files into `../workflow/webapp/static/`:

| file | what it is | how large |
| --- | --- | --- |
| `index.html` | the whole page — every script, every stylesheet, folded in | ~4 MB |
| `chunk_worker.bundle-*.js` | neuroglancer fetches pieces of image in this | ~0.9 MB |
| `async_computation.bundle.js` | neuroglancer unpacks them in this | ~1.6 MB |

Those three are what has to reach the microscope computer, and they have to stay
in one folder together. The page opens and draws with the two Viv engines
whether or not the other two came along; the third engine, neuroglancer, needs
them.

Everything is folded into the page for the same reasons it always was. The
microscope PC has no toolchain and no network, so the build happens on a
developer machine and Python hands out the result; it is close to the shape
`workflow/webapp/_page.py` already serves; and a page that is genuinely one file
can be published as a Claude artifact when a shareable link is wanted. That last
one is now true only of a build without neuroglancer in it.

### Why neuroglancer cannot be folded in

Neuroglancer hands two jobs to *background programs* — separate pieces of
JavaScript running alongside the page, so that fetching and unpacking pieces of
image does not freeze what the operator is looking at. A browser will only start
one of those from a file of its own.

Folding them into the page was tried properly before this was accepted, and it
failed twice over:

1. **The build tool will not compile them.** Neuroglancer ships each background
   program as a twenty-line list of imports written in a shorthand only a build
   tool can read. Vite does not read it: where neuroglancer asks for a background
   program, Vite copies the file across exactly as it found it. Folded into the
   page that way, the browser cannot make sense of it, the program never starts,
   and nothing reports an error — the description of a run loads and the picture
   never appears. The only place Vite will accept a compiled program is the file
   on disk inside `node_modules`, which is why `neuroglancer-workers.mjs` writes
   there; a plugin handing Vite the compiled program instead was tried and Vite
   never asked for it.
2. **Even compiled, it is too large to fold in.** A background program folded
   into a page stops being a file and becomes a very long address — about a
   third longer than the program itself, because of how it has to be written
   down — and Chromium refuses to start one from an address longer than about
   2 MB. Measured in this browser: a 1.5 MB program started, a 2 MB one did not,
   and the one that did not throw nothing, warn about nothing, and appear
   nowhere. It simply never ran. The two programs come to about 2.5 MB together,
   and they have to be folded together, because a folded program cannot look up
   a file beside itself and the fetching one starts the unpacking one that way.

So the page is folded into one file and the two background programs sit beside
it. `neuroglancer-workers.mjs` compiles them; `vite.config.js` places them.

### What that costs

Three things, and it is worth being honest about which of them actually matter.

**Copying a folder rather than a file.** This turns out to be very little. None
of the reasons for one file were about the copying: the microscope PC still does
not build anything, the files still arrive already built, and Python still hands
them out. A folder copies as easily as a file so long as it is copied *whole* —
which is the one new way to get this wrong, and why the build produces exactly
three files and `tests/viewer-built.spec.js` says so out loud.

**A build with neuroglancer in it can no longer be a Claude artifact.** That was
one of the three original reasons for a single file, and it is genuinely given
up. A page built without the third engine would still be one file, so this is a
choice that can be made per build rather than a door closed for good.

**Opened straight off the disk — a `file:///…` address, which double-clicking
the page does — the third engine cannot work.** A browser gives such a page no
address of its own and refuses to start a background program for it. The page
knows this and offers only the two engines that can draw, with a sentence in the
corner saying where the third went. Serve the folder over HTTP and all three are
there; `python dev_window.py --build` now does exactly that, which is also the
closer imitation of how the page will really be handed out.

`build.outDir` points at `../workflow/webapp/static/`, currently gitignored.
Whether the built files ship in the repo is decided when the page is wired up —
given the scope PC cannot build, they probably have to, the way `workflow/react/
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

## The canvas demonstration

The canvas is the picture of a run that an operator pans and zooms, and it is
being built separately, in `viz_studio/options/`, once for each of several
drawing engines and all of them behind one small interface. This page offers it
as a workflow of its own — **Canvas demonstration** in the chooser at the top
left.

**It is a bench, not a run.** No microscope moves, nothing is saved, and nothing
in it produces anything. It is there so that the canvas can be watched behaving
inside the real operator window before it is put to work in a workflow that
drives an instrument. It is deliberately not part of target acquisition: mixing
it in would mean every question about the picture became a question about the
acquisition going on around it.

Point it at a run the same way the scan step is pointed at one, and choose the
workflow:

```
http://127.0.0.1:5174/?overview=http://127.0.0.1:8788/overview.ome.zarr
```

### Two steps, and why there are two

The demonstration has two steps: **The picture drawn by Viv** and **The picture
drawn by neuroglancer**. They wait for nothing and share nothing — each opens its
own picture, in its own box, with its own engine and its own view — so you may go
to either one first, and whatever you do in one cannot reach the other. Looking
at the same scene in one and then the other is the only fair way to compare two
ways of drawing it.

The row of buttons above either picture chooses which engine draws it, and
changing engine keeps the view exactly where it is, which is the only way to see
a difference that is small. `?engine=viv-inside` opens both steps with one named
engine instead, which is how the built page is checked one engine at a time.
Dragging pans and the plain wheel zooms; nothing else moves the view.

### The three layers, and the buttons that turn them on and off

The picture an operator looks at is three drawings stacked one over the other,
and the second row of buttons turns each of them on and off. They are named from
the bottom of the stack upwards:

* **Beneath** — the operator's own drawing under the picture. In a real workflow
  this is the carrier and the positions still to be visited. You see it wherever
  the picture does not reach, so zoom out to see more of it.
* **Picture** — the acquisition itself, read from the run.
* **Above** — the operator's own drawing over the picture.

**The layer beneath is where the three engines genuinely differ, and the
demonstration shows it rather than explaining it.** Turn it on in the Viv step
and a wash of blue fills everything the picture does not cover; turn it on in the
neuroglancer step and nothing appears at all, because neuroglancer forces its
canvas opaque at the end of every frame and a drawing behind it is never seen.
Each engine answers that question about itself, and the page prints its answer
beside the button — so what you get is a reason rather than a button that seems
broken. Measured from a photograph, in `tests/viewer-workflow.spec.js`: about 92%
of the box under Viv, and 0% under neuroglancer.

### Turning the picture off, and the gap that turned up

Turning **Picture** off opens the canvas with no acquisition at all — the
operator's own drawing above and below and nothing in the middle. That is not an
idle case: it is what an operator sees before a run has started, laying positions
out on an empty plate.

**Two of the three engines do it and one does not.** `viv-under` and `viv-inside`
open with no acquisition in under a quarter of a second.
`neuroglancer-under` never finishes opening at all: it waits for the engine to
say what space the picture lives in, and with no image layers to read that from,
it never does. So the page gives every open a time limit, says plainly what
happened when the limit is reached, and puts the picture that was working back —
because a page that waited for ever would look exactly like one that was still
loading, which is the failure this project keeps meeting. That is a gap in the
interface rather than something for this page to fix, and it is written down in
`viz_studio/options/README.md`.

### What else is worth knowing

All three engines are here: `viv-under`, `viv-inside` and `neuroglancer-under`.
The first step opens on `viv-under` and the second on `neuroglancer-under`.

The third one is the fussy one, for the reason set out under *Why neuroglancer
cannot be folded in* above. In short: it needs two files sitting beside the page,
and it needs the page to have been served over HTTP. Both hold under `npm run
dev` and under a served build, and neither holds if the page is opened straight
off the disk — in which case the chooser offers two engines and says in the
corner where the third went, rather than offering a button that quietly draws
nothing.

Two limits are worth knowing while this is young. Only the first colour a run
recorded is drawn, in white, because the page has no way to ask the canvas what
colours the run holds; and the whole of the room the run declared is drawn rather
than only the part it has imaged, because the page does not yet hand over the
run's record of where it has been. `src/canvas/panel.js` says what each of those
would take to fix.

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

`tests/viewer-built.spec.js` is the only test that looks at the *built* page
rather than the development server, and it is worth knowing why one exists.
Everything else asks how the page behaves, and the development server serves the
same page. But the build rearranges what the browser is given — the page folded
into one file, neuroglancer's two background programs beside it — and that
rearrangement is exactly what the third engine is sensitive to. So this one runs
`npm run build`, checks that the three files it must produce are there and are
real compiled programs rather than the short lists neuroglancer ships, serves
them over HTTP and photographs each engine drawing, and then opens the same
folder straight off the disk and checks that the page offers only what can draw
there and says where the other went. Deleting either background program from the
output turns the picture completely black while the page still reports itself
perfectly content, which is what that test is for.

Deliberately not covered yet, because each costs a full run through the UI: the
focus model ladder (constant / plane / spline by geometry), the metric legend,
the drag override. Those want unit tests on the pure functions once the maths
stops moving and it is worth extracting them into their own modules.

## State of the code

`src/main.js` is still the prototype as one module — around 2100 lines. Splitting
it is the next structural job: the pure parts (surface fitting, sweep and peak
picking, the synthetic sample) come out first, then a panel per file, with a
small store so panels never import each other.
