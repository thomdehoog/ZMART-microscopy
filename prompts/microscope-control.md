# Microscope Control Mode

When the user asks to do something with the microscope (move stage, acquire images, change settings, read status, etc.), **write a self-contained Python script and execute it** — do not just show code or explain what to do. The user expects direct action.

## Connection Boilerplate

Every script must start with this pattern:

```python
from LasxApi import PYLICamApiConnector as lasx_api
import driver as drv

client = lasx_api.LasxApiClientPyModel
client.Connect("PythonClient")
assert drv.ping(client), "LAS X not responding"
```

## Stage Safety Limits

Must be set before any `move_xy` or `move_z` call:

```python
drv.set_stage_limits(
    x_min=1000, x_max=130000,
    y_min=1000, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)
```

## Script Pattern

A typical script:
1. Connect (boilerplate above)
2. Get the currently selected job: `job = drv.get_selected_job(client)` → use `job["Name"]`
3. Execute the requested operation (e.g. `drv.set_pinhole_airy(client, job_name, 0, 5.0)`)
4. Print the result so the user sees what happened

If the user doesn't specify a job name, use the currently selected job.
If the user doesn't specify a setting_index, default to 0.

## Tile Geometry

For any multi-position or tiling work, use `parse_tile_geometry(settings)` to get the physical tile dimensions from the current job. Never hardcode FOV sizes — they depend on zoom, objective, and format.

```python
settings = drv.get_job_settings(client, job_name)
geo = drv.parse_tile_geometry(settings)
# geo = {
#   tile_w_um, tile_h_um     — tile size in um
#   pixel_w_nm, pixel_h_nm   — pixel size in nm
#   pixel_w_um, pixel_h_um   — pixel size in um
#   pixels_x, pixels_y       — pixel count
#   bbox                     — {x_min, x_max, y_min, y_max} in um
# }
```

Use `tile_w_um` / `tile_h_um` as the step size so tiles connect without gaps or overlap.

## Key Functions

- Read-only: `ping`, `get_scan_status`, `get_jobs`, `get_job_settings`, `get_hardware_info`, `get_xy`
- Job settings: `set_zoom`, `set_scan_speed`, `set_scan_resonant`, `set_image_format`, `set_objective`, `set_scan_mode`, ...
- Optical: `set_pinhole_airy`, `set_detector_gain`, `set_laser_intensity`, ...
- Movement: `move_xy`, `move_z`
- Acquisition: `acquire`, `select_job`
- Geometry: `parse_tile_geometry` (tile size, pixel size, bounding box from raw settings)
- Parsing: `make_changeable_copy` (transforms raw settings JSON into navigable dict)
- **README.md** has the full API reference
