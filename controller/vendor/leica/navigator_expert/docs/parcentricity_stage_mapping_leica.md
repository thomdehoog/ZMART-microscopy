# Stage-to-Image Coordinate Mapping on the Leica STELLARIS 8
## Technical Observations for Discussion with Leica

**Date:** 14 April 2026  
**Author:** Thom De Hoog  
**Institution:** Center for Microscopy and Image Analysis (ZMB), University of Zurich  
**Instrument:** Leica STELLARIS 8 confocal microscope, stand DMI8, serial number 8400000246, LAS X software  

---

## Executive Summary

During the development of an automated parcentricity correction workflow for the Leica STELLARIS 8, we empirically characterised the relationship between commanded stage displacements (in µm, as reported by LAS X) and the corresponding lateral shifts observed in acquired images (measured by sub-pixel image registration). Two systematic findings are reported:

1. **Axis orientation:** A near-90° rotation exists between the stage coordinate system and the image coordinate system. Stage X displacements appear predominantly in the image Y direction, and vice versa. This is consistent with the scan orientation of the instrument but is worth confirming as expected behaviour.

2. **Scale factor discrepancy:** Stage displacements do not translate 1:1 into image-space displacements. The measured scale factors at high magnification (where measurement precision is highest) are approximately **97% on the X→Y axis** and **83–85% on the Y→X axis**. The Y-axis discrepancy in particular (15–17% below expected) is consistent and reproducible across objectives and zoom levels. We would appreciate Leica's perspective on whether these values are within specification, and whether a recalibration procedure is available.

---

## 1. Context and Motivation

We are developing an automated acquisition pipeline on the Leica STELLARIS 8 that programmatically corrects for parcentric offsets when switching between objectives. This requires converting a measured image-space shift (obtained by registering images from two different objectives) into the correct stage move. To do this accurately, the mapping between stage coordinates and image coordinates must be known.

To characterise this mapping, we performed the following experiment repeatedly across multiple objectives and zoom levels:

1. Acquire a reference image at a known stage position.
2. Command a known stage displacement (10 µm in X only, or 10 µm in Y only).
3. Acquire a second image at the displaced position.
4. Measure the image-space shift between the two images using sub-pixel image registration.
5. Return the stage to the original position and verify the registration reads back to zero (repeatability check).

All measurements were performed using the **Overview** scanning job on a sparse fluorescence sample. Image registration used a three-method voting scheme (masked phase cross-correlation, normalised cross-correlation, and RANSAC-based feature matching) to ensure robustness and provide a confidence estimate.

---

## 2. Finding 1 — Stage and Image Axes Are Rotated ~90°

When a 10 µm displacement was commanded in the **stage X direction**, the resulting image shift appeared almost entirely in the **image Y direction** (and vice versa for stage Y → image X). Representative measurements:

| Commanded move | Measured image shift (X) | Measured image shift (Y) |
|----------------|--------------------------|--------------------------|
| Stage +X, 10 µm | −0.62 µm | −9.67 µm |
| Stage +Y, 10 µm | +8.53 µm | −0.47 µm |

The dominant displacement is in the perpendicular image axis in both cases, confirming an approximately 90° rotation between coordinate systems. The sign convention (stage +X → image −Y; stage +Y → image +X) is consistent across all measurements.

**Question for Leica:** Is this axis rotation an expected and documented property of the STELLARIS 8 scan geometry? Is it configurable, and if so, what determines the orientation?

---

## 3. Finding 2 — Scale Factor Discrepancy

The magnitude of the measured image shift does not equal the commanded stage displacement. At high magnification (fine pixel size), where measurement precision is highest, the measured shifts were consistently:

- **Stage X → image Y: ~97%** of the commanded displacement
- **Stage Y → image X: ~83–85%** of the commanded displacement

### 3.1 Reproducibility

These values were reproduced with good consistency across repeated runs. Results from run 2 onwards (after an initial settling run following objective switching, described in Finding 3) were mutually consistent, with the range across repeated measurements remaining below 0.3 µm in all cases.

### 3.2 Resolution Dependence

The apparent scale factors improved at higher magnification (finer pixel size), indicating that the discrepancy at low magnification is partly due to registration precision rather than a larger physical effect. Results at fine pixel sizes (≤ 0.06 µm/px) were used for the final estimates. The values below are representative single measurements from stable runs at each condition.

