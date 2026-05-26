# SMART

Microscope automation framework.

## Structure

- `shared/` - vendor-neutral utilities used by controllers and workflows.
- `controller/vendor/leica/navigator_expert/` - Leica Navigator Expert package.
  - `driver/` - LAS X driver, template handling, acquisition save chain, and stage helpers.
  - `tests/` - offline driver unit tests and fixtures.
- `calibration/vendor/leica/navigator_expert/` - Leica calibration notebooks, code, tests, and promoted current state.
- `workflows/vendor/leica/navigator_expert/` - Leica workflow entry points.
  - `target_acquisition/` - target acquisition notebook, pipeline code, docs, and tests.
  - `examples/` - runnable Leica workflow cookbooks.
- `docs/cleanup/` - active cleanup state and conventions.

## Leica LAS X Driver

- **Package**: `controller/vendor/leica/navigator_expert/driver/`
- **API reference**: `controller/vendor/leica/navigator_expert/README.md`
- **All commands return** a result dict with `success`, `confirmed`, `message`, `timing`, `logs`

## Code Quality

Before finalizing any change, review it for cleanliness: every fix should be structural, not bolted on. Prefer refactoring the underlying design over adding special cases, branching logic, or conditional workarounds. If a new parameter creates a parallel code path instead of unifying an existing one, rethink the approach. The goal is code that looks like it was always designed this way, not code that reveals its history of patches.

Follow the Zen of Python:

- Beautiful is better than ugly.
- Explicit is better than implicit.
- Simple is better than complex.
- Complex is better than complicated.
- Flat is better than nested.
- Sparse is better than dense.
- Readability counts.
- Special cases aren't special enough to break the rules.
- Errors should never pass silently.
- Unless explicitly silenced.
- In the face of ambiguity, refuse the temptation to guess.
- There should be one, and preferably only one, obvious way to do it.
- If the implementation is hard to explain, it's a bad idea.
- If the implementation is easy to explain, it may be a good idea.

## Environment

- **Git**: `C:/ProgramData/MinicondaZMB/Library/bin/git.exe`
- **Conda env**: `C:/ProgramData/MinicondaZMB/envs/lasxapi_extended`

## Active Cleanup

Read `docs/cleanup/STATE.md` first for the current cleanup-wave state, off-limits zones, open questions, and the rollback path. `docs/cleanup/CONVENTIONS.md` is the rubric every cleanup commit is graded against.
