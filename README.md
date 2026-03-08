# SMART

Microscope automation framework.

## Structure

- `controller/` — Microscope control and hardware drivers
  - `vendor/leica/lasx/` — Leica STELLARIS confocal driver
- `analysis/` — Data analysis pipelines
  - `post_acquisition/` — Post-acquisition analysis
  - `realtime/` — Real-time analysis during acquisition
