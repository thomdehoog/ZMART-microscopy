# LAS X DataContainer Temp Files — Architecture Reference

## Overview

Leica LAS X stores all acquired image data in memory-mapped temp files managed
by `LMSDataContainerServerV2.exe`. These files contain everything needed to
build an independent viewer: pixel data, image pyramids, stage positions, scan
settings, and the full object hierarchy.

This document is a complete reference for building modules that read this data.

---

## System Layout

```
D:\Temp\                              ← configurable, port 8892
├── V2LMSDC_OBJ<id>_<pid>.tmp        ← object metadata (XML, UTF-16-LE)
├── V2LMSDC_MMF<id>_<off>_<pid>.tmp  ← pixel/data payloads (raw binary)
├── V2LMSDC_CLD<id>_<pid>.tmp        ← parent→child links (13-byte records)
└── <hexname>.tmp                     ← PE/DLL process memory (ignore)
```

- `<pid>` is the DataContainer server process ID (decimal or hex, e.g. `5984` or `8f1c`)
- `<id>` is the DataContainer object ID (integer, monotonically increasing per session)
- `<off>` in MMF files is the byte offset within the logical data stream (usually `0`)

---

## File Format Details

### OBJ files — XML metadata

Binary header (variable, ~20 bytes) followed by UTF-16-LE XML.
Find the XML start by searching for the byte sequence:

```
b"<\x00D\x00a\x00t\x00a\x00>"   # "<Data>" in UTF-16-LE
```

The XML ends at `</Data>`. After the XML there is a binary trailer containing:
- Object type name (encoded in a proprietary format)
- Application tag (`LAS AF`)
- User name
- UUID
- Save flags (e.g., `PreventLIFSave`, `nosave_nocopy`)

### MMF files — raw pixel data

No header. Flat binary array of pixel values. Data type and dimensions must
come from the corresponding OBJ file.

Pixel ordering is row-major (C order): X increments fastest, then Y, then Z,
then channels. The `BytesInc` attribute in each `<DimensionDescription>`
confirms the stride.

Common dtypes:
- `Resolution="8"`  → `uint8`
- `Resolution="16"` → `uint16`
- `Resolution="32"` → `float32`

Some objects have multiple MMF chunks (e.g., `MMF69_0` and `MMF69_524288`).
The `<off>` value is the byte offset — concatenate chunks in offset order
to reconstruct the full data array.

### CLD files — object hierarchy

Each record is 13 bytes:

```
[1 byte type] [4 bytes LE uint32] [4 bytes LE uint32] [4 bytes child_obj_id LE uint32]
```

The third uint32 is the child OBJ ID. The first two appear to be constant
flags (`83886080`, `704643072`). To find all children of an object, read its
CLD file and extract every third uint32.

---

## Object Hierarchy (observed structure)

```
OBJ 1 (root)
├── OBJ 4  — Session config (version, user paths)
├── OBJ 5  — Project config (naming, format profiles)
├── OBJ 6  — Experiment: "Open Files"
├── OBJ 7  — Experiment: "Favorites"
└── OBJ 8  — Experiment: "Network"

OBJ 2 (project tree root)
├── OBJ 11 — Folder: "OpenFiles"
│   └── OBJ 12 — Folder: "Libraries"
│       ├── OBJ 15 — Folder: user home (\\homes.core.uzh.ch\...)
│       ├── OBJ 16 — Folder: Desktop
│       ├── OBJ 17 — Folder: Pictures
│       ├── OBJ 18 — Folder: Videos
│       └── OBJ 19 — Folder: Music
├── OBJ 13 — Folder: "Favorites"
├── OBJ 14 — Folder: "Network"
├── OBJ 43 — Folder: drive C:
│   └── OBJ 44 — child: "parsing..."
├── OBJ 45 — Folder: drive D:
│   └── OBJ 46 — child: "parsing..."
├── OBJ 47 — Folder: drive E:
│   └── OBJ 48 — child: "parsing..."
└── OBJ 49 — Folder: drive Z:
    └── OBJ 50 — child: "parsing..."

OBJ 64 (experiment "Hidden")
├── OBJ 69 — Acquired image (512x512 16-bit)
│   ├── OBJ 70 — Pyramid 256x256
│   │   └── OBJ 71 — Pyramid 128x128
│   │       └── OBJ 72 — Pyramid 64x64
│   │           └── OBJ 73 — Pyramid 32x32
│   ├── OBJ 74 — Histogram/LUT (65536x1 32-bit)
│   └── OBJ 68 — FrameProperties (min/max/sum intensity)
└── OBJ 80 — Acquired image (512x512 16-bit, with CarrierInfo)
    ├── OBJ 81 — FrameProperties
    └── OBJ 82 — FrameProperties

Standalone objects:
├── OBJ 9-10  — Global ROISets
├── OBJ 20-29 — Spectral/detector curves (DimID=4 and DimID=13)
├── OBJ 30-37 — ROISets (viewer, bleach points)
├── OBJ 31    — Test palette image (8-bit, DimID=4, 16 elements)
├── OBJ 32-33 — Subject / processing queue (empty)
├── OBJ 42    — UI/application state
└── OBJ 51    — Dye database (complete fluorophore list)
```

