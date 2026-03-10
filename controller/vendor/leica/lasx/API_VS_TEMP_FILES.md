# LAS X Data Sources: API vs Temp Files

## Overview

The LAS X CAM API and the DataContainer temp files serve complementary roles:

- **API** → control the microscope (trigger actions, change settings, read current state)
- **Temp files** → observe what happened (read pixels, verify quality, get physical metadata)

The biggest gap: **the API cannot return acquired image pixels**. You can
trigger an acquisition, but the only way to read the result is from the
temp files (or by exporting from LAS X to disk).

---

## Unique to Temp Files (NOT available through API)

| Data | Where | Why it matters |
|------|-------|---------------|
| **Actual pixel data** | MMF files | The API has no image readback command. Temp MMF files are the only way to access acquired pixels without manual export from LAS X. |
| **Image pyramids** | MMF files (OBJ+1, +2, ...) | Pre-built multi-resolution thumbnails (8-bit Gray, halved per level). Essential for a fast web viewer. The API knows nothing about these. |
| **Per-frame intensity stats** | FrameProperties objects | Min/max/sum intensity per frame — instant quality check without reading full pixel data. Not exposed by the API. |
| **Pixel size / FOV in meters** | `<DimensionDescription>` Origin + Length | Exact physical dimensions of each image. The API gives `format` ("512 x 512") and `zoom`, but not the physical extent in meters. |
| **Historical scan settings** | `<HardwareSetting>` per image | The API reads the *current* microscope state. Temp files record the *actual* settings used for each specific acquisition — critical when settings change between tiles. |
| **Spectral/detector curves** | OBJ 20-29 (DimID=4, 32-bit float) | 1024-point detector sensitivity spectra for each channel. Not available through any API endpoint. |
| **Carrier/plate geometry** | `<Carrier>` in CarrierInfo attachment | Well plate layout: rows, columns, sector dimensions, center position. No API endpoint for carrier info. |
| **Object hierarchy (CLD tree)** | CLD files | Parent-child links: which pyramids, histograms, and frame properties belong to which image. |
| **Dye database** | OBJ 51 (NiceDyeDisplayNameList) | Complete list of all fluorophore names known to LAS X. |
| **UI/application state** | OBJ 42 (Subject attributes) | Current workflow tab, autosave settings, viewer layout, scalebar config, LUT mode, save directory. |
| **Pixel dwell time** | `PixelDwellTime` in HardwareSetting | Actual dwell time in seconds. The API gives scan speed (Hz) but not the computed per-pixel dwell time. |
| **Bidirectional scan phase** | `PhaseX` in HardwareSetting | Phase correction value used for bidirectional scan alignment. |
| **Scan field origin** | `PanFirstDim` / `PanSecondDim` | Pan offset of the scan field from center. |
| **System serial number** | `SystemSerialNumber` in HardwareSetting | Identifies the physical microscope (e.g., "STELLARIS SIMULATOR"). |

---

## Available Through Both API and Temp Files

| Data | API source | Temp file source | Notes |
|------|-----------|-----------------|-------|
| Stage position X/Y | `get_xy()` → `x`, `y` (meters) | `StagePosX` / `StagePosY` in HardwareSetting | API gives live position; temp gives position at capture time |
| Z position | `get_job_settings()` → `zPosition` dict | `ZPosition` in HardwareSetting | API gives current; temp gives per-image |
| Objective name | `get_job_settings()` → `objective.name` | `ObjectiveName` in HardwareSetting | Both identical |
| Numerical aperture | `get_hardware_info()` → objectives list | `NumericalAperture` in HardwareSetting | |
| Zoom | `get_job_settings()` → `zoom.current` | `Zoom` in HardwareSetting | |
| Scan speed | `get_job_settings()` → `scanSpeed.value` | `ScanSpeed` in HardwareSetting | |
| Scan mode | `get_job_settings()` → `scanMode` | `ScanMode` in HardwareSetting | |
| Image format | `get_job_settings()` → `format` (string) | `InDimension` / `OutDimension` | API returns "512 x 512"; temp gives integers |
| Bit depth | Implicit from format | `BitSize` / `Resolution` | Temp is explicit |
| Pinhole | `get_job_settings()` → `pinholeAiry.value` | `Pinhole` (meters) + `PinholeAiry` (AU) | Temp gives both physical and Airy units |
| Frame averaging | `get_job_settings()` → `frameAverage` | `FrameAverage` in HardwareSetting | |
| Line averaging | `get_job_settings()` → `lineAverage` | `LineAverage` in HardwareSetting | |
| Frame accumulation | `get_job_settings()` → `frameAccumulation` | `FrameAccumulation` in HardwareSetting | |
| Detector gain | `get_job_settings()` → `activeDetectors[].gain` | Detector elements in HardwareSetting XML | |
| Laser intensity | `get_job_settings()` → `activeLaserLines[].intensity` | LaserLineSetting elements in HardwareSetting | |
| Scan field rotation | `get_job_settings()` → `scanFieldRotation.value` | `RotatorAngle` in HardwareSetting | |
| Sequential mode | `get_job_settings()` → `sequentialMode` | `IsEnabledForSequentialScanning` | |
| Z-stack definition | `get_job_settings()` → `stack` dict | DimID=3 in DimensionDescription | |
| Immersion type | `get_hardware_info()` → objective details | `Immersion` in HardwareSetting | |
| Resonant scanner | `get_job_settings()` → `scanSpeed.isResonant` | `IsResonantScanner` in HardwareSetting | |

