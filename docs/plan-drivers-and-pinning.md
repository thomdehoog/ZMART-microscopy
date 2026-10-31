# Plan: how the drivers are organised and pinned

*Status: agreed in outline with Thom on 31 October 2026: one repository, one branch per driver line, tags as pins, and ZMART Microscopy as the front page. Nothing has been changed yet; the questions at the end are still open.*

## In short

We have, or will have, drivers for several vendors (Leica, Nikon, ZEISS,
Evident, mesoSPIM). One vendor can have several microscopes, and those
microscopes can be driven through different software interfaces from the
vendor (we call these **APIs**: the way a program talks to the microscope
software, such as ZEN API or NIS-Elements 6.10).

We want three things at once:

1. Each microscope should run one exact, known version of its driver, so it
   does not change underneath us. This is what **pinning** means.
2. We should be able to update the driver for one microscope or one API
   without touching the others.
3. One main page should show, for every microscope, which driver and which
   version it runs, with a link to that exact version.

This plan proposes a structure that gives all three, without splitting into
many repositories.

## How it is today

ZMART drivers is a single package, `zmart-drivers`, with one version for
everything. Inside it, drivers are grouped by vendor:

```
zmart_drivers/
  leica/stellaris5_y42h93/navigator_expert/
  nikon/nis_elements_6_10/
  zeiss/zenapi/
  mesospim/
  evident/spike/            (an early try-out, not packaged)
```

A fix to the ZEISS driver therefore means a new version of every driver, and
a microscope cannot take that fix without also taking whatever changed for
Leica. ZMART drivers private follows the same layout for code that cannot be
published.

## Proposal

### 1. Pin with tags, not branches

A **branch** moves every time someone commits to it. A microscope pinned to a
branch can change without anyone deciding that it should. Long-lived branches
per vendor also drift apart, and a fix to shared code then has to be copied
into each branch by hand.

A **tag** is a fixed name for one exact commit. "This microscope runs
`zeiss-zenapi-v0.2.1`" means the same thing today and in two years.

So: one `main` branch, and a tag for every release of a driver.

### 2. Three levels, and only one of them is code

| Level | Example | What it is |
|---|---|---|
| Vendor | Leica, Nikon, ZEISS | a folder that groups drivers |
| Driver, one per API | ZEN API, NIS-Elements 6.10, Leica Navigator Expert | **code**, which is versioned and released |
| Microscope | the Stellaris 5 in Y42-H93 | **settings**: which driver at which version, and its limits, orientation and calibration |

A driver is written once per API, not once per microscope. Two microscopes
that use the same API share one driver; what differs between them is their
settings. This means `leica/stellaris5_y42h93/navigator_expert` would become
`leica/navigator_expert`, and what is particular to the Stellaris 5 in Y42-H93
moves to that microscope's settings (see section 5).

The controller already picks an instrument by its whole name, made of the
vendor, the microscope and the API. That name stays. What changes is where
the microscope part comes from: today it is the driver's folder, and after
this plan it comes from the microscope's settings, so one driver can appear
under the name of every microscope that uses it. Before anything moves, this
needs checking against how the controller reads a driver's name (for example
from the Leica driver's `zmart_driver.json`).

### 3. One repository, one package per driver

The thing we want to update on its own should be the thing that has its own
version. So each driver becomes its own small package, with its own version
and its own tags, while all of them stay in one repository:

```
ZMART-drivers/
  leica/navigator_expert/   pyproject.toml  →  zmart-driver-leica-navigator-expert
  nikon/nis_elements_6_10/  pyproject.toml  →  zmart-driver-nikon-nis-elements-6-10
  zeiss/zenapi/             pyproject.toml  →  zmart-driver-zeiss-zenapi
  mesospim/                 pyproject.toml  →  zmart-driver-mesospim
  shared/                   pyproject.toml  →  zmart-driver-shared   (only if the drivers share code)
```

Tags name the driver and its version, for example `zeiss-zenapi-v0.2.1` or
`leica-navigator-expert-v0.3.0`. pip can install one folder of a repository
at one tag:

```
zmart-driver-zeiss-zenapi @ git+https://github.com/thomdehoog/ZMART-drivers@zeiss-zenapi-v0.2.1#subdirectory=zeiss/zenapi
```

A fix to the ZEISS driver is then a new ZEISS tag. No other driver gets a new
version, and no other microscope changes.

### 4. One branch per driver line, so drivers can be worked on side by side

We want to work on several drivers at the same time without them getting in
each other's way, and without creating a repository for every driver. So
each driver gets its own **branch** in ZMART drivers, named after the vendor
and the API:

```
ZMART-drivers  (one repository)
  main                     what all drivers have in common, and the latest of each
  nikon/nis-6.10           only the Nikon NIS-Elements 6.10 folder changes here
  nikon/nis-6.20           a newer NIS-Elements version, if its driver differs
  zeiss/zen-api
  leica/navigator-expert
  mesospim
```

Every branch starts from `main` and holds all the drivers, but **only its
own driver changes on it**. This matters: because all branches share their
history with `main`, a fix to something the drivers have in common (shared
code, the documentation, the automatic tests) can be merged into every
branch. Branches that each held only one driver's files would share no
history, and every such fix would have to be copied by hand.