---

## Object Types Reference

### Image objects (contain `<Image>` element)

**Acquired images** — the actual microscopy data:
- Channels with colored LUT (Green, Red, Cyan, etc.) and typically 16-bit
- DimID=1 (X) and DimID=2 (Y), optionally DimID=3 (Z for z-stacks)
- Large OBJ file (~128 KB) because it includes a `<HardwareSetting>` attachment
  with the full microscope state at capture time

**Pyramid thumbnails** — downsampled versions for fast display:
- Always 8-bit Gray, single channel
- Dimensions halved independently per level down to ~32px shortest side
- Linked to parent via CLD chain
- DimID=10 present (pyramid/stack index)
- Marked with `PreventLIFSave` in trailing metadata

**Histogram/LUT objects** — 65536x1 32-bit:
- Width=65536, Height=1
- Used for display LUT mapping

**Spectral data** — detector sensitivity curves:
- DimID=4 (spectral, 1024 or 129 elements) and/or DimID=13 (2 elements)
- 32-bit float
- One pair per detector channel (OBJ 20-29 = 5 channels × 2 objects each)

### Non-image objects

| XML root element | Object type | Content |
|-----------------|-------------|---------|
| `<Subject>` (with attributes) | Session root | LAS X version, user paths, installed modules |
| `<Subject>` (with `DoWorkWithProjects`) | Project config | Save format, naming, export profiles |
| `<Subject>` (with UI attributes) | UI state | Workflow mode, viewer config, autosave settings |
| `<Subject><NiceDyeDisplayNameList>` | Dye database | All known fluorophore names |
| `<Subject><processing>` | Processing queue | Job queue state (usually empty) |
| `<Subject/>` (empty) | Empty subject | Placeholder |
| `<Experiment>` | Experiment ref | Path to experiment definition + timestamp |
| `<Generic>` (GenericFolderInfo) | Folder tree | IOManager folder structure with drive/path entries |
| `<ROISet>` | ROI definitions | Region of interest and bleach point sets |
| `<SimpleListInMemory>` | FrameProperties | Per-frame intensity statistics (min, max, sum) |

---

## HardwareSetting — Full Microscope State Per Image

Each acquired image's OBJ file contains an
`<Attachment Name="HardwareSetting">` with an
`<ATLConfocalSettingDefinition>` element. This records the *actual* microscope
configuration used for that specific acquisition.

### Stage position

| Attribute | Unit | Example | Description |
|-----------|------|---------|-------------|
| `StagePosX` | meters | `0.066080000000` | Stage X (66.08 mm) |
| `StagePosY` | meters | `0.040920000000` | Stage Y (40.92 mm) |
| `ZPosition` | meters | `-0.000000000238` | Z focus position |
| `StageRangeX` | meters | `0.127` | Full X travel (127 mm) |
| `StageRangeY` | meters | `0.083` | Full Y travel (83 mm) |

### Optics

| Attribute | Example | Description |
|-----------|---------|-------------|
| `ObjectiveName` | `HC PL APO CS 10x/0.40 DRY` | Full objective string |
| `ObjectiveNumber` | `506511` | Leica part number |
| `Magnification` | `10` | Magnification factor |
| `NumericalAperture` | `0.40` | NA |
| `Immersion` | `DRY` | DRY / Water / Oil |
| `Zoom` | `1` | Scan zoom factor |
| `BaseZoom` | `0.75` | Base zoom (minimum zoom) |
| `Pinhole` | `0.0003980125` | Pinhole diameter (meters) |
| `PinholeAiry` | `0.9999` | Pinhole in Airy units |
| `RotatorAngle` | `0` | Scan field rotation (degrees) |

### Scan configuration

| Attribute | Example | Description |
|-----------|---------|-------------|
| `ScanMode` | `xyz` | xy, xyz, xzy, xt, xyt, etc. |
| `ScanSpeed` | `600` | Scan speed (Hz) |
| `PixelDwellTime` | `9.608e-07` | Dwell time per pixel (seconds) |
| `InDimension` | `512` | Pixels per line |
| `OutDimension` | `512` | Lines per frame |
| `BitSize` | `16` | Bit depth |
| `ScanDirectionXName` | `Bidirectional` | Uni- or bidirectional scanning |
| `FrameAverage` | `1` | Frame averaging count |
| `LineAverage` | `1` | Line averaging count |
| `FrameAccumulation` | `1` | Frame accumulation count |
| `IsResonantScanner` | `0` | 1 = resonant, 0 = galvo |

