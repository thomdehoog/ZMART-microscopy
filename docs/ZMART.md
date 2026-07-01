# ZMART

**ZMB's Microscopy-Agnostic Research Toolkit** — a vendor-neutral framework for
smart, feedback-driven microscopy.

> Smart microscopy is a loop: look through the microscope, decide what is
> interesting, drive the next acquisition — automatically. ZMART is the toolkit
> that makes that loop run on *any* microscope.

## What ZMART is

One public API that workflows and users import. The microscope vendor lives
underneath, out of sight:

```python
import zmart

scope = zmart.connect()            # resolves the right vendor driver
zmart.acquire(...)                 # vendor-agnostic verbs
targets = zmart.select_targets(...)
```

- **Below `zmart`** — vendor drivers: `leica` (Stellaris / Navigator Expert),
  `nikon` (NIS-Elements), `evident` (FV4000), … each translating the agnostic
  verbs into that instrument's control layer. Users never import these.
- **`zmart` itself** — the vendor-neutral "waist": a stable verb vocabulary
  (connect, move, acquire, save, calibrate) plus the shared algorithms,
  calibration, and provenance.
- **Above** — workflows: target acquisition, calibration, analysis — written
  once, run on any supported scope.

## The one principle

**`zmart` is the brand surface.** The name only carries when it is the thing
people type. So the public, importable API is `zmart`; the vendor drivers are
plugins you register, never import directly. If a user's code says
`from leica…`, the boundary has leaked.

## Why the name

- It reads as **"smart"** to anyone — memorable, not parochial; it does not
  announce itself as an in-house tool.
- The **Z is ZMB.** Anyone who looks twice sees the origin — it credits the
  Center for Microscopy and Image Analysis, University of Zurich, without a logo.
- **The A is the point.** *Agnostic* is not just architecture hygiene, it is the
  distribution mechanism. A tool spreads outside ZMB only if it *runs* outside
  ZMB — on someone's Nikon, someone's Zeiss. Every vendor driver added is
  another institute that *can* adopt it, and every adoption drags the ZMB name
  into another lab's repos, papers, and talks. The branding ambition and the
  agnostic-layer work are the same bet.

This is how a core facility builds field-wide reputation: not by advertising,
but by shipping the thing everyone ends up importing. CellProfiler *is* the
Broad; napari, scanpy, and Fiji each carry their origin across the field every
time someone uses them.

## Status & sequencing

- **Name: staked** (here, and across the front-facing docs).
- **The `zmart` waist exists as `controller/`, still under construction.** It is
  the intended single workflow-facing surface, but workflows do not yet run
  through it (they use the Leica driver directly). The vendor-neutral verb
  contract is not frozen (see `docs/MIDLAYER_PLAN.md`). Drivers today: Leica
  (production-tested), Zeiss (MVP, offline-green), Nikon + Evident
  (investigation / spike).
- **The name is set; the code rename is deliberate.** The project is **ZMART
  Microscopy** (repo `ZMART-microscopy`). Physically renaming the repo, cutting
  the top-level `zmart` package (from `controller/`), and renaming the conda env
  is a deliberate pass — done *once the agnostic API is worth branding*, so we
  brand the surface people import (not the vendor internals) and never rename
  twice.
- **The order:** build the `zmart` waist so it is genuinely vendor-neutral → a
  couple of non-Leica examples so outsiders believe it → clean `import zmart` +
  install + docs → *then* the rebrand, and the name starts working in other
  people's code.

## The "R"

`R = Research`. It says plainly what the toolkit is *for* — the research
community — which is exactly the audience the brand needs to travel to. Chosen
over Reactive, Runtime, and Robotic: those name a property; **Research** names
the users.
