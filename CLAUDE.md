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

## Environment

- **Git**: `C:/ProgramData/MinicondaZMB/Library/cmd/git.exe`
- **Conda env**: `C:/ProgramData/MinicondaZMB/envs/lasxapi_extended`
