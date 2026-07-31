# Testing the viewer

## The short version

From the `viz_studio` folder, one command runs everything:

```
python run_tests.py
```

That is all you need. It installs the test tools if they are missing, builds the
two pages the tests open — the viewer itself, and the small page the three
drawing options are compared on — and then runs every test. The first run takes a
few minutes (building those pages and, on a real machine, downloading the browser
the render tests drive); after that it is quick.

To test against a **real acquisition** as well, point it at an OME-Zarr store:

```
ZMART_TEST_STORE=/path/to/acquisition.ome.zarr python run_tests.py
```

Anything you add after the command goes straight to pytest, so you can run just
part of the suite while you work:

```
python run_tests.py -k omezarr     # only the OME-Zarr tests
python run_tests.py -v              # one line per test
python run_tests.py -s -k gpu       # print which GPU the renderer found
```

## What runs, and what skips

The suite is written so a plain machine stays green and a capable machine tests
more — nothing fails just because a piece is absent; it *skips* with a clear
reason. Three things decide what runs:

- **Always.** The data-reading tests (finding channels in a store, choosing a
  contrast window, serving chunks safely) need only Python with numpy and zarr.
  These run everywhere.
- **When the page is built, and a browser can be started.** The browser tests
  load the real viewer and check that pixels actually reach the renderer.
  `run_tests.py` builds the page for you; without Node.js they skip. They also
  need a Chromium, and the suite goes to some trouble to find one — see
  "Finding a browser this machine already has" below.
- **When a GPU / real data is present.** Two tests only make sense on a real
  machine, and live in `tests/test_gpu_realdata.py`:
  - `test_webgl_is_hardware_accelerated` — confirms a graphics card, not
    software, is drawing WebGL. It **skips** on a machine without one (you will
    see "software WebGL renderer … no GPU on this machine"), so it is quiet in
    CI and meaningful on the microscope PC. Run it with `-s` to print the exact
    GPU it found.
  - `test_real_store_channels_become_layers` and `test_real_store_renders` —
    open the store named by `ZMART_TEST_STORE`, and check that every channel in
    it becomes a layer and that the volume actually streams and renders. They
    **skip** unless that variable is set.

There is also a set of tests that run against a specific real mesoSPIM transfer
on the lab's network share (`tests/test_real_mesospim_data.py`). They skip
wherever that drive is not mounted, and run on the acquisition PC where it is.

## Finding the limit on how many positions a browser will carry

One test is left out of an ordinary run because it takes many minutes rather
than seconds. It is worth knowing about, because it measures the number the
viewer's safety margin is built on.

A folder of more than roughly six hundred and eighty positions used to draw only
part of the specimen and say nothing at all about the rest — the browser starts
refusing requests once too many are waiting, and a refused request looks to the
drawing engine like a position that cannot be read. The viewer now hands the
positions over in groups and lets each group finish, which keeps the queue short
enough that nothing is refused.

That protection is only as good as the size of a group, so two things guard it.
The ordinary run checks that the size the viewer ships with still leaves room
beneath the measured limit — that one is instant and it is what fails if somebody
raises the number. The measurement itself is opt-in:

```
ZMART_FIND_THE_LIMIT=1 python run_tests.py -s -k finds_the_limit
```

It turns the pacing off and opens folders of increasing size until positions
start going missing, narrowing down until it has the boundary, and then opens a
folder well past that limit with the pacing on to confirm every position still
arrives. The `-s` is worth having: it prints what it found at each step.

Run it when the browser is updated, when the viewer moves to a different drawing
engine, or when somebody wants to raise the group size.

**The answer depends on the machine, and by a lot.** Run on the sandbox this
project's tests are developed on, the browser carried four thousand positions
unpaced without losing a single one — the search never found a limit at all,
where the figure the viewer's margin is built on is six hundred and eighty. Both
numbers are real; they are simply different machines. So a run of this test tells
you about *that* machine, and the figure worth trusting for the lab is the one
measured on the acquisition PC. The margin the ordinary run checks against stays
at the smaller, more cautious number for exactly this reason: a viewer that is
safe on the slowest machine is safe everywhere.

## Finding a browser this machine already has

Playwright downloads its own Chromium and will only launch that one exact build.
That is usually fine, and it is why `run_tests.py` offers to fetch it for you. But
some machines cannot download one — a lab PC behind a policy that blocks it, or a
container that ships a browser of its own — and on those machines Playwright
refuses to start the perfectly good Chromium sitting right there, because its build
number is not the one it expected.

The consequence is worse than an error would be. Every test that looks at the
picture skips, and the run goes green having never drawn a pixel.

So before giving up, the suite looks for a Chromium the machine already has. It
searches wherever `PLAYWRIGHT_BROWSERS_PATH` points, and `/opt/pw-browsers`, and
takes the newest build it finds. No build number is written down anywhere, so this
keeps working as browsers are updated. Playwright's own browser is still tried
first, so nothing changes on an ordinary machine.

If that search picks the wrong one, or finds nothing on a machine you know has a
browser, name the one you want:

