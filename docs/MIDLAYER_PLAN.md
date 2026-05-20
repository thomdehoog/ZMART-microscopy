# SMART Mid Layer — Implementation Plan

A vendor-neutral layer ("the waist") between workflow scripts and vendor driver
code.

**This is foundation work.** Every microscope automation built on top will
inherit its shape, so the design is sized for longevity: a small, coherent
surface chosen by *cutting* — not accumulated by patches or workarounds;
**internally consistent in style and structure throughout**; behaviour you can
hold in your head and find in the source in seconds; extension by *adding* to
the contract rather than reworking it; tests and a phase plan that take it from
first commit to a production hardware run; documentation that is the spec on
disk. The plan is written to be shipped now and maintained later by people who
weren't in the room when it was designed.

- **Status:** v0.7 — built and polished. Phase 1 is implemented (eight polish
  rounds on branch `feat/mid-layer`); this revision consolidates Gap #1
  (timeout ownership moves to the adapter) and Gap #15 (synchronous-blocking
  codified) from the live `docs/PHASE_1_GAPS.md`. 12-method flat surface,
  symmetric naming, surface unchanged from v0.5.
- **Target world:** imaging facilities running **proprietary control suites**
  (LAS X, ZEN, NIS-Elements, cellSens, SlideBook). Each suite owns its
  microscope and exposes a scripting API; SMART drives whichever one you have
  through a uniform contract. This is a *different* problem from Micro-Manager
  (which builds microscopes from device parts); the mid layer is shaped for
  facility-mode reality, not MMCore-style device assembly.
- **Backend reference:** branch `try/all-four`. The v6 Leica driver under
  `controller/vendor/leica/navigator_expert/driver/` is **frozen** — the
  adapter wraps it, never edits it.
- **v1 scope is deliberately narrow** — see §8.

---

## 1. The idea

Today the workflow imports the Leica driver directly. No vendor-neutral seam
exists; a second vendor would mean rewriting the workflow. The fix is a small
contract — **the waist** — that workflow imports instead.

```
   notebook        thin: markdown + a few calls
   workflow        orchestration, domain logic
   ── THE WAIST ──  12 methods, vendor-neutral        ← this plan
   adapter         implements the waist for ONE vendor plug-in
   driver          frozen vendor API
```

**The one rule:** nothing above the waist imports a vendor package. Workflow
imports `controller.microscope` and nothing else hardware-related.

The waist has two faces: **`Microscope`** (what workflow calls — the 12 methods)
and **`MicroscopeAdapter`** (the ABC a plug-in implements — the single plug
point). A plug-in is *one implementation of one vendor's control*
(`navigator_expert` is one Leica plug-in). The waist names no vendor; the
plug-in is selected at construction by a string id, resolved through an explicit
registry — no import-magic.

---

## 2. The contract

### 2.1 The 12 methods

```python
# session
scope.initialize()                              # connect, read hardware, set up session

# stage
scope.getxyz()                  -> Position     # live (x, y, z) in the declared frame
scope.setxyz(x, y, z=None, *, timeout=...)      # move the stage; validated against active limits

# named acquisition state
scope.getstate(name)            -> Preset       # read a named state from the scope
scope.setstate(preset, *, timeout=...)          # apply preset.fields; name is identity, not a lookup key

# named stage-limits bundle
scope.getlimits(name)           -> Preset       # read named limits
scope.setlimits(preset)                         # apply as active guard; every setxyz is validated

# named positions (read-only in v1)
scope.getposition(name)         -> Positions    # list of XYZ targets

# acquisition lifecycle
scope.acquire(*, timeout=...)   -> ImageHandle  # acquires whatever was last setstate'd (one plane)
scope.save(handle, experiment, lineage=None)    # writes canonical OME-TIFF + sidecar; mutates handle.path
scope.release(handle)                           # free in-memory pixels

# discovery
scope.capabilities()            -> frozenset[Capability]
```

Twelve methods, flat, discoverable via `dir(scope)`. **`set*` means "make the
scope have this thing"** — same mental model whether it's a stage position,
acquisition state, or limits. Time-cost and failure are universal across all
set-verbs; the name doesn't encode them.

Workflow uses only these 12. There is no `scope.vendor.*` escape hatch — vendor
names never appear in workflow code; vendor-specific workarounds live in the
adapter where they belong.

