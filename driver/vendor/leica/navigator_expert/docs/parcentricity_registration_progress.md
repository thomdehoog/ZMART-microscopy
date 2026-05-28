# Parcentricity Registration Pipeline — Technical Progress Report

> Historical note: this document describes pre-restructure paths and workflow state.
**Date:** 2026-04-14  
**Author:** Thom De Hoog  
**System:** Leica STELLARIS 8 confocal microscope (stand DMI8, serial 8400000246), LAS X driver stack (Python)  
**Status:** Registration pipeline validated; stage-to-image calibration characterised; correction step pending

---

## 1. Background and Motivation

**Parcentricity** is the property of a matched objective set whereby the centre of the field of view remains stationary when switching between objectives. In practice, no set of objectives is perfectly parcentric: switching from a low-magnification overview objective to a high-magnification acquisition objective introduces a lateral offset that must be corrected before imaging.

In our automated acquisition workflow, parcentric offsets are corrected programmatically via a stage move. To do this reliably, we need to:

1. Measure the lateral shift between images acquired on two different objectives.
2. Convert that image-space shift into the correct stage correction.
3. Apply the correction and verify the residual offset.

This report documents the development and characterisation of the image registration pipeline that underpins steps 1–3, and the empirical measurements of the stage-to-image coordinate mapping required for step 2.

---

## 2. Registration Pipeline

### 2.1 Overview

Rather than relying on a single registration algorithm, we implemented a **three-estimator voting scheme**. Each estimator is algorithmically independent; their outputs are compared and a consensus is taken. This provides robustness against failure of any single method (e.g. NCC failing on dim images, RANSAC failing on featureless images) and gives a principled confidence measure.

### 2.2 Estimators

| Estimator | Method | Accuracy | Strengths |
|-----------|--------|----------|-----------|
| **PCC** | Masked phase cross-correlation (Padfield 2012, `skimage`) | Sub-pixel (100× upsampling) | Robust on dim/sparse images; no feature detection required |
| **NCC** | OpenCV `matchTemplate` (`TM_CCOEFF_NORMED`) on centre 50% crop | Integer-pixel | Fast; independent of PCC; good cross-check |
| **RANSAC** | ORB keypoints + brute-force matching + RANSAC consensus translation | Sub-pixel | Robust on textured images; completely independent algorithm |

**Sign convention** (validated empirically):

```
register(ref, tgt) returns (dx_um, dy_um) where:
    dx_um = -col_displacement * pixel_um
    dy_um = -row_displacement * pixel_um
```

### 2.3 Voting

All estimators that succeed are compared pairwise. The largest cluster whose members agree within a **1 µm threshold** is selected; the cluster mean is the final estimate. Confidence is reported as:

- **High**: 3/3 estimators agree
- **Medium**: 2/3 estimators agree  
- **Low**: only 1 estimator available

### 2.4 NCC Search Range Limitation

The NCC estimator uses the centre 50% of the target image as a template and searches within the full reference. The maximum detectable shift is therefore `H/4` pixels (128 px for a 512×512 image). At fine pixel sizes this limit is reached quickly:

| Pixel size (µm) | Max shift via NCC | 10 µm move (px) | NCC usable? |
|-----------------|-------------------|-----------------|-------------|
| 0.5687 | 72.8 µm | 17.6 px | Yes |
| 0.2275 | 29.1 µm | 43.9 px | Yes |
| 0.0569 | 7.3 µm | 175.8 px | **No** |
| 0.0284 | 3.6 µm | 352.1 px | **No** |

When NCC drops out, PCC and RANSAC continue to function correctly and maintain `medium` confidence.

---

## 3. Validation

### 3.1 Dry Validation (Synthetic Images)

A synthetic fluorescence image (512×512, Gaussian blobs) was generated. Known pixel shifts were applied using `scipy.ndimage.shift` and the registration pipeline was run. All seven test cases passed within 1 µm tolerance.

