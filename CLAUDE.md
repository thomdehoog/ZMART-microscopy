# LASX Driver v6

Python driver for the Leica STELLARIS confocal microscope.

- **Package**: `lasx/` (or `import driver as drv`)
- **README.md** has the full API reference
- **All commands return** a result dict with `success`, `confirmed`, `message`, `timing`, `logs`

## Environment

- **Git**: `C:/ProgramData/MinicondaZMB/Library/cmd/git.exe`
- **Conda env**: `C:/ProgramData/MinicondaZMB/envs/lasxapi_extended`

## Loadable Prompts

Context-specific instructions live in `prompts/`. Ask me to load one when needed:

- `prompts/microscope-control.md` — Microscope control mode: connection boilerplate, stage limits, script patterns, tile geometry. Load this when working at the microscope.