**Every method is synchronous.** When a call returns, the requested operation
is done; on runtime hardware failure it raises `MicroscopeError`. Workflow code
can rely on the next line meaning *"the previous op completed."* Timeout
exhaustion is failure, not return — never a silent half-done state. This
applies to every method on the waist; misuse (wrong preset type, unknown
plug-in id, etc.) raises `ValueError`/`TypeError` per §2.2 and §4.

**Notes on a few methods:**

- `acquire()` fires a **single plane** in v1. The currently-applied state must
  be shaped to produce one (c, z, t) call; a state that would produce a
  multi-plane result raises `FAILED` rather than being silently collapsed. Stacks
  and multi-channel runs are workflow loops over `setstate` + `acquire`.
- `save(handle, experiment, lineage=None)` writes the canonical layout and
  then **mutates `handle.path`** to the written file. After a successful return
  the handle itself is the source of truth for "where this image was saved."
- `lineage` is a flat vendor-neutral dict carrying provenance — e.g.
  `{"parent_image": "tile_3_4", "row": 2, "col": 5}` — attached to the saved
  metadata. Schema is open and workflow-defined; the waist treats it as opaque
  data and persists it verbatim.

### 2.2 Failure

Every method that touches hardware raises `MicroscopeError` on failure. Success
paths return their typed result directly (`Position`, `Preset`, `ImageHandle`,
or `None`) — `Verdict` only exists *attached to an exception*, so the enum has
no `OK` value.

```python
class Status(Enum):
    FAILED         = "failed"
    TRANSIENT      = "transient"
    NEEDS_OPERATOR = "needs_operator"

@dataclass(frozen=True)
class Verdict:
    status:      Status
    confirmed:   bool | None = None    # readback within tolerance; None = unverifiable
    retry_after: float | None = None   # transient: minimum backoff in seconds
    message:     str = ""              # human-readable; never branched on

class MicroscopeError(Exception):
    def __init__(self, verdict: Verdict):
        super().__init__(verdict.message)
        self.verdict = verdict
```

Rules, total and minimal:

- All failure raises `MicroscopeError`. Workflow branches on `verdict.status` —
  never on `message`.
- `TRANSIENT` carries `retry_after`; workflow defers to it.
- **Partial `setstate`**: raises `FAILED`; the adapter re-reads the scope state
  so a subsequent `getstate` reflects physical truth, and `message` reports
  what was applied.
- **Limits-guard rejection** (a `setxyz` outside the active `limits`) raises
  `FAILED` with a message naming the violated axis, *in the shell, before the
  adapter is called*.
- **`NEEDS_OPERATOR` is predictive.** Before issuing a call known to block on a
  physical action, the adapter raises with a message describing the required
  action. The adapter detects such cases from the `setstate` diff against
  hardware info (e.g. a slot change to a manually-actuated objective). Reactive
  recovery from a stuck blocking call is not in v1.
- **Timeout is a failure threshold, not cancellation.** The adapter raises
  `TRANSIENT` (or `FAILED`) once the vendor operation has returned, or once
  idle has been observed — never while a native call is mid-flight. v1 has no
  mid-call cancellation (§8). The "leave the instrument idle on timeout" rule
  in §4 applies only after the vendor call has yielded control.
- **Session degradation** is contained inside the adapter: it settles after any
  operation known to perturb the vendor session before returning. Subsequent
  unrelated methods never inherit a degraded session. The vendor-specific
  conditions (e.g. LAS X behaviour after LRP writes — §6) are adapter detail.

### 2.3 Data shapes

All shapes the methods exchange:

```python
class Capability(Enum):
    HARDWARE_AUTOFOCUS = "hardware_autofocus"
    CONTINUOUS_FOCUS   = "continuous_focus"
    POSITION_READOUT   = "position_readout"
    # vocabulary grows when the second adapter forces real distinctions

class PresetType(Enum):
    STATE  = "state"
    LIMITS = "limits"

@dataclass
class Position:
    x: float                           # absolute stage micrometres in the declared frame
    y: float                           # absolute stage micrometres in the declared frame
    z: float | None = None             # focus-drive micrometres; None only as an input to setxyz

@dataclass
class Positions:
    name:   str
    points: list[Position]

@dataclass
class Preset:
    name:   str
    type:   PresetType                 # the adapter knows the schema from this
    fields: dict[str, Any]             # plain JSON-shaped dict with stable top-level keys;
                                       # values may be nested containers matching the schema

@dataclass
class ImageHandle:                     # one plane per acquire
    pixels:  "ndarray"
    indices: dict[str, int]            # {"c": 0, "z": 12, "t": 0}
    ome_xml: str                       # OME metadata, as written
    path:    Path | None = None        # None until save() returns; then the canonical path
```

