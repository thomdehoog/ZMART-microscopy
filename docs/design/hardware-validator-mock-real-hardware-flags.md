# Fix the mock acquire test, then collapse hardware-validator flags to --mock / --real-hardware

Status: proposed, not yet implemented.

## Context

While running the full CI (`run_ci.py both --live-writes`) to verify an unrelated change, one
offline test failed: `test_acquire_backlash_correction_through_the_controller_seam` in
`tests\hardware\test_validate_zmart_adapter.py`. Investigating why it never reached an actual
acquisition led to a broader realization: the hardware-validator scripts have accumulated a large,
confusing flag surface (`--read-only`, `--yes`, `--mock`, `--allow-xy`, `--allow-z`,
`--allow-objective`, `--allow-acquire`, `--allow-move`, `--allow-state`, `--allow-autofocus`,
`--allow-job-switch`, `--allow-template-roundtrip`, `--allow-missing-lasx`, `--skip-settings`,
spread inconsistently across 5 different scripts). The decision: collapse this to exactly two
flags everywhere: `--mock` (run everything against the in-process fake CAM) and `--real-hardware`
(run everything for real, live). Confirmed across several rounds of design discussion:

- Fix the failing test now, independently of the bigger redesign.
- Collapse ALL the granular `--allow-*` phase gates into the two-flag binary — no more per-phase
  opt-in. `--real-hardware` means "do everything for real" (writes, moves, objective switches,
  acquisitions); `--mock` means "do everything against the mock" (same scope, minus the one hard
  capability boundary below).
- `probe_four_readers.py` (which currently has zero mock support — always connects to live LAS X)
  gets a mock branch added too, for consistency across all 5 scripts.
- `run_ci.py` keeps its own orchestration-level gate: `online`/`both` mode WITHOUT `--live-writes`
  no longer invokes any of the 5 hardware-validator scripts at all (there's no more safe "connect
  to real hardware but stay read-only" concept once `--real-hardware` always does everything).
  `online`/`both --live-writes` invokes them all with `--real-hardware`, which now includes
  objective switches and real acquisitions on every such run (previously those stayed manual-only).

**One unavoidable hard boundary, not a design choice**: `MockLasxClient`
(`tests\helpers\mock_lasx_api.py`) has no `PyApiSaveExperiment`/`PyApiLoadExperiment` and never
writes real export files to disk. This means the *adapter-level* capture+save path
(`zmart_adapter.py`'s `acquire()`, used by `validate_zmart_adapter.py`'s `phase_acquire`) can never
produce a real image under `--mock`, no matter how the flags are named — it has to keep a
mock-specific skip for that one specific sub-step. Everything else (settings, moves, job
selection, objective switch, the *driver-level* `drv.acquire()` used by `validate_hardware.py`,
and the whole `backlash → capture → save` ordering logic) already works fully against the mock
today and stays that way.

## Part A — Fix the failing test (do first, independent, low risk)

**File:** `tests\hardware\test_validate_zmart_adapter.py`, around line 153-157.

The test's own purpose (per its docstring) is to verify the `Session -> ops table -> adapter`
seam correctly orders `backlash_correction` before capture — it has nothing to do with scan-field
stripping. The production code already exposes a first-class opt-out for exactly this I/O
boundary (`zmart_adapter.py:593`, `strip_scan_fields: [True, False]`, referenced directly in the
runtime error message and in `README.md:308-311`). Add it to the options dict:

```python
record = session.acquire(
    acquisition_type="prescan",
    position_label="1",
    options={"backlash_correction": True, "strip_scan_fields": False},
)
```

This is the smallest correct fix: it needs no `MockLasxClient` changes, no fixture changes, isn't
dependent on the host machine's real `%APPDATA%\...\ScanningTemplates` state (making the test more
hermetic as a side effect), and doesn't touch anything the test is actually asserting on
(`order == [("backlash", ...), ("capture", ...)]`).

