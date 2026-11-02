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
| Driver: vendor / software / API type | Leica / LAS X / CAM API, ZEISS / ZEN / ZEN API | **code**, which is versioned and released |
| Microscope | the Stellaris 5 in Y42-H93 | what differs for this instrument and its test record (inside the driver, section 4), and which version it runs (the pin, section 6) |

A driver is written once per vendor software and API type, not once per
microscope. Two microscopes driven the same way share one driver, and what
differs between them is kept in a folder per microscope inside it. This
means `leica/stellaris5_y42h93/navigator_expert` would become
`leica/las_x/cam_api`, with the Stellaris 5 in Y42-H93 as one of its
microscope folders (see section 4).

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
  leica/las_x/cam_api/            pyproject.toml  →  zmart-driver-leica-las-x-cam-api
  leica/las_x/lcs/                pyproject.toml  →  zmart-driver-leica-las-x-lcs
  nikon/nis_elements_6_10/  pyproject.toml  →  zmart-driver-nikon-nis-elements-6-10
  zeiss/zenapi/             pyproject.toml  →  zmart-driver-zeiss-zenapi
  mesospim/                 pyproject.toml  →  zmart-driver-mesospim
  shared/                   pyproject.toml  →  zmart-driver-shared   (only if the drivers share code)
```

Tags name the driver and its version, for example `zeiss-zenapi-v0.2.1` or
`leica-cam-api-v0.3.0`. pip can install one folder of a repository
at one tag:

```
zmart-driver-zeiss-zenapi @ git+https://github.com/thomdehoog/ZMART-drivers@zeiss-zenapi-v0.2.1#subdirectory=zeiss/zenapi
```

A fix to the ZEISS driver is then a new ZEISS tag. No other driver gets a new
version, and no other microscope changes.

### 4. One branch per driver line, so drivers can be worked on side by side

We want to work on several drivers at the same time without them getting in
each other's way, and without creating a repository for every driver. So
each driver gets its own **branch** in ZMART drivers.

A driver is defined by three things, and its branch is named after them:
**vendor / software / API type**. The API type is the way a program talks
to the vendor's software.

The driver is named after the software and not after the hardware because
ZMART never talks to the microscope's hardware directly. It always talks to
the vendor's software (LAS X, ZEN, NIS-Elements), and that software drives
the hardware. So what decides how a driver must be written is the software
and the way it lets programs in, not the model of the microscope.

```
ZMART-drivers  (one repository)
  main                             what all drivers have in common, and the latest of each
  leica/las-x/cam-api              only the Leica driver through the CAM API (Navigator Expert) changes here
  leica/las-x/lcs                  the Leica driver through LAS X's hardware server, LCS (the classic Navigator)
  nikon/nis-elements/6.10
  nikon/nis-elements/7
  zeiss/zen/zen-api
  evident/cellsens-fv/rdk          later, once it is a real driver (today only a try-out)
```

For Leica, the API type is named after the connection the driver uses, like
every other driver here (decided with Thom on 2 November 2026; an earlier
draft named them after the LAS X windows). The two are separate drivers:

- **`cam-api`** drives LAS X through the **CAM API** of the Navigator Expert
  add-in. Operators know it as "Navigator Expert"; the driver's README says
  so.
- **`lcs`** drives LAS X through its hardware server, **LCS** (`LCS.EXE`),
  the same connection LAS X's own plain ("classic") Navigator window uses. It
  needs no add-in.

For Nikon, NIS-Elements 6.10 and 7 are also two separate drivers, because
the two versions let programs in differently and need different code.

The mesoSPIM driver is left out of this plan.

The Nikon examples further down use the shorter name `nikon/nis-6.10` for
`nikon/nis-elements/6.10`.

**Where each driver is today** (31 October 2026):

| Driver | Where it is | State |
|---|---|---|
| Leica LAS X, CAM API (Navigator Expert) | `main` of both driver repositories, at `leica/stellaris5_y42h93/navigator_expert` | working; most complete in ZMART drivers private |
| Leica LAS X, LCS (classic Navigator) | branch `claude/zmart-las-x-navigator-driver-jjxccf`, at `leica/stellaris/navigator` | beta `0.1.0b1`: its route passed 50 checks on the STELLARIS on 15 October 2026; the packaged driver is tested offline only |
| Nikon NIS-Elements 6.10 | `main`, at `nikon/nis_elements_6_10`, and branch `nikon-nis-elements-ar610` | working |
| Nikon NIS-Elements 7 | branch `claude/nikon-nis-elements-ar7-0.1.0a1`, at `nikon/nis_elements_ar7` | early alpha `0.1.0a1` |
| ZEISS ZEN API | `main`, at `zeiss/zenapi` | working |
| Evident cellSens-FV (RDK) | `evident/spike` only, for the FV4000 | a try-out; waits on Evident's real command reference |

Before the new branches are made, the existing branches need sorting out:
ZMART drivers has 31 and ZMART drivers private has 9, most of them left over
from earlier work. Each is either merged, kept as an archive, or deleted,
and that list is gone through together first.

Every branch starts from `main` and holds all the drivers, but **only its
own driver changes on it**. This matters: because all branches share their
history with `main`, a fix to something the drivers have in common (shared
code, the documentation, the automatic tests) can be merged into every
branch. Branches that each held only one driver's files would share no
history, and every such fix would have to be copied by hand.

Branches follow **the vendor's software and API type**, not microscopes.
Several microscopes can use one driver: for example, several Leica systems
that are all driven through LAS X's CAM API share the branch
`leica/las-x/cam-api`.

**Inside the driver: one folder per tested microscope.** A driver is tested
on the specific microscopes it is used on, and those microscopes can differ
slightly (other objectives, detectors or stage, or a setting that behaves
differently). So on its branch, the driver's folder holds the shared code and
one folder for each microscope it has been tested on:

```
branch leica/las-x/cam-api
  zmart_drivers/leica/las_x/cam_api/
    driver/                    the code shared by all these microscopes
    microscopes/
      stellaris5-y42h93/       what is different on this microscope, and its test record
      <second Leica system>/
      <third Leica system>/