Multi-channel z-stacks are workflow loops yielding N handles — matches v6's
one-file-per-call output.

---

## 3. Using it

```python
from controller.microscope import Microscope

scope = Microscope("leica.navigator_expert")
scope.initialize()

# populate the three states (operator configured them as named jobs in the vendor suite)
overview = scope.getstate("overview-scan")
highres  = scope.getstate("highres-scan")
stack    = scope.getstate("highres-stack")

# limits and positions
scope.setlimits(scope.getlimits("safe-area"))
tiles = scope.getposition("overview-tiles")

# execute the plan
for step in plan:
    scope.setxyz(step.x, step.y, step.z)
    scope.setstate(step.state)
    img = scope.acquire()
    scope.save(img, experiment="run_2026_05_20", lineage={"parent_image": step.parent})
    scope.release(img)
```

The plan reads line-by-line: move → apply → acquire → save → release.

---

## 4. The `MicroscopeAdapter` ABC

The down-face mirrors the up-face — same names, same semantics. **`z=None`
on `setxyz` and `lineage=None` on `save` are shell-resolved caller semantics.**
`timeout=` is the caller's override channel — the shell passes it through
unchanged; `None` signals the adapter to apply its own implementation-specific
default.

```python
class MicroscopeAdapter(ABC):
    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def getxyz(self) -> Position: ...
    @abstractmethod
    def setxyz(self, x: float, y: float, z: float | None, *, timeout: float | None) -> None: ...

    @abstractmethod
    def getstate(self, name: str) -> Preset: ...
    @abstractmethod
    def setstate(self, preset: Preset, *, timeout: float | None) -> None: ...

    @abstractmethod
    def getlimits(self, name: str) -> Preset: ...
    @abstractmethod
    def setlimits(self, preset: Preset) -> None: ...

    @abstractmethod
    def getposition(self, name: str) -> Positions: ...

    @abstractmethod
    def acquire(self, *, timeout: float | None) -> ImageHandle: ...
    @abstractmethod
    def save(self, handle: ImageHandle, experiment: str, lineage: dict | None) -> None: ...
    @abstractmethod
    def release(self, handle: ImageHandle) -> None: ...

    @abstractmethod
    def capabilities(self) -> frozenset[Capability]: ...
```

The adapter is stateful — it owns the vendor session, the current job, the
last-applied state (for diffs in `setstate`), and any run-lifecycle objects
(the v6 `RunHandle` for Leica). **Every method is synchronous: it returns
only after the requested operation has completed, or raises.** When a hardware
operation was started, the adapter leaves the instrument idle before raising
(§2.2). Timeout exhaustion is failure, not return — never a silent half-done
state.

The plug-in registry is one line per plug-in (explicit registration, no
`pkgutil` import-magic):

```python
# controller/microscope/__init__.py
_PLUGINS = {
    "leica.navigator_expert":
        "controller.vendor.leica.navigator_expert.adapter:NavigatorExpertAdapter",
}
```

`Microscope("leica.navigator_expert")` looks up the id, imports lazily,
instantiates.

---

## 5. Package layout

```
controller/
├── microscope/                 ← THE WAIST — vendor-neutral, names no vendor
│   ├── __init__.py             ← Microscope factory + plug-in registry
│   ├── microscope.py           ← the 12-method shell + limits guard
│   ├── adapter.py              ← MicroscopeAdapter ABC
│   └── types.py                ← Status, Capability, PresetType, Verdict, MicroscopeError,
│                                  Position, Positions, Preset, ImageHandle
├── transform/                  ← registration / objective math (vendor-neutral)
├── workflow/                   ← Phase-3 target (relocated from the plug-in)
└── vendor/
    ├── _shared/output_layout/  ← EXISTS — canonical naming (used by adapters)
    └── leica/navigator_expert/
        ├── adapter.py          ← NavigatorExpertAdapter
        ├── connect.py          ← connect() returning a v6 client
        ├── templates.py        ← LRP machinery, moved down from workflow (§6)
        └── driver/             ← EXISTS — v6 driver, FROZEN
```

Four files in the waist. Three files in the plug-in, plus the frozen driver.