*(Not in scope: the more general BENCH_EVAL_2026-07-07.md bug #4 — `find_scanning_templates_dir()`
reading the real `%APPDATA%` regardless of `hermetic_mock_machine_root()` — remains open for any
other mock code path that might hit `_ensure_scan_fields_stripped` with a real, unstripped
template on the host machine. Not touching it here since it's an unrelated, already-tracked issue.)*

**Verification:** `pytest tests/hardware/test_validate_zmart_adapter.py::test_acquire_backlash_correction_through_the_controller_seam -v`
passes; then re-run the full `python run_ci.py both` to confirm 1000/1000 offline tests pass again.

## Part B — Collapse the flag surface to --mock / --real-hardware

### The pattern (applies to all 5 validator scripts)

For each of `validate_hardware.py`, `validate_zmart_adapter.py`,
`validate_readers_side_by_side.py`, `stress_hardware.py`, and `probe_four_readers.py`:

1. **Argparse**: remove `--read-only`, `--yes`, `--allow-missing-lasx`, `--skip-settings`, and every
   per-phase `--allow-*` flag (`--allow-xy`, `--allow-z`, `--allow-objective`, `--allow-acquire`,
   `--allow-move`, `--allow-state`, `--allow-autofocus`, `--allow-job-switch`,
   `--allow-template-roundtrip`). Add `--real-hardware` (`store_true`). Keep `--mock` where it
   already exists (`validate_hardware.py`, `validate_zmart_adapter.py`,
   `validate_readers_side_by_side.py`, `stress_hardware.py`); add it fresh to
   `probe_four_readers.py`. Make the two mutually exclusive and jointly required
   (`parser.add_mutually_exclusive_group(required=True)`) — no more "real hardware by default when
   no flag given."
2. **Connection**: keep each script's existing mock-construction mechanism as-is (it already
   works and is tested) — just gate it on `args.real_hardware`/`args.mock` instead of the old
   flags:
   - `validate_hardware.py`, `validate_readers_side_by_side.py`, `stress_hardware.py`: keep the
     existing `if args.mock: MockClient(...) else: load_lasx_api_runtime() -> Connect(...)` shape
     in their `_connect()` functions.
   - `validate_zmart_adapter.py`: keep the existing monkeypatch-of-`connect_python_client` shape in
     `_connect_session()`.
   - `probe_four_readers.py`: **new** — add a `_connect(args)` mirroring the same
     `hermetic_mock_machine_root()` + `MockLasxClient(...)` branch used elsewhere (it already
     performs XY moves and job changes, so it needs the same limits-handshake redirection the other
     mock branches set up first), replacing its current unconditional
     `drv.connect_python_client(...)` call.
3. **Phase gating**: every phase function that was previously guarded by an `--allow-*` flag now
   just always runs when the script runs — delete the `if not args.allow_x: skip(...)` guards.
   `_confirm_live_write()`-style interactive-prompt helpers are deleted entirely (no longer needed:
   passing `--real-hardware` *is* the explicit confirmation).
4. **The one exception**: `validate_zmart_adapter.py`'s `phase_acquire` keeps its `--mock`-specific
   skip for the file-producing capture+save step (see Context above) — update the skip *reason*
   text and condition to check `args.mock` (same as today), but it no longer depends on
   `--allow-acquire` since there's no such flag anymore; it simply always attempts real acquire
   under `--real-hardware` and always skips-with-reason under `--mock`.
5. **Docstrings/usage strings**: update each script's module docstring and CLI help/usage examples
   (several scripts print `Usage:` blocks referencing the old flags — e.g.
   `validate_zmart_adapter.py:24-27`) to the new two-flag examples.

### `run_ci.py`

- Delete the `sxs_gate`/`vh_gate`/`adapter_gate` per-script flag-list construction
  (`run_ci.py:256-263` roughly) — replace with a single decision: if `args.live_writes` (only
  meaningful when `mode` is `online`/`both`), invoke each of the 5 hardware scripts with
  `--real-hardware`; if not, **skip invoking all 5 hardware-validator steps entirely** (no
  `--mock` fallback here — mock coverage already comes from the offline pytest suite in the same
  run). Print a clear one-line note in the CI summary when hardware validation was skipped this
  way, so it's not a silent gap (e.g. `"hardware validation skipped (pass --live-writes to run it)"`).