### System info

| Attribute | Example | Description |
|-----------|---------|-------------|
| `Software` | `LAS X [ BETA ] 4.9.0.30051` | Software version |
| `SystemTypeName` | `SIMULATOR` | System type (STELLARIS 5, SIMULATOR, etc.) |
| `SystemSerialNumber` | `STELLARIS SIMULATOR` | Serial number |
| `HardwareServerVersion` | `Build 30051` | Hardware server build |

### Physical dimensions (from `<DimensionDescription>`)

Each dimension has `Origin` (physical start, meters) and `Length` (physical
extent, meters). Combined with `NumberOfElements`:

```
pixel_size = Length / NumberOfElements
field_of_view = Length
world_x_start = StagePosX + Origin_X    (approximately)
world_x_end = world_x_start + Length_X
```

Example for 512×512 at 10x zoom=1:

```
DimID=1 (X): 512 elements, Length=1.1625e-03 m → pixel=2.27 µm, FOV=1162.5 µm
DimID=2 (Y): 512 elements, Length=1.1625e-03 m → pixel=2.27 µm, FOV=1162.5 µm
```

### Carrier/plate info (when configured)

Present inside `<Attachment Name="CarrierInfo"><Carrier .../>`:

| Attribute | Example | Description |
|-----------|---------|-------------|
| `Round` | `true` | true = round dish, false = rectangular plate |
| `CarrierWidth` | `0.075` | Width in meters (75 mm) |
| `CarrierHeight` | `0.025` | Height in meters (25 mm) |
| `CarrierCenterX` | `0.0635` | Center X in stage coords (meters) |
| `CarrierCenterY` | `0.0435` | Center Y in stage coords (meters) |
| `Rows` | `1` | Number of well rows |
| `Columns` | `1` | Number of well columns |
| `SectorWidth` | `0.015` | Well width (meters) |
| `SectorHeight` | `0.015` | Well height (meters) |
| `FirstSectorX` | `0` | Offset to first well X |
| `FirstSectorY` | `0.002` | Offset to first well Y |
| `SectorDistanceX` | `0` | Well spacing X |
| `SectorDistanceY` | `0` | Well spacing Y |

---

## FrameProperties — Quick Intensity Stats

`<SimpleListInMemory>` objects with columns:

| Column | Unit | Size | Description |
|--------|------|------|-------------|
| `CDCSIMPLELISTINMEMORYDESCRIPTION_ISCOLUMNUSEDCOLDESC` | flag | 1 byte | Column validity flag |
| `MinIntensity` | gray/rgb | 2 bytes | Minimum pixel value |
| `MaxIntensity` | gray/rgb | 2 bytes | Maximum pixel value |
| `SumIntensity` | gray/rgb | 8 bytes | Sum of all pixel values |

Each row = one frame. For z-stacks, there is one row per slice.
Reading these is much faster than loading full pixel data — useful for
saturation detection and exposure validation.

---

## UI/Application State (OBJ 42)

The `<Subject>` element in OBJ 42 stores the full LAS X UI state as
key-value attributes. Selected useful fields:

| Attribute | Example | Description |
|-----------|---------|-------------|
| `WorkFlowBar_WorkflowBar` | `eWFB_Acquire` | Current workflow tab |
| `ImageLoadSave_AutoSaveBaseDataPath` | `C:\Users\t.de\temp` | Autosave directory |
| `ImageLoadSave_UseAutoSave` | `False` | Autosave enabled? |
| `ImageLoadSave_CurrSaveDirectory` | `\\homes.core.uzh.ch\...` | Last save location |
| `ImageLoadSave_CurrSaveFileExtension` | `lif` | Save format |
| `ImageLoadSave_ExperimentName` | `Project` | Project name template |
| `MultipleViewer_ViewMode` | `eMultiplePartitions` | Viewer layout mode |
| `MultipleViewer_SplitRGBChannels` | `False` | Channel split mode |
| `ViewerScalebar_IsVisible` | `False` | Scale bar visibility |
| `ViewerScalebar_Length` | `300` | Scale bar length |
| `ViewerScalebar_Font` | `Arial, 16pt` | Scale bar font |
| `LUTRepository_CurrentLUTMode` | `Default` | LUT display mode |

---

## MMF File Sizes — What to Expect

