# Code review: `zmart_controller`

- **Scope:** `zmart_controller/__init__.py`, `layer.py`, `registry.py`, `README.md`, `tests/` (conftest.py, mock_driver.py, test_layer.py, test_registry.py); notebooks skimmed for hygiene (`example_experiment.ipynb`, `example_leica_experiment.ipynb`). The Leica and mesoSPIM adapters were read for context only, to judge whether the controller's abstractions fit their real consumers.
- **Date:** 2026-07-03
- **Reviewed commit:** `c7964dd` (working tree identical to `origin/main`)
- **Verification:** all behavioral claims below were reproduced against the mock driver on this tree; the full test suite passes (35 passed in 0.05s).

## Executive summary

This is a healthy, deliberately small package that mostly lives up to its own "it earns its keep by being boring" charter (`layer.py:5-6`). The ops-table registry is the right amount of abstraction — proven by two real drivers (Leica, mesoSPIM) that plug in without any controller changes — and the code is close to bloat-free: no plugin framework, no ABCs, no caching, no config system. The two findings that need attention before anything else are documentation actively teaching a broken pattern: the package docstring's multi-microscope recipe disconnects the first microscope (ZC-01), and the flagship example notebook crashes on its state-key names, which drifted from the current `changeable`/`observed` contract (ZC-02). Everything else is medium/low hygiene: a signature-erasing `*args, **kwargs` wrapper, post-disconnect behavior guaranteed by the mock rather than the controller, README examples drifted from the real Leica connection dict, and a handful of small test/typing nits.

## What works well

Specific decisions worth keeping:

1. **The ops-table driver contract** (`registry.py:32-45`, `register()` at `registry.py:66-82`). A driver is a dict of plain functions keyed by operation name — no base class, no entry points, no dynamic discovery. This is validated by its consumers: both real adapters (`zmart_drivers/leica/stellaris5_y42h93/navigator_expert/zmart_adapter/zmart_adapter.py:1068-1093`, `zmart_drivers/mesospim/mesospim_zmart_adapter.py:597-633`) build the exact same 13-entry table with zero friction. This is the rare abstraction layer with two genuinely independent implementations behind it.
2. **Hand-written forwarding methods on `Session`** (`layer.py:50-174`) instead of `__getattr__` magic over the ops dict. Twelve short methods cost ~140 lines and buy real signatures, per-op docstrings, and IDE/tab support — the right trade for a surface aimed at "humans and AI agents alike" (`README.md:12`).
3. **Credential hygiene in error messages** (`registry.py:59-62`): `_identity()` lists only the missing key *names*, never values, because connection dicts may carry credentials — and there is a test pinning exactly that (`tests/test_registry.py:31-36`, asserting `"hunter2"` does not appear). Threat-aware without ceremony.
4. **Careful lifecycle ordering, with the reasoning written down.** `Session.disconnect()` marks closed *before* calling driver teardown so a raising teardown is never retried (`layer.py:168-174`); the module-level `set_instrument()` resolves the new session before tearing down the old one and tracks the new one before teardown so a raising teardown never leaks it (`__init__.py:52-57`) — and that exact edge is tested (`tests/test_layer.py:175-184`).
5. **Copy discipline in the registry**: `register()` stores `dict(connection)` (`registry.py:82`) and `get_instruments()` returns fresh copies (`registry.py:92`), so callers can edit an instrument dict (e.g. drop in `output_root`) without vandalizing the registry — both directions tested (`tests/test_registry.py:44-57`).
6. **No caching, stated as a contract** (`layer.py:126-127`, `layer.py:185`): option menus are forwarded live to the driver on every call. For hardware whose job list / options change under you (the Leica job catalog does), this eliminates a whole class of stale-menu bugs.
7. **The mock is a faithful reference, not a drifted stub.** Its return shapes — per-axis `{"value", "actuator", "unit"}` (`tests/mock_driver.py:161-169`), `changeable`/`observed` state split (`mock_driver.py:214-221`), non-sticky actuator defaults (`mock_driver.py:137-149`) — match both real adapters (Leica `zmart_adapter.py:514-550`, mesoSPIM adapter `get_xyz` and `get_state`), which add extras (e.g. Leica's `"hardware"` block) without breaking the core shape. The "mock registers from the test side, never imported by production" rule (`registry.py:15-17`, `tests/conftest.py:1-8`) keeps the dependency direction clean.
8. **Tests exercise behavior through the public API** (round-trips, error messages, idempotence, option discovery) rather than internals, and the whole suite runs offline in ~0.05 s.

## Findings

### ZC-01 — High — Documented multi-microscope pattern disconnects the first microscope

**Where:** `__init__.py:16-20` (docstring) vs `__init__.py:43-58` (implementation).

**Problem:** The package docstring teaches:

```python
# or hold the session object explicitly (needed for >1 microscope at once)
from zmart_controller import set_instrument
mic = set_instrument(instrument)
```

But `from zmart_controller import set_instrument` resolves to the module wrapper defined at `__init__.py:43`, which unconditionally disconnects the previous active session (`__init__.py:55-57`). Verified against the mock: after `mic1 = set_instrument(a); mic2 = set_instrument(b)`, `mic1.get_xyz()` raises `RuntimeError: session is disconnected`. Driving two microscopes at once via the documented import is impossible; the only way is the un-advertised `zmart_controller.layer.set_instrument`.

**Why it matters:** On real hardware this is a mid-experiment teardown of a live instrument, taught by the very first docstring a user reads. The single-active semantics themselves are a reasonable design — the docs are what's wrong.

**Action:** Either (a) fix the docstring to point the multi-scope case at `zmart_controller.layer.set_instrument` (and consider re-exporting it under a distinct name, e.g. `open_session`), or (b) drop the ">1 microscope at once" claim entirely if it's not a supported use case. Add a test asserting the wrapper's disconnect-previous-on-swap behavior, which is currently only implied (`tests/test_layer.py:175-184` tests the failure path, not the normal swap).

### ZC-02 — High — Example notebook crashes: state keys drifted from `changeable`/`observed`

**Where:** `example_experiment.ipynb` cells 6-8 (markdown "an `immutable` fingerprint plus a `mutable` part"; code `prescan["mutable"]["laser_power"] = 2.0`).

**Problem:** The mock's `get_state()` returns `{"changeable": ..., "observed": ...}` (`tests/mock_driver.py:218-221`), as do both real adapters and the controller docs (`layer.py:62-78`, `README.md:112-121`). The notebook still uses the old `mutable`/`immutable` vocabulary; cell 7 raises `KeyError: 'mutable'` (verified). Cell 11's markdown also says `zmart.set_state(target)` — a module name that doesn't exist in the notebook (`zmart_controller` everywhere else).

**Why it matters:** `README.md:166-169` sells this notebook as the runnable end-to-end reference ("open it and step through the cells"). It's the first thing a new user runs, and it dies at step 2.

**Action:** Update cells 6-8 and 11 to the `changeable`/`observed` contract. Since the notebook runs fully offline against the mock, add a smoke test that executes it (e.g. `nbclient`/`pytest --nbmake`) so this class of drift can't recur.

### ZC-03 — Medium — Post-disconnect safety is guaranteed by the mock, not the controller

**Where:** `layer.py:162-174` (`Session.disconnect` sets `_closed` but no other op reads it); `tests/test_layer.py:139-142` (`test_ops_after_disconnect_raise`).

**Problem:** `Session._closed` guards only double-disconnect. `test_ops_after_disconnect_raise` passes solely because the *mock* raises via `_require_open` (`tests/mock_driver.py:89-92`) — the controller makes no such promise. The real consumers diverge: the Leica adapter re-implements `_require_open` in every op (`zmart_adapter.py:159-162`), while the mesoSPIM adapter has no closed flag at all — a controller op after `disconnect()` there hits a closed client with whatever confusing error the transport produces.

**Why it matters:** The test pins a contract the controller doesn't own, and each driver must re-implement (or forget) the same guard. This is exactly the kind of duplicated safety logic the thin controller exists to centralize.

**Action:** Check `self._closed` at the top of every `Session` op (one shared `_require_open(self)` helper, ~4 lines total) and raise a clear `RuntimeError`. The mock's and Leica's per-op guards then become redundant defense-in-depth, and the existing test becomes honest.

### ZC-04 — Medium **[YAGNI]** — `set_instrument(*args, **kwargs)` erases the signature of the primary entry point

**Where:** `__init__.py:43`.

**Problem:** The wrapper takes `*args, **kwargs` and forwards to `layer.set_instrument`, which accepts exactly one parameter: `instrument: dict[str, Any]` (`layer.py:177`). The star-signature is speculative generality — there is no second signature to forward — and it costs real usability: `help()`/IDE show nothing, and a typo like `set_instrument(instrument=..., extra=...)` surfaces as a confusing TypeError from the layer.

**Action:** Declare it as `def set_instrument(instrument: dict[str, Any]) -> Session` and forward explicitly.

### ZC-05 — Medium — README connection-dict examples drifted from the real Leica adapter

**Where:** `README.md:82-83` and `README.md:185-191` vs the adapter's actual `CONNECTION` (`zmart_adapter.py:89-97`).

**Problem:** The README shows `{"vendor": "leica", "microscope": "stellaris5-01", ..., "api_delay_ms": 250}`. The real adapter registers `"microscope": "stellaris5-y42h93"`, `"api_delay_ms": None`, and — crucially — `"output_root": None`, which `acquire()` requires and which the Leica notebook must edit in (`example_leica_experiment.ipynb` cell 4). A reader comparing the README to `get_instruments()` output sees a dict that matches on nothing but the vendor, and the one key they *must* set is absent.

**Why it matters:** Step 1 of "The workflow, step by step" is the on-ramp; copy-paste drift here erodes trust in the rest of the doc.

**Action:** Paste the adapter's real `CONNECTION` dict (values as registered) into both README examples, and mention `output_root` where the README explains editing the dict before connecting (`README.md:75-78`).

### ZC-06 — Medium — Module `__getattr__` delegates private attributes of the active session

**Where:** `__init__.py:74-77`.

**Problem:** The delegation branch checks `hasattr(_active, name)` with no underscore guard (the `startswith("_")` check exists only in the no-active branch, `__init__.py:78`). With a session active, `zmart_controller._ops` and `zmart_controller._handle` resolve to the session's internals (verified: returns the ops dict).

**Why it matters:** It silently widens the public surface to `Session`'s implementation details; code that starts depending on `zmart_controller._handle` will break when internals change, and the leak contradicts `layer.py:26-27` ("The only public attribute is `context`").

**Action:** In `__getattr__`, refuse names starting with `_` before delegating (fall through to the standard AttributeError).

### ZC-07 — Low — Captured module-level methods go stale after an instrument swap

**Where:** `__init__.py:74-77`.

**Problem:** `zmart_controller.set_xyz` returns a method bound to the *current* session at attribute-access time. `f = zmart_controller.set_xyz; set_instrument(other); f(1, 2, 3)` raises `RuntimeError: session is disconnected` (verified) — or worse, would silently drive the old scope if a driver doesn't guard closed handles (see ZC-03).

**Action:** Not worth a wrapper layer; document in the `__getattr__` comment / package docstring that module-level calls must be made through the module attribute, not captured into variables across `set_instrument` calls.

### ZC-08 — Low — Unstated single-threaded assumption around module-global state

**Where:** `__init__.py:40, 50-58`; `registry.py:52`.

**Problem:** The `previous, _active = _active, new` swap is not atomic; two threads calling `set_instrument` concurrently can both read the same `previous`, leaving one session never disconnected. `REGISTRY` mutation is likewise unsynchronized. No docstring claims thread safety, so this is not a broken promise — but hardware-control code is exactly where someone eventually adds a watchdog thread.

**Action:** One sentence in the package docstring: the module-level surface (and registry mutation) assumes a single thread; use explicit `Session` handles from a single owner thread otherwise. No locks needed today.

### ZC-09 — Low — Inconsistent return annotations on `Session` setters

**Where:** `layer.py:72` (`set_state`), `layer.py:84` (`set_procedure`), `layer.py:109` (`set_xyz`).

**Problem:** Every `get_*` is annotated `-> dict`, and the setters' docstrings all say "return whatever the driver reports", but the three setters carry no return annotation. Copy-paste drift within one class.

**Action:** Annotate all three `-> dict` (or `-> Any` if the contract is genuinely "whatever" — but the mock and both adapters always return dicts, so `-> dict` matches reality).

### ZC-10 — Low — `set_procedure` runs; `set_instrument` connects

**Where:** `layer.py:84-89`; `layer.py:177`.

**Problem:** `set_procedure`'s own docstring opens with "Run a procedure" — nothing is set or persisted; both real adapters implement it as command dispatch (mesoSPIM adapter `set_procedure` moves the focus axis). The get/set symmetry is clearly a deliberate vocabulary choice (`layer.py:8-10`), but this one verb misleads about side effects, which matters when the side effect is hardware motion.

**Action:** Either rename to `run_procedure` (with a deprecation alias if churn is a concern), or state the "get discovers / set applies-or-runs" convention once in the README so the asymmetry is a documented rule rather than a surprise.

### ZC-11 — Low **[YAGNI]** — `resolve()` returns its own argument

**Where:** `registry.py:95-110`; consumer at `layer.py:190`.

**Problem:** `resolve(instrument)` returns `(ops, connection)` where `connection` *is* the `instrument` argument, unmodified — a value the sole caller already holds (`ops, connection = resolve(instrument)`; `layer.py:190-192`). The tuple return is API surface with no information content, and it invites the false reading that resolve merges the stored registration dict in.

**Action:** Return just the ops table; `set_instrument` keeps using its own `instrument`.

### ZC-12 — Low — `register()` validates op names but not callability

**Where:** `registry.py:76-78`.

**Problem:** `ops={"connect": None, "get_xyz": some_dict, ...}` registers successfully and fails only at `set_instrument`/call time with a bare `TypeError: 'NoneType' object is not callable`. The whole point of validating at registration (`registry.py:76-78` already rejects missing names) is fail-fast.

**Action:** Extend the existing check: `missing = [name for name in OPS if not callable(ops.get(name))]`, and validate `disconnect` is callable when present.

### ZC-13 — Low — Tests reset state through private internals

**Where:** `tests/test_registry.py:19` (`registry.REGISTRY.pop(registry._identity(...))`); `tests/conftest.py:36` (`zmart_controller._active = None`).

**Problem:** The registry fixture uses the private `_identity` and mutates `REGISTRY` directly; the autouse fixture nulls `_active` without disconnecting, leaking the session (harmless for the mock, but it bypasses the public teardown path the suite claims to exercise).

**Action:** In conftest, call `zmart_controller.disconnect()` instead of assigning `_active = None` — it's the public API, it's idempotent, and it also disconnects the leaked session. The registry fixture's direct pop is acceptable given no `unregister()` exists (adding one just for tests would itself be YAGNI); a one-line comment saying so would settle it.

### ZC-14 — Low **[PATCHWORK]** — sys.path surgery in conftest and both notebooks because the package is not installable

**Where:** `tests/conftest.py:13-17`; `example_experiment.ipynb` cell 2; `example_leica_experiment.ipynb` cell 1; root cause: `pyproject.toml` has no `[project]` table (lint config only), acknowledged at `__init__.py:22` ("Requires the repository root ... on sys.path").

**Problem:** Three separate copies of path-hacking exist to work around the missing packaging metadata, and `import mock_driver` puts a generically-named module at the top level of `sys.modules` (collision-prone).

**Action:** Add a minimal `[project]` table so `pip install -e .` works; the conftest then shrinks to `register_mock()` via `from zmart_controller.tests import mock_driver` (plus a `tests/__init__.py`), and the notebooks lose their first cell. Until then, this is tolerable — but it's the root cause behind three workarounds.

### ZC-15 — Low — Misfiled tests in `TestDisconnect`

**Where:** `tests/test_layer.py:144-154`.

**Problem:** `test_actuator_selection_does_not_persist` and `test_invalid_acquire_option_rejected` live inside `TestDisconnect` but have nothing to do with disconnect — copy-paste placement drift.

**Action:** Move them to `TestFrame` and `TestAcquire` respectively.

### ZC-16 — Low — The optional-`disconnect` branch is never tested

**Where:** `layer.py:172-174` (`self._ops.get("disconnect")` None path).

**Problem:** `OPS` deliberately excludes `disconnect` (`registry.py:31`), and the registry tests register drivers without one (`tests/test_registry.py:22-23`) — but no test ever opens a `Session` on such a driver and calls `disconnect()`. The one branch that exists specifically to tolerate a missing op has no coverage.

**Action:** One test: register a scratch driver without `disconnect`, `set_instrument`, `session.disconnect()` — must be a silent no-op.

### ZC-17 — Low — Two import spellings for the Leica adapter; notebook lint

**Where:** `example_leica_experiment.ipynb` cells 1-2 (`sys.path += [...]; import navigator_expert.zmart_adapter`) vs `README.md:15-16` and `registry.py:13-16` (`import zmart_drivers.leica.stellaris5_y42h93.navigator_expert.zmart_adapter`).

**Problem:** Adding the machine dir to `sys.path` makes the same modules importable under two different names. If a workflow ever mixes the spellings, Python creates two module objects — two registrations, two `MACHINE` singletons. Also `ruff check` flags both import cells (I001), the only lint findings in the package.

**Action:** Use the dotted `zmart_drivers...` path in the notebook (only the repo root is needed on `sys.path`), and fix the two I001s.

### ZC-18 — Low — README states the `zmart` brand surface in the present tense

**Where:** `README.md:20-23` ("the layer the outside world is meant to import (`import zmart`)").

**Problem:** No `zmart` package exists; `docs/ZMART.md` is explicit that the waist *currently* "exists as the `zmart_controller/` package". A reader skimming the README may try `import zmart` and fail.

**Action:** One-word fix: phrase it as the intended future surface ("will be importable as `zmart`"), keeping the ZMART.md pointer.

### ZC-19 — Low — Notebook ergonomics: no `__dir__`, no `Session.__repr__`

**Where:** `__init__.py` (no `__dir__`); `layer.py:23` (`Session` uses default repr).

**Problem:** The delegated verbs (`acquire`, `set_xyz`, ...) are invisible to `dir(zmart_controller)` and tab-completion — in the notebook-first workflow this package targets, discoverability of the module surface is the product. Likewise `set_instrument(...)` as the last expression of a cell (as in `example_experiment.ipynb` cell 5) prints `<zmart_controller.layer.Session object at 0x...>` instead of anything useful.

**Action:** Add a module `__dir__` returning the module names plus `Session`'s public methods, and a `Session.__repr__` built from `self.context` (e.g. `<Session leica/stellaris5-y42h93 via navigator-expert>`).

## Summary table

| ID | Severity | Title |
|-------|----------|-------|
| ZC-01 | High | Documented multi-microscope pattern disconnects the first microscope |
| ZC-02 | High | Example notebook crashes on stale `mutable`/`immutable` state keys |
| ZC-03 | Medium | Post-disconnect op safety guaranteed by the mock, not the controller |
| ZC-04 | Medium | `set_instrument(*args, **kwargs)` erases the primary entry point's signature **[YAGNI]** |
| ZC-05 | Medium | README connection-dict examples drifted from the real Leica adapter |
| ZC-06 | Medium | Module `__getattr__` delegates private session attributes |
| ZC-07 | Low | Captured module-level methods go stale after instrument swap |
| ZC-08 | Low | Unstated single-threaded assumption around `_active` / `REGISTRY` |
| ZC-09 | Low | Missing return annotations on `set_state` / `set_xyz` / `set_procedure` |
| ZC-10 | Low | `set_procedure` runs, `set_instrument` connects — misleading verbs |
| ZC-11 | Low | `resolve()` returns its own argument **[YAGNI]** |
| ZC-12 | Low | `register()` doesn't check ops are callable |
| ZC-13 | Low | Tests reset state through private internals, leaking sessions |
| ZC-14 | Low | sys.path surgery in conftest + notebooks; package not installable **[PATCHWORK]** |
| ZC-15 | Low | Misfiled tests inside `TestDisconnect` |
| ZC-16 | Low | Optional-`disconnect` branch never tested |
| ZC-17 | Low | Two import spellings for the Leica adapter; notebook I001 lint |
| ZC-18 | Low | README claims `import zmart` in the present tense |
| ZC-19 | Low | No `__dir__` / `Session.__repr__` for the notebook-first surface |
