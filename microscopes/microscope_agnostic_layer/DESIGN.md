# Microscope-Agnostic Layer Design

This layer is the vendor-neutral interface between smart-microscopy workflows
and microscope-specific integrations.

Status: under construction. The Leica Navigator Expert driver is working and
hardware-tested; this layer is not yet the production API used by the workflow.

## Charter

The layer has **one aim**: provide a simplified abstraction over microscope
drivers, with no unnecessary complication, that workflows can build on. Nothing
more.

It earns its keep by being boring — it forwards intent and context to the driver
and returns what the driver gives back; the driver does the work. Two things
serve that single aim:

- **Provide the driver with context.** It holds the session context set up at
  connect time — reference objective, coordinate frame, available actuators and
  which are active — and feeds that context to the driver on every call, so the
  driver is never missing what it needs to interpret a command.
- **Keep the surface easy.** Set context once, get good defaults and discoverable
  options, then issue short domain-level calls. The user asks the session what is
  available instead of memorizing vendor strings.

The layer is *thin* not because it is dumb, but because a simplified, stable
abstraction is the whole point. Anything that requires knowing vendor semantics
lives **below** it (driver, calibration); anything that decides *what to do*
lives **above** it (workflows, guards, limits) — built on this surface.

```text
workflows / guards / limits      decide WHAT to do        (the smart part)
─────────────────────────────────────────────────────────────────────────
agnostic layer = CONTEXT          holds session context, feeds it down,
                                  exposes an easy, discoverable surface
─────────────────────────────────────────────────────────────────────────
vendor drivers + calibration      do the work, USING the context
```

There is a separate driver per microscope; each driver wraps its own vendor API
and owns the messy details (control software, logging, confirmation, calibration
math, what is mutable vs immutable).

## The Connector

`initialize()` is the **connector**: the single entry point that selects the
driver, opens the session, authenticates, and establishes the coordinate-frame
context. It returns a connected session handle that exposes the operations.

```python
connect(
    vendor,        # selects the driver, e.g. "leica"
    microscope,    # which instrument, e.g. "stellaris"
    api,           # which backend/transport, e.g. "pyapi"
    client,        # client/session identity
    password,      # auth                                    (no baked-in default)
    objective,     # reference objective, e.g. "10x"     ┐  define the absolute
    stage_type,    # reference actuator frame            ┘  coordinate frame
)  # -> session
```

Defaults are data-driven: a per-vendor profile supplies the common
`microscope` / `api` / `client` / `objective` / `stage_type` values, and caller
arguments are merged over it. The common path is therefore short, e.g.
`connect()` or `connect(vendor="leica")`.

The connector discovers all **standardized** selectable options once, at connect
time, and exposes them on the session as **options + current selection**.
Discovery of these is centralized here — nothing standardized is probed lazily
per call. (Flexible dicts are *not* part of this menu — see Methods; they are
fetched live by their `get` method.)

```python
session.capabilities == {
    "objective": {"options": ["10x", "20x", "40x"], "active": "10x"},
    "stages": {
        "x": {"options": ["motoric"],           "active": "motoric"},
        "y": {"options": ["motoric"],           "active": "motoric"},
        "z": {"options": ["motoric", "piezo"],  "active": "motoric"},
    },
    "save_format":    {"options": ["ome-tiff", "ome-zarr"], "active": "ome-tiff"},
    "save_procedure": {"options": [...],                    "active": ...},
    # ... same shape for api, etc.
}
```

This single structure is the one source of truth, and it drives the whole usage
pattern: **discover at init, put it back at call.** `active` is the default the
layer uses when the caller specifies nothing; `options` is the legal vocabulary
the caller reads and then passes straight back as an argument (the `stages`
selector on `get/setXYZ`, `format`/`procedure` on `save`, the objective, …). One
round-trip, one vocabulary.

## Coordinate System

This is the one concern the connector context is built to nail down. "Absolute
coordinates" only mean something once a reference frame is fixed, so the layer
pins three normally-conflated things apart:

- **The coordinate system you *speak* in** — always the motoric-stage frame. The
  single canonical absolute space. Galvo and piezo positions map into it.
- **The actuator that *executes* the move** — motoric, piezo, or galvo. Choosing
  the galvo does not change the coordinates you give; the galvo just realizes the
  target within its range.
- **The objective you *see* through** — 10x / 20x / 40x. The reference objective
  defines the baseline; others carry a known offset (parcentricity/parfocality)
  so a feature's absolute coordinate stays constant and the view still centers.