---

## 6. The Leica backend

`NavigatorExpertAdapter` is new code wrapping the frozen v6 driver. The shell's
limits-guard enforces `setxyz` against the active `LIMITS` preset *before* the
adapter is called; the adapter does not duplicate that check. Verb-coverage
audit of today's workflow (currently at
`controller/vendor/leica/navigator_expert/notebooks/workflow/`):

| Class | What | Where |
|-------|------|-------|
| Covered by a method | `move_xy_with_backlash`, `move_z`, `get_xy` + `read_zwide_um`, `get_job_settings` + `make_changeable_copy`, `acquire_frame`, `select_job`, `set_stage_limits` | the 12 methods |
| Leica-internal — moves DOWN | `save_experiment`, `strip_template`, `restore_template`, `parse_lrp`, `lrp_*`, `find_scanning_templates_dir`, `parse_template_positions`, `synthesize_tiles` (only if no operator-defined tiles) | `navigator_expert/templates.py` |
| Adapter session state | `start_run` (lazy, keyed by `experiment`), the resulting `RunHandle`, the last-applied state cache for diffs | inside `NavigatorExpertAdapter` |
| Not called above the driver in v1 | `acquire_and_save` (deliberately bypassed — adapter calls `acquire_frame` instead so save can stay a separate verb) | n/a |
| Pure / neutral — stays UP | `translate_xyz_between_objectives`, `load_calibration` | `controller/transform/` + workflow |

**Three areas of new adapter code:**

1. **State diff / apply engine.** v6 has no `diff_settings`/`apply_job_changes`
   — only per-knob `set_*` and the LRP-editing `lrp_set_*` family. The engine
   diffs `setstate` against a cached last-applied state and routes each field
   per a static table to either the live `set_*` path or the LRP
   strip/edit/restore path. STATE.md documents an LAS X "wedge" after heavy LRP
   writes — *this* is where the universal "session degradation contained in
   adapter" rule (§2.2) becomes concrete: the adapter settles after each LRP
   batch (re-`ping` until idle) before returning. `NEEDS_OPERATOR` prediction
   lives here: an objective-slot change in the `setstate` diff is checked
   against `get_hardware_info` for a manually-actuated slot before the LAS X
   call is issued.

2. **LRP template machinery** (`templates.py`). Relocated from the workflow
   tree (`notebooks/workflow/`) into the plug-in, driven inside `setstate` /
   `acquire`.

3. **Acquire / save split + `ImageHandle` assembly + run lifecycle.** On first
   `save(...)` for a given `experiment`, the adapter calls `start_run(client,
   experiment)` and holds the resulting `RunHandle` (one per experiment,
   reused). `acquire()` calls `acquire_frame` (gets the array and the LAS X
   export file path), then reads the **companion OME-XML sidecar** — the v6
   driver writes one at `<experiment_dir>/metadata/<image>.ome.xml` (driver
   helper `_find_companion_xml` documents the location). The adapter assembles
   the `ImageHandle`. On `save()`, the adapter derives a `Naming` (from
   `handle.indices` + the current state name as `acquisition_type` + any slot
   overrides on the `output` preset bundle if used) and writes the canonical
   layout via `_shared/output_layout`, mutating `handle.path`. `lineage` is
   persisted to the run's metadata sidecar.

**Name resolution for `getlimits` and `getposition`:**

- `getlimits(name)` → the adapter resolves via the existing stage-config
  loader (`stage_config.load(name)`) and returns a `Preset(type=LIMITS,
  fields={"x_min": …, "x_max": …, …})`. Accepted names match the bundles
  defined in the stage config file.
- `getposition(name)` → resolves via `parse_template_positions(name)` against
  the operator-defined scanning template of that name; if no such template
  exists, the adapter raises `FAILED` rather than synthesising one (synthesis
  is a workflow-side operation, not a hidden adapter fallback).

---

## 7. Phases, branches, testing

Build on `feat/mid-layer` off `try/all-four`.

- **Phase 1 — build the waist** (`controller/microscope/`). Pure code, no
  hardware. Unit-tested; plus a fake adapter for the import-independence check.
- **Phase 2 — build `NavigatorExpertAdapter`.** Includes the three areas of
  new code (§6). The state engine is unit-tested against captured real
  job-settings JSON. Gate: one example script ported to run through
  `Microscope` on hardware.