**Key difference**: the API reads the *current* microscope state (what it's
set to right now). The temp files record the *actual* state at the moment
each image was acquired. For a single image this is the same, but during
a tile scan or time series, settings may change between frames — only the
temp files preserve the per-frame truth.

---

## Only Available Through API (NOT in temp files)

| Data | API function | Description |
|------|-------------|-------------|
| **Scanner status** | `get_scan_status()` | Real-time state: Idle, Scanning, Ready |
| **Hardware inventory** | `get_hardware_info()` | All objectives in turret, all laser lines, detector types, filter wheels, stage range |
| **Job list** | `get_jobs()` | Named experiment definitions and which is selected |
| **Job selection** | `select_job()` | Switch active experiment |
| **Command execution** | `acquire()`, `move_xy()`, `move_z()` | Trigger scans, move stage, change settings |
| **Settings modification** | `set_zoom()`, `set_laser_intensity()`, etc. | Change any microscope parameter |
| **Confirmation/readback** | `_confirm_*()` functions | Poll until setting matches expected value |
| **Application config** | `get_lasx_settings()` (from XML on disk) | Export config, CAM settings, stage calibration, rare event detection |
| **Connection health** | `ping()` | Verify API connectivity |

---

## Data Flow for a Web Viewer

```
User clicks "Acquire"
        │
        ▼
  ┌─────────────┐     PyApiAcquireJob      ┌─────────────┐
  │  Web UI      │ ───────────────────────> │  LAS X API  │
  │  (frontend)  │                          │  (CAM)      │
  └──────┬───────┘                          └──────┬──────┘
         │                                         │
         │  websocket: "acquisition started"       │ scanner runs
         │                                         │
         │                                         ▼
         │                                  ┌─────────────┐
         │                                  │ DataContainer│
         │                                  │ Server       │
         │                                  └──────┬──────┘
         │                                         │
         │                                         │ writes to D:\Temp
         │                                         ▼
         │  ┌──────────────┐  file watch    ┌─────────────┐
         │  │ temp_watcher  │ <──────────── │  OBJ + MMF  │
         │  └──────┬───────┘               │  + CLD files │
         │         │                        └─────────────┘
         │         │ new image event
         │         ▼
         │  ┌──────────────┐
         │  │ session_state │  parses metadata, builds spatial index
         │  └──────┬───────┘
         │         │
         │         │ tile ready event
         │         ▼
         │  ┌──────────────┐
         │  │ tile_server   │  serves pyramid as PNG tiles over HTTP
         │  └──────┬───────┘
         │         │
         │         │  /tiles/{id}/{z}/{x}/{y}.png
         ▼         ▼
  ┌─────────────────────┐
  │  OpenSeadragon /     │
  │  Leaflet viewer      │  displays tiles at correct stage coordinates
  │  (frontend)          │
  └─────────────────────┘
```

### What each layer provides

| Layer | Source | Provides |
|-------|--------|----------|
| **API** | CAM commands | Control: acquire, move, configure |
| **API** | `get_job_settings()` | Current settings for UI controls |
| **API** | `get_xy()` | Live stage position for crosshair |
| **API** | `get_hardware_info()` | Objective list, laser list for dropdowns |
| **Temp** | OBJ HardwareSetting | Per-tile metadata (position, FOV, settings at capture) |
| **Temp** | MMF files | Actual pixel data for display |
| **Temp** | Pyramid MMF files | Multi-resolution tiles for smooth zoom |
| **Temp** | FrameProperties | Quick quality stats (saturation, exposure) |
| **Temp** | CLD tree | Image-to-pyramid linkage |
| **Temp** | Carrier info | Well plate overlay geometry |

### Summary

The API is the **steering wheel** — it controls the microscope.
The temp files are the **dashboard** — they show what actually happened.
A complete web viewer needs both.