- `probe_four_readers.py`'s special-cased always-`--read-only` invocation
  (`run_ci.py:298-299`) goes away — it now follows the same on/off-with-`--real-hardware` pattern
  as the other 4 scripts.
- The pre-hardware safety gate (`pytest tests/unit/test_limits_adversarial.py` mock self-check,
  `run_ci.py:264-293`) is unrelated to this change and stays exactly as-is.
- Update `run_ci.py`'s own `--help`/docstring (`run_ci.py:8-14`) to describe the new behavior:
  `online`/`both` without `--live-writes` now does *no* hardware-validator steps at all (previously
  it ran them read-only); `--live-writes` now also implies objective switches and real
  acquisitions (previously those stayed manual-only).

### Pytest wrappers that call `.main([...])` with the old flags — must be updated or they'll break

Argparse will reject the now-deleted flags, so every in-process caller needs its argument list
updated to just `["--mock"]` (or `["--real-hardware"]` where a wrapper deliberately tests the real
path, though most of these wrappers are offline/mock-only by design). Known call sites to fix,
found during Part A/B investigation — grep for `\.main\(\[` under `tests\hardware\` and
`tests\unit\` to confirm there are no others before finishing:

- `tests\hardware\test_validate_hardware.py` (`test_validate_hardware_full_mock_run` and others —
  currently pass `--mock --allow-xy --allow-z --allow-objective --allow-acquire`)
- `tests\hardware\test_validate_zmart_adapter.py` (the `_run_mock()` helper, plus the assertion at
  `test_validate_zmart_adapter.py:100-101` that currently checks
  `by_name["phase: acquire"]["status"] == "SKIP"` under mock — this assertion should still hold
  under the new scheme since the file-producing skip is preserved, so the assertion itself likely
  doesn't need to change, only the `.main([...])` argument list feeding it)
- `tests\hardware\test_stress_hardware.py` (multiple scenarios combining `--mock` with various
  `--allow-*`)
- Any `test_validate_readers_side_by_side.py`-equivalent wrapper, if one exists (confirm during
  implementation — verify before assuming it's covered only by the live `run_ci.py` invocation)

## Out of scope (explicitly, per the investigation)

- Centralizing the 3 different mock-connection mechanisms (direct `MockLasxClient` bypass,
  `adapter._session.connect_python_client` monkeypatch, template-function monkeypatch) into one
  seam inside `connection\session.py` itself. The ask is about the CLI flag surface, not the
  internal mocking architecture — each script keeps whatever mechanism it already has, just
  triggered by the new two-flag names.
- BENCH_EVAL_2026-07-07.md bug #4 (the general `%APPDATA%`/`ScanningTemplates` hermeticity gap
  beyond the one test fixed in Part A).
- Adding real file-writing simulation to `MockLasxClient` so adapter-level acquire could work
  under mock — confirmed as a hard, out-of-scope capability gap, not something this change
  attempts to close.

## Verification

- Part A: the specific test passes in isolation, then the full offline suite
  (`python run_ci.py` default mode) is back to 0 failures.
- Part B, offline: `python run_ci.py` (default/offline mode) — every pytest wrapper that drives
  `.main([...])` must still pass with the new argument lists.
- Part B, online read: `python run_ci.py both --live-writes` against the live LAS X simulator —
  all 5 hardware steps should run and pass, now including objective-switch and real-acquire
  phases that previously stayed manual-only. Watch specifically for: the objective actually
  switching and switching back on the real/simulated scope, and a real acquisition actually
  producing files.
- Part B, orchestration: `python run_ci.py both` (no `--live-writes`) — confirm the CI summary
  shows the 5 hardware steps as skipped-with-explanation rather than either erroring or silently
  vanishing.
- `git status` at the end should show changes confined to: `run_ci.py`, the 5 scripts under
  `tests\hardware\`, their pytest wrappers, and `test_validate_zmart_adapter.py` (Part A's one-line
  fix, likely the same file touched again in Part B for the mock-skip condition update).