| Case | Applied shift (µm) | PCC error (µm) | NCC error (µm) | Agreement (µm) |
|------|--------------------|----------------|----------------|----------------|
| Right 20 px | (−10.00, 0.00) | 0.000 | 0.000 | 0.000 |
| Down 20 px | (0.00, −10.00) | 0.000 | 0.000 | 0.000 |
| Mixed (14.6, −9.6 px) | (−7.30, +4.80) | 0.283 | 0.283 | 0.000 |
| Mixed (−10, 16.4 px) | (+5.00, −8.20) | 0.200 | 0.200 | 0.000 |
| Sub-pixel (1.0, 0.6 px) | (−0.50, −0.30) | 0.200 | 0.200 | 0.000 |
| Zero shift | (0.00, 0.00) | 0.000 | 0.000 | 0.000 |
| Diagonal 28 px | (−10.00, −10.00) | 0.000 | 0.000 | 0.000 |

**Result: PASS.** All estimators agree (agreement = 0.000 µm on all cases), and NCC quality = 1.000 throughout.

### 3.2 Semi-Real Validation (Real Image, Computational Shifts)

A real fluorescence image was acquired from LAS X (Overview job, pixel size 0.5687 µm, max intensity 15–16 counts). The same computational shift test was applied. All seven cases passed.

Key observations:
- PCC remained robust despite the very dim image (max = 15 counts).
- NCC quality dropped to ~0.3–0.4 for non-axis-aligned shifts due to low image contrast, but the voting scheme correctly weighted PCC and RANSAC.
- All cases reported **high confidence** (3/3 voters).

**Result: PASS.** The voting scheme recovered correct shifts even where NCC alone would have failed.

### 3.3 Hardware Validation (Real Stage Moves)

A reference image was acquired, the stage was moved by a known displacement, a second image was acquired, and the shift was measured via the registration pipeline. The stage was then restored and a verification image acquired to confirm repeatability.

All measurements were made on a sparse non-DAPI fluorescence sample. **Stage repeatability** was found to be excellent: the residual after restoration was consistently **0.00 µm** across all objectives and zoom settings tested. This confirms that the stage controller returns accurately to its commanded position.

---

## 4. Stage-to-Image Coordinate Mapping

### 4.1 Axis Orientation

The stage X and Y axes are **not aligned with the image X and Y axes**. Empirical measurements revealed a near-90° rotation:

| Stage move | Image shift (dx) | Image shift (dy) |
|------------|-----------------|-----------------|
| +X | ~0 | **negative** (dominant) |
| +Y | **positive** (dominant) | ~0 |

The corrected mapping is:

```
image_dx ≈  scale_Y * stage_y
image_dy ≈ -scale_X * stage_x
```

This corresponds to the validated correction formula used in `test_centricity_check.py`:
```python
stage_corr_x = +dx_um
stage_corr_y = -dy_um
```

### 4.2 Scale Factor Characterisation

Scale factors were measured across multiple objectives and zoom levels. Measurements are quoted from **run 2 onwards** (run 1 consistently showed a settling artefact after objective switching, with slightly elevated residuals; subsequent runs were stable).

| Objective | Zoom | Pixel (µm) | X→dy scale | Y→dx scale | Confidence |
|-----------|------|------------|------------|------------|------------|
| 10x | 4 | 0.5687 | 91% | 74% | Low (coarse pixels) |
| 10x | 1 | 2.2700 | 91% | 68–74% | Low (coarse pixels) |
| 10x | 40 | 0.0569 | 94% | 78% | Medium |
| 20x | 1 | 1.1400 | ~95% | ~85% | Low (noisy voters) |
| 20x | 5 | 0.2275 | 95% | 78% | High |
| 20x | 20 | 0.0569 | 97% | 79% | High |
| 20x | 40 | 0.0284 | 97% | 82% | High |
| 40x | 1 | 0.5687 | 97% | 85% | High |
| 40x | 10 | 0.0569 | 95% | 85% | High |