```

Each microscope folder holds:

- **what is specific to that microscope for this driver**, such as its
  objectives, detectors or stage, or a setting that works differently there;
- **a short test record**: on which date it was tested, with which version
  of the vendor's software, and what the result was.

A published version of the driver therefore means: *this driver, tested on
these microscopes*, and anyone can see on GitHub exactly which instruments it
was checked on. If one microscope needs a small difference in code, that
code can start in its own folder. Only if the difference grows large does it
become a driver, and a branch, of its own.

What a microscope folder on the driver branch does **not** hold is the pin:
which version that microscope runs. The pin stays on the front page in ZMART
Microscopy (section 6), because it changes when we decide to move a
microscope to a newer version, and that should not count as a new version of
the driver.

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

**One branch holds many versions.** A branch keeps every state it has ever
been in, and each tag marks one of them. So one driver branch carries all the
published versions of that driver, and different microscopes can be pinned
to different versions on the same branch:

```
nikon/nis-6.10   ──●────────●────────●──────────●──────▶  (keeps moving)
                   │        │        │          │
                 v0.4.0   v0.4.1   v0.5.0     (newest, not yet tagged)
```

| Microscope | Pinned to |
|---|---|
| Nikon Ti2, room A | `nikon-nis-6.10-v0.4.1` |
| Nikon Ti2, room B | `nikon-nis-6.10-v0.5.0` |
| Nikon test system | `nikon/nis-6.10` (the branch, always the newest) |

A tag never moves and is never removed, so room A keeps running v0.4.1 until
someone deliberately moves it to v0.5.0.

**A new branch, or a new version?** Ordinary fixes and improvements are new
versions on the same branch. A new branch is started from `main` only when
the driver has to work in a fundamentally different way, which usually means
the vendor's software changed: for example a new NIS-Elements whose way of
talking to programs is different. Then `nikon/nis-6.20` starts beside
`nikon/nis-6.10`, and the microscopes still on 6.10 keep their branch and
their tags.

In one line: **a branch is one driver (vendor / software / API type), with a
folder for each microscope it is tested on; a tag is one published version of
it; the pin on the front page says which version each microscope runs.**

### 5. Publishing a version

This repository is where the drivers are published. Each tag becomes a
**GitHub Release**: a page for that version with a short note, written for
the person at the microscope, saying what changed and what it needs. For
example: "Fixes how the number of planes is reported. Needs NIS-Elements
6.10.02 or newer." The front page in ZMART Microscopy links to these pages.

Versions are numbered `vMAJOR.MINOR.FIX`, and each number tells the reader
how careful to be when moving a microscope to it:

- **FIX** goes up (v0.4.0 → v0.4.1) for a correction that changes nothing
  else. Moving a microscope to it should be safe.
- **MINOR** goes up (v0.4.1 → v0.5.0) when something new is added or
  behaviour changes in a way the operator may notice. Read the note first.
- **MAJOR** goes up (v0.5.0 → v1.0.0) when the driver is no longer
  interchangeable with the version before, for example because it follows a
  new version of the controller's contract. Check it on a test microscope
  first.

While a driver is still young its major number stays at 0, as it is for all
of them today.

### 6. The pins live in ZMART Microscopy, one folder per microscope

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
| Leica Stellaris 5, Y42-H93 | Leica LAS X, CAM API | [`leica-cam-api-v0.3.0`](#) | [`leica/las-x/cam-api`](#) | 0.2 |
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

### 7. Each driver says which controller contract it was written for

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
2. ZMART drivers: create one branch per driver from `main`, named
   vendor / software / API type, and write down in the README how a fix
   moves from a branch, through a test microscope, to a tag.
3. ZMART drivers: inside each driver, make one folder per tested microscope
   with what differs there and its test record, starting with the Leica
   driver (`leica/stellaris5_y42h93` becomes a microscope folder of
   `leica/las_x/cam_api`).
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