| Content | Calculation | Size |
|---------|-------------|------|
| Live scan buffer (MMF0) | Fixed allocation | 50 MB |
| 512×512, 1ch, 16-bit | 512×512×2 | 512 KB |
| 1024×1024, 1ch, 16-bit | 1024×1024×2 | 2 MB |
| 2048×2048, 2ch, 16-bit | 2048×2048×2×2 | 16 MB |
| Pyramid (256×256, 8-bit) | 256×256×1 | 64 KB |
| Histogram/LUT (65536×1, 32-bit) | 65536×4 | 256 KB |
| Spectral curve (1024, 32-bit) | 1024×4 | 4 KB |
| FrameProperties (per frame) | 13 bytes/row | ~13 B |
| Hex-named PE dumps | Fixed | 26.6 MB each |

Hex-named files (PE/DLL dumps) dominate disk usage: 24 files × 26.6 MB =
638 MB of useless data. Total useful data for one 512×512 image with
pyramids is ~1.5 MB.

---

## Identification Patterns

How to identify what an OBJ file contains without parsing the full XML:

| Check | Conclusion |
|-------|-----------|
| `<Image` present, LUTName ≠ "Gray", Resolution ≠ "8" | **Acquired image** |
| `<Image` present, LUTName = "Gray", Resolution = "8" | **Pyramid thumbnail** |
| `<Image` present, Width = 65536, Height = 1 | **Histogram/LUT table** |
| `<Image` present, DimID = "4" only (no 1/2) | **Spectral curve** |
| `<SimpleListInMemory` | **FrameProperties** |
| `<ROISet` | **ROI definitions** |
| `<Experiment` | **Experiment reference** |
| `<Generic` with GenericFolderInfo | **Folder tree node** |
| `<Subject` with NiceDyeDisplayNameList | **Dye database** |
| `<Subject` with WorkFlowBar | **UI state** |
| `<Subject` with InstalledVersion | **Session config** |
| `<Subject` with DoWorkWithProjects | **Project config** |

---

## Coordinate System

All physical values are in **SI units (meters)**.

```
Stage coordinates (meters):
  X: 0 → 0.127  (127 mm travel)
  Y: 0 → 0.083  (83 mm travel)
  Z: varies by objective working distance

Image origin in stage space:
  top-left corner = (StagePosX + Origin_X, StagePosY + Origin_Y)
  bottom-right    = (top-left_X + Length_X, top-left_Y + Length_Y)

Pixel to world:
  world_x = Origin_X + pixel_col * (Length_X / Width)
  world_y = Origin_Y + pixel_row * (Length_Y / Height)
```

For the web viewer, convert meters → micrometers (×1e6) or millimeters (×1e3)
for display.

---

## Planned Modules

### `temp_watcher.py` — Real-time file system monitor
- Watch D:\Temp for new/modified V2LMSDC_OBJ files
- Emit structured events: `ImageAcquired`, `SessionStarted`
- Use `watchdog` library for cross-platform file watching
- Debounce rapid file changes during live scanning

### `session_state.py` — In-memory session model
- Parse CLD tree to build full object hierarchy
- Maintain spatial index of all images (stage position + FOV bounding box)
- Track session metadata: objective, zoom, carrier info
- Provide queries: "images in region", "latest image", "all images for well A1"

### `coord_mapper.py` — Coordinate transforms
- Stage coords (meters) ↔ image coords (pixels) ↔ screen coords
- Handle carrier/plate geometry (well grid → stage positions)
- Calculate tile overlaps for stitching

### `tile_server.py` — HTTP tile endpoint for web viewers
- Serve pyramid levels as PNG tiles: `/tiles/{image_id}/{z}/{x}/{y}.png`
- Auto-contrast uint16 → uint8 for display
- Compatible with OpenSeadragon / Leaflet tile layer
- Cache converted tiles in memory (LRU)

### `quality_monitor.py` — Acquisition quality feedback
- Read FrameProperties for instant min/max/saturation stats
- Compare requested vs actual HardwareSetting
- Flag: saturation, underexposure, empty frames, wrong objective

---

## Key Paths (this system)

```
Temp directory:     D:\Temp
DC Server:          C:\Program Files\Leica Microsystems CMS GmbH\Services\DataContainer\Bin\Service\LMSDataContainerServerV2.exe
DC Server log:      C:\ProgramData\Leica Microsystems\LMSDataContainerService\DCServerLogFileOld.log
LAS X log:          C:\ProgramData\Leica Microsystems\LAS X\LAS X.log
LAS X user config:  C:\Users\t.de\AppData\Roaming\Leica Microsystems\LAS X\
Python env:         C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe
```
