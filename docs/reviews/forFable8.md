# Review prompt: low-level Leica limits enforcement

Review commit `02a37b9` (`Enforce typed Leica limits at commands`) on branch
`claude/forfable4-document-11mxsx` in the ZMART-microscopy repository. Compare
`fff3768..02a37b9`. Review only this changeset and the existing code paths that
are necessary to prove or disprove its safety claims. Do not review unrelated
legacy code, and do not modify files.

## Intended contract

`limits.json` is one flat, operator-readable Leica configuration. Every
constrained entry is explicitly one of:

```json
{"range": [0, 10]}
{"allowed": [1, 2, 3]}
```

An exact `[]` means that the setter was considered but is intentionally
unrestricted. Stage X/Y, z-galvo, and z-wide must use `range`; objective slots
must use `allowed`; each configurable Leica setter has its own same-named key.
Missing keys, unknown keys, malformed constraints, legacy schemas, non-finite
ranges, and invalid objective slots must never be silently accepted.

The central safety requirement is that enforcement occurs at the lowest shared
software boundary: inside the Leica command wrappers, immediately before the
native CAM model can be created or fired. The adapter, `zmart_controller`,
workflows, website, and notebooks must all inherit this protection and must not
be able to bypass it. A caller using the public command wrappers directly must
receive the same protection.

The limits handshake is fail-closed. A never-handshaken client, failed
handshake, or configured constraint violation must refuse before touching the
native API. Invalid machine-local configuration may use the documented,
loudly reported bundled-default fallback, but it must not authorize values
outside that fallback. The independent hardcoded physical stage backstop must
remain effective.

The renamed `limits/notebooks/set_limits.ipynb` must remain a minimal file
factory: explanatory text, one small code cell, the complete flat configuration,
and one call into the driver to validate and publish it. It must not contain
driver implementation logic.

## Required trace and adversarial review

Trace every public mutating Leica wrapper to its final native API fire. Build an
independent inventory rather than trusting `MUTATING_COMMANDS` or the existing
tests, then verify that every path checks the installed policy before native
objects are accessed. In particular, verify:

1. `move_xy` and `move_z` check the actual physical axis values, including both
   Z actuators, and remain bounded by the hard backstop.
2. Objective selection by slot, name, or magnification is resolved to the
   physical turret slot before the allowed-slot check.
3. Every configurable `set_*` wrapper passes the setting value—not a job name,
   setting index, or other metadata—to its matching flat policy entry.
4. Z-stack definition checks both explicit endpoints. A reset whose resulting
   endpoint is unknown must fail closed whenever that setter is constrained.
5. `range` is inclusive and rejects booleans, non-numeric values, NaN, and
   infinity. `allowed` membership cannot be bypassed through Python equality or
   type coercion.
6. `[]` is unrestricted only for that setting; it must not disable the session
   handshake or another command's constraints.
7. Acquisition, job selection, experiment load/save, galvo-to-pixel movement,
   and procedure paths that do not have configurable JSON entries still cannot
   execute through a client with no valid limits handshake.
8. A stale or disconnected client's gate state cannot govern a new client,
   including possible Python object-id reuse and reconnect sequences.
9. There is no higher-level path that reaches the native Leica client directly
   and thereby skips the command wrappers. Trace browser action → web flow →
   workflow → controller session → Leica adapter → command wrapper for the
   affected operations.
10. Validation and runtime enforcement interpret the exact same policy. Look
    for normalization drift, mutable-policy problems, unsupported yet accepted
    scalar types, ambiguous allowed values, empty candidate lists, and error
    paths that accidentally return success.

Use hostile clients/spies that raise on any attribute access to prove refusal
happens before the native layer. Add temporary local tests if useful for the
review, but leave the worktree unchanged. Do not require or synthesize real
microscope data; all safety behavior in this changeset must be provable offline.

## Files central to this review

- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/commands/gate.py`
- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/commands/commands.py`
- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/motion/stage_config.py`
- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/motion/limits.py`
- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/limits/defaults/limits.json`
- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/limits/notebooks/set_limits.ipynb`
- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/unit/test_limits_adversarial.py`
- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/tests/unit/test_stage_config.py`
- `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/zmart_adapter/`
- `zmart_controller/` and `workflows/target_acquisition/`, only as needed to
  verify that the low-level boundary cannot be bypassed

## Validation to reproduce

Use the repository's Python 3.11 environment. From the Leica driver directory:

```text
python run_ci.py --mock
```

Expected for `02a37b9`: `1100 passed, 1 skipped`, approximately 83.45% coverage.
The skip is the expected unavailable LAS X CAM runtime on macOS. The two
whole-driver `ruff format --check` warnings in `motion/movement.py` and
`tests/unit/test_stage_backlash.py` predate this changeset; all changed Python
files must be formatted.

From the repository root:

```text
python -m pytest -q -rs zmart_controller/tests workflows/target_acquisition/tests
python -m pytest -q shared/limits/tests shared/output_layout/tests
python -m pytest -q workflows/target_acquisition/tests/test_webapp_browser.py
```

Expected locally: `341 passed, 3 skipped`; then `85 passed`; then `5 passed`.
The three skips are the known offline `skimage.data` download failures. Run the
real Chromium webapp file three consecutive times and require `5 passed` each
time.

Also require:

- `ruff check` for the Leica driver, controller, and target-acquisition workflow;
- `ruff format --check` for every Python file changed by `fff3768..02a37b9`;
- `git diff --check fff3768..02a37b9`;
- nbformat validation and Python compilation of `set_limits.ipynb` and both v4
  notebooks;
- an AST/literal comparison proving the notebook's `LIMITS` value exactly
  matches the bundled `limits/defaults/limits.json`;
- no remaining reference to `set_stage_limits.ipynb`;
- a clean worktree after review.

## Deliverable

Report findings first, ordered **blocker**, **major**, **minor**, then **nit**.
Every finding must include an exact `file:line`, a concrete bypass or failure
sequence, its impact, why the current tests miss it, and the smallest safe fix.
Do not report speculative style preferences as safety findings.

Then provide a verified-correct section covering the independently traced
command boundary, schema behavior, upper-layer inheritance, notebook parity,
and reproduced test results. State explicitly if there are no findings.
Residual risk should be limited to behavior that genuinely requires the LAS X
runtime or physical microscope; do not use lack of hardware to excuse a safety
property that can be tested with mocks.