- **Phase 3 — relocate `workflow/`.** Move
  `controller/vendor/leica/navigator_expert/notebooks/workflow/` to
  `controller/workflow/`. (3a) Lift pure code and the transform module up;
  swap imports incrementally. (3b) The LRP-machinery move-down is an atomic
  cut-over; the old workflow location stays runnable until the new path passes
  a workflow integration run on hardware.
- **Phase 4 — enforce.** Import-lint (any tool that checks module imports per
  package — pick at implementation time): nothing under `controller/workflow/`
  or `controller/microscope/` imports `controller.vendor.*`.

**Testing tiers:** waist = unit tests (pure). Adapter = unit tests of the state
engine against real-data fixtures + hardware runs (mock-vs-real divergence has
bitten before — hardware is the truth for the adapter). Fake adapter = proves
import-independence, never behaviour.

Phases 1–2 are additive (zero risk). Phase 3 is the first edit to existing
files; do not merge until its hardware run is clean.

---

## 8. v1 scope — deliberately out

Each is a clean *additive* extension, not a v1 compromise:

- **Live / streaming acquisition** — v1 is batch only. Streaming would be a new
  method (not a mutation of `acquire`).
- **Mid-acquire cancellation** — v1 has `timeout` only. `KeyboardInterrupt`
  cannot interrupt a blocking native call until it returns.
- **Explicit session teardown** — v1 ties the vendor session to process
  lifetime; `Microscope.close()` (or context-manager support) lands when a real
  production deployment teaches what shape it needs.
- **Multi-plane `ImageHandle`** — v1 returns one plane per `acquire`. Stacks
  are workflow loops.
- **`scope.vendor` escape hatch** — *rejected.* Vendor-specific operations live
  inside the adapter. A notebook that genuinely needs vendor-specific behaviour
  can `from controller.vendor.leica.navigator_expert import …` directly — a
  visible, deliberate import, not a hidden path through `scope`.
- **Rich `Capability` vocabulary** — v1 ships almost none. The set grows when
  the second adapter forces real distinctions (e.g. AFC one-shot vs Definite
  Focus continuous-hold).
- **Second plug-in** — v1 ships Leica `navigator_expert` only. A real second
  plug-in (a Zeiss/ZEN adapter is the natural choice — another proprietary
  suite) is what confirms vendor-neutrality.
- **Typed OME metadata** — `ImageHandle.ome_xml` is raw XML for v1.
- **`output` and `positions` as preset types** — v1 has two preset types
  (`STATE`, `LIMITS`). `positions` is its own data shape; output is just a
  `save()` argument; neither needs a registry surface.

The motto: *if we end up needing more, we extend.*

---

## 9. Decisions log — index

A thin pointer to the body; resolution detail lives in the cited section.

| Topic | Resolution |
|-------|-----------|
| Surface | 12 flat methods, symmetric `get*`/`set*` — §2.1 |
| Failure | `MicroscopeError` carries `Verdict`; only failure raises — §2.2 |
| Failure types | `Status`, `Verdict`, `MicroscopeError` — §2.2 |
| Other data shapes | `Capability`, `PresetType`, `Position`, `Positions`, `Preset`, `ImageHandle` — §2.3 |
| `acquire` / `save` | separate verbs (not fused) — §2.1, §6 |
| Preset types | two: `STATE`, `LIMITS` — §2.3 |
| Plug-in selection | string id + explicit registry — §4 |
| Vendor escape | rejected — §8 |
| File format | flat OME-TIFF + companion XML sidecar via `_shared/output_layout` — §2.3, §6 |
| Scope boundaries | batch only, one plug-in, no cancellation, no session teardown — §8 |

---

## 10. Reference

- Frozen backend: `controller/vendor/leica/navigator_expert/driver/`. **Public
  API surface and docstrings live in `driver/__init__.py`**; treat that as the
  authoritative API reference (the older `controller/vendor/leica/README.md`
  may lag the code).
  Lower-level acquire: `acquire_frame` in `driver/acquire.py`. Save layer +
  companion-XML sidecar: `_shared/output_layout/` and the v6 helper
  `_find_companion_xml` in `driver/acquisition.py`.
- Prior prototype (up-face source): SMART v4, at
  `Z:/zmbstaff/10374/Protocols_Notes/thom/notes/20260224_thom_SMART/smart/smart_controller/`.
- Constraints and off-limits zones: `docs/cleanup/STATE.md`.