| Objective | Zoom | Pixel size (µm) | X→image Y | Y→image X |
|-----------|------|-----------------|-----------|-----------|
| 10x | 4× | 0.5687 | 91% | 74% |
| 10x | 40× | 0.0569 | 94% | 78% |
| 20x | 5× | 0.2275 | 95% | 78% |
| 20x | 20× | 0.0569 | 97% | 79% |
| 20x | 40× | 0.0284 | 97% | 82% |
| 40x | 1× | 0.5687 | 97% | 85% |
| 40x | 10× | 0.0569 | 95% | 85% |

The scale factors converge at fine pixel sizes to ~97% (X axis) and ~83–85% (Y axis). The variability in the Y-axis figure across objectives (78–85%) warrants further investigation; it may partly reflect remaining measurement precision limitations and will be characterised more precisely once correction validation is in place.

### 3.3 Stage Repeatability is Excellent

The stage returns accurately to its home position after each test: residual shifts after restoration were consistently **0.00–0.07 µm** (sub-pixel at all magnifications tested). This confirms the stage encoder and controller are performing well. The scale factor discrepancy is therefore not a repeatability issue — the stage arrives at its commanded position reliably, but the commanded position may not correspond to the expected physical displacement.

### 3.4 Pixel Size Is Correct

We verified that the pixel size reported by LAS X matches the value shown in the scan settings UI (568.74 nm for the 10× objective at zoom 4). The pixel size is not the source of the discrepancy.

**Question for Leica:** Are the observed scale factors (97% and 83–85%) within the factory specification for this instrument? Is there a stage calibration procedure (e.g. in LAS X or the service menu) that could bring these values closer to 100%? The 15–17% discrepancy on the Y axis in particular would introduce meaningful errors in our automated stage correction workflow unless it is explicitly accounted for.

---

## 4. Finding 3 — First-Run Settling After Objective Switch

In every test series, the first measurement after an objective switch produced a slightly different result (shifted by 0.5–1.0 µm) compared to subsequent runs, which were mutually consistent. By the second or third run, all measurements stabilised. This suggests that the stage or objective turret requires one move-and-return cycle to fully settle after an objective change.

**Question for Leica:** Is this settling behaviour expected following an objective switch? Is there a recommended dwell time or confirmation mechanism after the objective switching command before commanding stage moves?

---

## 5. Preliminary Calibration Matrix

Based on the measurements at fine pixel sizes, the empirical stage-to-image mapping is:

```
image_shift_X  =   0.00 * stage_move_X  +  0.83 * stage_move_Y
image_shift_Y  =  -0.97 * stage_move_X  +  0.00 * stage_move_Y
```

Inverting to obtain the stage correction required to null a measured image shift:

```
stage_correction_X  =  -image_shift_Y / 0.97
stage_correction_Y  =   image_shift_X / 0.83
```

> **Note:** This matrix is **preliminary**. The 0.83 coefficient on the Y axis represents the conservative end of the measured range (83–85%); the variability between objectives has not yet been fully resolved. All measurements were made on a sparse non-DAPI fluorescence sample; the matrix will be revalidated on DAPI-stained nuclei, which provide richer image content and are the intended sample for the production workflow.

We will apply this matrix in our parcentricity correction workflow. However, given the 15–17% correction factor on the Y axis, we would strongly prefer to understand whether this is a genuine stage calibration offset that Leica can address, rather than a fixed empirical correction we need to maintain in software.

---

## 6. Summary of Questions for Leica

| # | Question |
|---|----------|
| 1 | Is the ~90° rotation between stage and image coordinate axes expected and documented for the STELLARIS 8? |
| 2 | Are scale factors of 97% (X) and 83–85% (Y) within factory specification? |
| 3 | Is a stage calibration procedure available that could improve these values? |
| 4 | Is the post-objective-switch settling behaviour (requiring one dummy move before measurements stabilise) expected, and is there a recommended workaround? |
| 5 | Is there a way to independently verify the absolute accuracy of stage displacements — for example, a service-level encoder readback or a recommended procedure using a calibrated reference — so that we can distinguish a genuine stage calibration error from a systematic bias in our image-based measurements? |

---

*Measurements were performed on a Leica STELLARIS 8 confocal system (stand DMI8, serial 8400000246) running LAS X. Image registration was implemented in Python using scikit-image (masked phase cross-correlation), OpenCV (normalised cross-correlation), and a custom RANSAC translation estimator. All results shown are the mean of at least two stable repeated measurements per condition.*
