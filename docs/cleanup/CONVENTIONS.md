# Cleanup conventions

These are the rules every cleanup commit on this repo is graded
against. They're framed so a reviewer (or future-you) can mechanically
check them — not aspirations.

Domain context: this is a Leica LAS X microscope automation package.
Readers may be biologists, microscopists, or developers — keep that
audience in mind for any prose written into the codebase.

---

## 1. Comments explain WHY, never WHAT

Names show what; comments earn their keep by explaining hardware
quirks, invariants, or surprises a reader can't infer.

- Bad: `# Set zoom to 1`
- Good: the `#:` blocks in `examples/galvo_zoom_in.py` for
  `IDLE_TIMEOUT_S` — names the constant AND explains why it's 5.0
  and why it isn't used between pan and acquire.

## 2. Educational annotations belong on hardware-domain choices, not Python idioms

Don't explain `@dataclass(frozen=True)`. Do explain what an LRP is,
why galvo pan ≠ stage move, why `ImageTransformation = TOPLEFT`
matters. The top-of-file docstrings in `examples/*.py` are the model
— replicate that flavour in module docstrings across the codebase.

## 3. Workarounds carry a marker; root causes get fixed

A workaround is acknowledged failure. If it stays, it carries a
`# WORKAROUND: ...` line citing the upstream limitation (LAS X
firmware, vendor API quirk) so it's greppable and revisitable. If
the root cause can be fixed in our code, fix it instead — no
patchwork.

## 4. Zero tolerance for dead code

- No commented-out code (git history is the archive).
- No "might be useful later" stubs.
- No unused parameters, defaults, or dataclass fields.
- `DEFAULT_APPLY_BACKLASH = True` (defined-never-read in three
  files, removed in `0419a9e`) is the canonical anti-example.

## 5. Hardware quirks live behind named helpers

A bare `time.sleep(0.5)` in driver code is a smell. A
`wait_for_lasx_to_commit_lrp_edit()` with a one-line docstring
("LAS X needs ~500 ms after a zoom write before the next edit;
shorter intervals trigger silent re-clamp") is documentation. Same
number, much better signal.

## 6. Magic numbers become named constants with units

Already the house style — `SETTLE_AFTER_LAS_X_EDIT_S: float = 0.5`,
not `0.5`. Extend it to anywhere a literal still appears in
runtime code.

## 7. Type hints everywhere; narrow over generic

Not `dict` — `dict[str, JobSettings]`. Not `list` —
`list[CellPick]`. The `FrameGeometry` / `CellPick` dataclasses in
the example scripts are the right pattern: any function returning
or accepting ≥3 related fields gets a dataclass.

## 8. Tests target pure logic; hardware behaviour is verified by example scripts

Unit tests cover translators, geometry math, ROI conversion — pure
Python. The integration contract is the 3 example scripts on real
hardware. **Do not** extend `mock_lasx_api.py` to fake `commands.py`
/ `confirmations.py` — that's exactly where mock-vs-real divergence
has burned the project before.

## 9. Module surface is explicit

Every package module declares `__all__`. Anything not in it is
private — leading underscore. The `driver/__init__.py` re-exports
become an actual contract instead of a leaky surface.

## 10. Errors have specific types and propagate

No bare `except:`, no `except Exception:` without re-raising. No
silent `pass`. The `driver/errors.py` hierarchy used consistently.
If an example script can't continue, it crashes with a clear
message — not retries silently.

---

## How to use this document

When reviewing or writing a cleanup commit, check each rule against
the diff. A commit that doesn't pass these is sent back, not merged.

Rules that turn out to be wrong for this codebase get edited here,
with a short note in the commit message — but the bar to soften a
rule is "we found a concrete example where following it produced
worse code", not "this is annoying".