```
ZMART_CHROMIUM=/path/to/chrome python run_tests.py
```

Naming a file that does not exist means "there is no browser here", which is a
useful way to see for yourself what a browser-less machine gets.

## Making a run fail if it never looked at a picture

About a third of this suite opens a real browser and reads the pixels it drew —
199 tests of 554 when this was last counted, on 2026-07-31 — and that third is the
only part that catches the fault this project keeps meeting: a picture that is
silently absent, with every piece fetched, every layer built, and the engine
reporting itself perfectly content.

If no browser can be started, or the page was never built, all of those tests skip
— and the run would otherwise report the same comfortable green as one that looked
and was satisfied. On a laptop without Node that is exactly right; on a machine
that is *supposed* to draw, it is the suite quietly stopping doing the one thing it
is for.

Two things guard that, and the first applies everywhere. **Any** run in which the
picture was not looked at ends with a banner saying so:

```
================================ NO PICTURE WAS LOOKED AT ================================
199 tests that open a real browser and read the pixels it drew were skipped.
Why:
  - no usable Chromium on this machine: BrowserType.launch: Executable doesn't exist at …
…
```

The run is still green, because a plain checkout is allowed to be missing a
browser. But nobody can now read that green as "the viewer draws correctly", which
is the whole point.

The second is for machines that really should be able to draw — a CI runner, the
microscope PC. On those, set:

```
ZMART_REQUIRE_BROWSER=1 python run_tests.py
```

and a run where the pixel tests did not happen **fails**, saying why. The project's
own CI sets it, which is what makes that job mean anything. Leave it unset on a
plain checkout and the run still passes, banner and all.

Both halves are themselves tested, in `tests/test_the_run_says_when_it_never_drew.py`.
Those tests start a second pytest on a machine arranged to look as though it has no
browser at all, and check that the banner appears, that the plain run still passes,
and that the strict one fails. A safeguard nobody has watched work is only a
comment.

## Keeping an eye on whether the viewer still draws quickly

`tests/test_the_drawing_keeps_up.py` measures how much of its own drawing rate the
viewer keeps when ten times as many positions are open. It is a comparison rather
than a number, so it means the same thing on a laptop and on the microscope PC — if
the whole machine is slow, both halves are slow and the ratio does not move.

There are two tests in it and they say different things. One holds the line where
the viewer is today, so that a further slide is noticed. The other states the rate
that is actually wanted and is **expected to fail**, because the viewer pays a cost
per position on every frame and that is not fixed — `NEXT_STEPS.md` records the
cause and why the fix is an architectural change. The day somebody does fix it, that
test will start passing, the run will say so, and the marker should come off.

## Confirming the GPU is really being used

The clearest single check:

```
python run_tests.py -s -k hardware_accelerated
```

On a machine with a graphics card this prints the renderer, for example
`WebGL renderer: NVIDIA GeForce …`, and passes. On a machine without one it
skips and tells you it saw a software renderer. (For a second opinion outside
the tests, open `chrome://gpu` in the same browser and look for "Hardware
accelerated" next to WebGL2.)

## A note on speed

Where these tests are slow, it is almost always the **software** rendering path:
with no GPU, WebGL runs on the CPU, so the render tests take minutes rather than
seconds. That is a property of the machine, not the viewer — on hardware with a
graphics card the same tests, and the viewer itself, run far faster. The test
*results* (correct channels, safe serving, pixels reaching the renderer) hold on
any machine; only the *timings* change.

## Windows lab-PC setup (validated 2026-07-24)

On a managed Windows PC, AppLocker may block native tools downloaded beneath a
user profile or a temporary directory. Keep the Conda environment, Node build
tools, Playwright browser, and test checkout beneath an approved installation
directory. The setup validated on the ZMART workstation used:

```bat
conda activate ZMART-viewer
conda install -c conda-forge nodejs esbuild
npm install --global vite@7.0.0 esbuild@0.25.12
set PLAYWRIGHT_BROWSERS_PATH=C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\ms-playwright
playwright install chromium
```

The checkout used for browser tests was placed below the same environment:

```text
C:\ProgramData\MinicondaZMB\envs\ZMART-viewer\src\ZMART-microscopy
```

This matters because both Vite/esbuild and Playwright launch native
executables. A checkout under `C:\tmp`, a mapped network drive, or a browser
download under `%LOCALAPPDATA%` may install successfully but then fail with
`spawn UNKNOWN`.

Validation recorded on **2026-07-24 at 11:29 Europe/Zurich** against commit
`4ce2711`:

```text
140 passed, 2 skipped in 568.93s
```

The hardware-accelerated WebGL, interaction, layer-panel, render-acceptance,
synthetic OME-Zarr, network-share mesoSPIM, server, and path-safety tests all
passed. The only skipped tests required an explicit real acquisition through
`ZMART_TEST_STORE`.

## Seeing it for real

Testing aside, to actually look at a real acquisition through the viewer:

```
python run_demo.py --data /path/to/acquisition.ome.zarr
```

This opens the store through the neuroglancer engine, streaming it out-of-core,
in a native window (falling back to a browser). See `README.md` for the details.