The win: the same physical point has the **same coordinates** regardless of which
actuator moves you there or which objective you are under.

```python
session.getXYZ()                            # positions, per active frame
session.setXYZ(x, y, z)                      # target in the motoric frame
session.setXYZ(x, y, z, stages={"z": "piezo"})  # realize Z via piezo; others default to active
```

The `stages` selector draws its keys/values from `capabilities["stages"]`. The
layer does **not** compute anything here: converting a motoric-frame target into a
galvo/piezo native command and applying the objective offset is **calibration
math owned by the driver**. The layer only carries the intent — *target in the
motoric frame, realize via this actuator, active objective is this* — down to the
driver.

## Methods

Every method is send/receive: the layer sends intent/context down to the driver
and receives the result up. It never acts or computes — even `setXYZ` and
`acquire` just forward the request and return what the driver gives back; the
move and the capture happen in the driver.

The two tiers therefore do not differ in behavior, only in **payload shape**:

- **Standardized** — *specific, named, typed parameters* (`x, y, z, stages,
  backlash_correction`, …) and structured results with explicit units. The layer
  commits to the signature and the shape.
- **Flexible** — a single generic **dict** in and out. The driver owns the shape;
  the layer promises nothing about the contents and interprets none of it.

**Standardized** — identical signature and semantics across every vendor:

- `getXYZ()` / `setXYZ()` — absolute positioning in the reference frame
  (see Coordinate System).
- `acquire(backlash_correction=True)` — acquire data and return a structured
  result. Kept simple. `backlash_correction` is acquisition-time intent: before
  the capture, the stage must settle via the right approach so the image is taken
  at the true position. It is an *acquisition* concern, not a move concern —
  `setXYZ` has no backlash notion. The driver runs the settle routine; the layer
  only passes the flag. Default on (trustworthy captures); turn off for speed.
- `save(format=..., procedure=..., name=None, position=None)` — persist the
  structured result. Kept simple. It has two selectable axes, both discoverable:
  `format` selects the output container (e.g. `"ome-tiff"`, `"ome-zarr"`) and
  `procedure` selects the saving procedure (how it writes — e.g. direct, tiled,
  compressed, target store). Each is drawn from a capability dict
  (`capabilities["save_format"]`, `capabilities["save_procedure"]`, options +
  active default), so omitting either uses the active one. `name` / `position`
  are optional context for the filename and embedded position/metadata — supplied
  when the workflow wants control over output naming, defaulted otherwise.

**Flexible** — pure send/receive conduits over **dictionaries**. The dicts are
opaque to the layer and meaningful only to the driver: `get` receives a dict from
the driver, `set` sends one to it. Whatever a dict means — run, define, restore —
is encoded in the dict and acted on by the driver; the layer just pipes it. No
interpretation, no processing.

Unlike the standardized options, flexible dicts are **not discovered at init**
and do **not** appear in `capabilities`. They are fetched live, on demand, by
calling the relevant `get` method — the driver produces the dict at call time.

- `getState()` / `setState()` — capture and reactivate instrument state. State
  splits into an **immutable** part (describes the instrument/config, not
  settable) and a **mutable** part (the settings that are captured and
  reapplied). The split *exists*, but **defining the line and enforcing it is the
  driver's job**: the driver returns its structured state, applies only what it
  deems mutable on `setState`, and validates reactivation against its own
  immutable fingerprint. The layer does not know the boundary.
- `getProcedure()` / `setProcedure()` — receive a procedure dict from the driver,
  send one to it. The layer does not know whether sending a procedure runs it,
  defines it, or stages it — that lives in the dict and the driver.
- `getInitialPositions()` — receive-only: a dict of the positions captured at the
  start, handed back for reactivation.

## Wiring

Drivers are Python-only, so the wiring uses Python's own dispatch rather than a
function-name lookup table.

### The driver tree is the registry

The driver directory mirrors the three `connect` axes, so the filesystem *is* the
registry — there is no separate registry file to keep in sync, and discovery of
*what exists* is just listing the tree:

```text
drivers / vendor / microscope / api-type /
          leica  / stellaris5-<id> / navigator-expert /
```

`connect(vendor, microscope, api)` resolves to a leaf. The filesystem answers
"what vendors/microscopes/apis exist"; `capabilities` (discovered at connect from
that leaf) answers "what this combination supports".

To avoid cloning a large, tested driver per instrument, the control code is
**shared** and the instance leaf is **thin**:

- **Shared control code** — the api/control-mode implementation (e.g.
  navigator-expert: moves, acquisition, state readers). Same for every instrument
  using that api. Lives once.
- **Thin instance leaf** — per-microscope profile *data*: capabilities, defaults,
  calibration reference, connection identity. Binds the shared driver to one
  instrument. A second Stellaris is a new thin leaf, not a new copy of the driver.

> Current repo is **not** organized this way yet (`drivers/vendor/leica/
> navigator_expert/`, no microscope tier). Reorganizing the tested driver into
> `vendor/microscope/api` is **deferred future work** — a careful move that keeps
> every test green, done separately from this design.

### Per-method wiring is the adapter

Each leaf supplies an adapter class implementing the agnostic `Protocol`. Each
agnostic method is a one-line method that calls the real driver function. This
*is* the per-method "config," expressed as code so Python (and the editor) checks
it: a wrong name or drifted argument is caught statically, not at runtime.

```python
class Microscope(Protocol):          # the agnostic contract
    capabilities: dict
    def setXYZ(self, x, y, z, stages=None) -> None: ...
    def acquire(self, backlash_correction=True) -> "Result": ...
    def save(self, format=None, procedure=None, name=None, position=None): ...
    def getState(self) -> dict: ...
    # ...

class LeicaNavigatorAdapter:         # per-method wiring + where context meets the driver
    def setXYZ(self, x, y, z, stages=None):
        self._drv.move_absolute(x, y, z, stages)
    def acquire(self, backlash_correction=True):
        return self._drv.snap(settle=backlash_correction)
```

The agnostic `setXYZ` does not look anything up — it *is* `adapter.setXYZ`. A
function-name-mapping config file would only earn its place if drivers were ever
out-of-process or non-Python; while they stay Python, the adapter wins on static
checking, debuggability, and editor support.

## Limits Are Out

Safety/policy limits are **not** part of this layer. They are vendor-neutral
config that lives outside it, consumed by a **guard above** the layer that checks
a target before it reaches the session. The layer never sees limits and does no
enforcement. (Hardware-intrinsic self-protection — e.g. refusing an
out-of-travel move — remains a correctness guarantee inside the driver, not a
config knob.)

## Design Rules

- Keep the public surface small and explicit; it carries context, it does not
  compute.
- Let drivers own everything vendor-specific: calibration math, confirmation,
  state mutability, source-specific evidence.
- Keep workflows free of vendor imports.
- Standardized tier returns structured results, not loose dictionaries; flexible
  tier deliberately passes raw vendor dicts and interprets nothing.
- Keep units explicit at the boundary.
- One vocabulary: discover via `capabilities`, reuse the same identifiers to
  drive.
- Add a method only when a workflow needs it and a vendor adapter can test it.

## Non-Goals

- Not a replacement for Micro-Manager or a hardware-device framework.
- Does not hide all vendor differences — the flexible tier is the deliberate
  escape hatch.
- Does not make untested microscope backends appear supported.
- Does not duplicate the driver's confirmation, calibration, or state machinery.

## Open Questions

Decisions reached in design discussion but not yet confirmed against an
implementation:

- **Connector output:** returns a session handle (assumed) vs. the connector
  *is* the handle. Returns-handle pairs naturally with an explicit `disconnect()`.
- **`password` resolution:** `None` default, resolved from env/secret (assumed) —
  never a baked-in credential.
- **`stages` granularity:** per-axis `{"x","y","z"}` (assumed) vs. grouped.
- **`getXYZ` return:** all stages by default, narrowable with a selector
  (assumed) vs. selector required.
- **Objective switching:** fixed per session, change = reconnect (assumed) vs.
  live-compensated within a session.
- **Connector teardown:** the session exposes an explicit `disconnect()`; whether
  any driver actually needs teardown is left to the driver.
- **Shared vs per-instance driver code:** the `vendor/microscope/api` tree assumes
  *shared* control code with *thin* per-instance leaves (profile data only). If a
  microscope ever needs genuinely different control logic, that becomes a shared
  base class or accepted duplication. (Driver reorg itself is deferred.)

## Acceptance Bar

The layer becomes production-ready only when:

- the target-acquisition workflow can run through it without importing the Leica
  driver directly;
- the Leica adapter passes the same offline and hardware gates as the direct
  driver path;
- the API is documented in the folder README;
- adding a second vendor would require a new adapter, not workflow rewrites.