Branches follow **APIs**, not microscopes. Two microscopes that use
NIS-Elements 6.10 run the same code, so they share one branch; what differs
between them is their settings.

To have several drivers open at once, `git worktree` gives each branch its
own folder from a single copy of the repository, for example
`ZMART-drivers-zeiss/` and `ZMART-drivers-leica/` next to each other. Each can
be open in its own editor window or Claude session, without switching
branches.

**Branches and tags work together.** A branch is a line of work: it keeps
moving as fixes are made. A tag is a fixed point on that line, and it is
what a microscope runs. When a fix on `nikon/nis-6.10` has been tested, it is
tagged, for example `nikon-nis-6.10-v0.4.1`, and microscopes are moved to
that tag when we choose to.

### 5. The pins live in ZMART Microscopy, one folder per microscope

```
ZMART-microscopy/
  microscopes/
    leica-stellaris5-y42h93/
      requirements.txt      exact versions: the driver, the controller,
                            the interface, the viewer, the analysis engine
      limits/
      orientation/
      calibration/
    zeiss-.../
    nikon-.../
```

Upgrading one microscope is changing one line in its `requirements.txt` and
checking it at the microscope. Every other microscope keeps what it had.

The main page of ZMART Microscopy gets a table built from these folders. It
links each microscope both to what it runs and to where its driver is being
worked on:

| Microscope | Driver | Runs (tag) | Worked on (branch) | Controller contract |
|---|---|---|---|---|
| Leica Stellaris 5, Y42-H93 | Leica Navigator Expert | [`leica-navigator-expert-v0.3.0`](#) | [`leica/navigator-expert`](#) | 0.2 |
| ... | | | | |

A microscope that people do experiments on is always pinned to a **tag**, so
its driver only changes when someone decides it should. A test or
development microscope may instead follow a **branch**, so it picks up every
fix at its next install. That is where a fix is tried before it is tagged.

Both links open **the driver's own folder** on GitHub, not the top of the
repository, so the reader sees only that driver even though the repository
holds all of them:

- the pin opens the folder exactly as that microscope runs it, for example
  `https://github.com/thomdehoog/ZMART-drivers/tree/nikon-nis-6.10-v0.4.1/zmart_drivers/nikon/nis_elements_6_10`;
- the branch opens the same folder as it is now, with the latest fixes, for
  example
  `https://github.com/thomdehoog/ZMART-drivers/tree/nikon/nis-6.10/zmart_drivers/nikon/nis_elements_6_10`.

Each driver folder therefore needs a README written for the person who lands
there from the main page: which microscopes and which software version it is
for, how to install it, and how to work on it.

The mental model we explain to people is short:

1. **ZMART Microscopy is the front page.** It lists our microscopes and what
   each one runs.
2. **Click the pin** to see the exact driver on that microscope.
3. **Click the branch** to see where that driver is being worked on. If you
   are working on it, you commit there, and you change only that driver's
   folder. Something all drivers share is fixed on `main` and then merged
   into the driver branches.

### 6. Each driver says which controller contract it was written for

The controller defines a short list of commands (move, read the state,
acquire) and what each one must return. We call that list its **contract**.
Each driver states which version of the contract it follows, for example
`0.2`, and the controller refuses a driver that does not match. Today the
Nikon, ZEISS and mesoSPIM drivers still report `planes` as a count rather than
one entry per picture; with a stated contract version this becomes visible
instead of a quiet mismatch.

## When to split into more repositories

Not by vendor and not by driver alone: one repository with a package and a
branch per driver already lets each driver be worked on and versioned on its
own, without a large number of repositories to look after. A separate
repository earns its place only for a practical reason:

- **Access or licence.** Code built on a vendor's software that we may not
  publish. ZMART drivers private exists for exactly this, and it would use the
  same layout and the same kind of tags.
- **Different people look after it.** For example, a vendor or another
  facility maintains its own driver.
- **Testing needs the vendor's software installed**, and that is easier to
  arrange in a repository of its own.

## Steps

Each step leaves everything working.

1. ZMART drivers: give each driver folder its own `pyproject.toml` and
   version, and tag the current state of each one as its first release.
2. ZMART drivers: create one branch per driver line from `main`, and write
   down in the README how a fix moves from a branch, through a test
   microscope, to a tag.
3. ZMART drivers: move microscope-specific parts out of the driver folders
   (starting with `leica/stellaris5_y42h93`) into settings.
4. ZMART drivers: add the contract version to each driver, and have the
   controller check it.
5. ZMART drivers private: the same layout, branches and tags.
6. ZMART Microscopy: add `microscopes/` with one folder per real microscope,
   and teach `install.py` to install a microscope by name, for example
   `python install.py --microscope leica-stellaris5-y42h93`.
7. ZMART Microscopy: add the microscope table to the main page.

## Questions to decide

1. Which microscopes do we run today, and which API does each use? The plan
   needs real names in place of the examples above.
2. Do the drivers share code that would need its own `shared` package, or is
   each driver self-contained?
3. Do the limits, orientation and calibration of a microscope belong in
   ZMART Microscopy, as proposed here, or on the microscope's own computer
   only (for example because they are re-measured often)?