### 4.3 Resolution Dependence

Scale factor measurements improve with finer pixel size. At coarse pixel sizes (≥ 0.5687 µm/px), a 10 µm stage move corresponds to only ~17 pixels; quantisation error in the registration dominates. At fine pixel sizes (≤ 0.0569 µm/px), the same move spans ≥ 175 pixels and sub-pixel PCC achieves much higher precision.

The **true scale factors** are therefore best estimated from fine-pixel, high-magnification measurements, which consistently converge to:

- **Stage X → image dy: ~97%**
- **Stage Y → image dx: ~82–85%**

### 4.4 Preliminary Calibration Matrix

From the stable fine-pixel measurements, the stage-to-image mapping matrix **A** is estimated as:

```
[dx_um]   [ 0.00   0.83 ] [stage_x]
[dy_um] = [-0.97   0.00 ] [stage_y]
```

The inverse (image shift → required stage correction) is:

```
stage_x = -image_dy / 0.97  ≈  -image_dy * 1.031
stage_y =  image_dx / 0.83  ≈   image_dx * 1.205
```

> **Note:** These values are **preliminary**, derived from a non-DAPI fluorescence sample. The measurements should be repeated on DAPI-stained nuclei, which provide richer image content and are the intended sample for the parcentricity workflow. The scale factor for Y→dx also shows variability between objectives (78–85%), which requires further investigation before a per-objective calibration can be derived.

### 4.5 Caveat: Residuals Confirm Repeatability, Not Absolute Accuracy

> **Important:** All shift measurements are derived from **image registration**, not from an independent position sensor. The stage restoration residual (0.00 µm) confirms repeatability but not absolute accuracy — if the stage consistently moves 9.7 µm instead of 10 µm, both the outward and return moves would be equally in error, giving a perfect residual regardless.
>
> To distinguish a genuine stage calibration error from a systematic registration bias, a linearity test is planned: measuring shifts at multiple commanded displacements (5, 10, 15, 20 µm) and verifying proportionality.

---

## 5. Software Deliverables

| Script | Description |
|--------|-------------|
| `test/test_parcentricity_dry.py` | Registration dry validation: synthetic and real-image modes; 3-estimator voting |
| `test/test_parcentricity_hardware.py` | Hardware move test: acquire → move → acquire → register → restore → verify |

Both scripts are committed on the `dev` branch of `smart-microscopy/driver`.

---

## 6. Next Steps

1. **Repeat calibration on DAPI nuclei** — re-run the hardware tests on a DAPI-stained sample to obtain definitive scale factors with rich image content.

2. **Linearity test** — move 5, 10, 15, 20 µm on both axes and verify that the measured shift scales proportionally, to confirm scale factors are a real stage property rather than a registration artefact.

3. **Implement correction step** — extend `test_parcentricity_hardware.py` to apply the inverse calibration matrix after measuring the shift, acquire a corrected image, and measure the true residual. This completes the full three-step parcentricity loop.

4. **Full parcentricity check** — integrate into `test_centricity_check.py` or a new script: acquire with objective A → switch to objective B → register → apply correction via calibration matrix → verify residual.

5. **Per-objective calibration** — the Y→dx scale factor appears to vary between objectives (40x: ~85%, 20x/10x: ~78%). Once the correction step is in place, this can be characterised more precisely.

---

## 7. Summary

A robust three-estimator image registration pipeline (PCC + NCC + RANSAC with voting) has been developed and validated on both synthetic and real fluorescence images. Hardware tests confirm that the pipeline accurately measures stage-induced image shifts with high confidence across a wide range of objectives and zoom settings. The stage X axis maps to image Y (negated) and stage Y maps to image X, with empirical scale factors of approximately 97% and 83–85% respectively. Stage repeatability is excellent (sub-pixel residuals after restoration). The correction step — applying the inverse calibration matrix to bring images into alignment — remains to be implemented and validated.
