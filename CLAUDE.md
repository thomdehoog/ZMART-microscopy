# SMART

Microscope automation framework.

## Structure

- `controller/vendor/leica/lasx/` — Leica STELLARIS confocal driver
- `controller/vendor/leica/test/` — Driver tests
- `analysis/post_acquisition/` — Post-acquisition analysis
- `analysis/realtime/` — Real-time analysis during acquisition

## Leica LASX Driver

- **Package**: `controller/vendor/leica/lasx/`
- **API reference**: `controller/vendor/leica/README.md`
- **All commands return** a result dict with `success`, `confirmed`, `message`, `timing`, `logs`

## Code quality

Before finalizing any change, review it for cleanliness: every fix should be structural, not bolted on. Prefer refactoring the underlying design over adding special cases, branching logic, or conditional workarounds. If a new parameter creates a parallel code path instead of unifying an existing one, rethink the approach. The goal is code that looks like it was always designed this way — not code that reveals its history of patches.

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
- There should be one — and preferably only one — obvious way to do it.
- If the implementation is hard to explain, it's a bad idea.
- If the implementation is easy to explain, it may be a good idea.

## Environment

- **Git**: `C:/ProgramData/MinicondaZMB/Library/cmd/git.exe`
- **Conda env**: `C:/ProgramData/MinicondaZMB/envs/lasxapi_extended`
