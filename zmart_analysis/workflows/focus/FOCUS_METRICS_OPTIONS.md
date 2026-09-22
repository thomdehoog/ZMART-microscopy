# Focus metrics: what we have, what else there is

A note of the discussion on 2026-09-22. Nothing here is built.

## What `score_focus` has today

- **Brenner** (gradient): mean squared difference between pixels two apart, along both axes.
- **DCT entropy** (frequency): Shannon entropy of the normalised DCT coefficient energy.

Both are scored on every stack; the page chooses which one decides, and the peak rule
(`application/parts/microscope/focus-peaks.js`: tallest peak wide enough to be tissue) is the same for all.

## The families

| Family | Examples | Strength | Weakness |
| --- | --- | --- | --- |
| Gradient (have) | Brenner, Tenengrad, variance of the Laplacian | Sharp peak on structured tissue | Noise in dim images looks like sharpness |
| Frequency (have) | DCT entropy, wavelet energy | Largely independent of how bright the image is | Broader peak, costs more to compute |
| Statistics | Normalised variance, Vollath F4 (autocorrelation) | Robust in low signal and noise | Slightly flatter peak than gradient |
| Intensity | Mean of the brightest 1 %, total signal | Simplest; works on sparse or faint samples on a confocal | Bleaching lowers it as the stack goes on; a bright speck of debris can win |
| Hardware | Leica's reflection autofocus off the coverslip | Fast, needs no image | Finds the glass, not the tissue; needs an offset |

## Why intensity works here

On a widefield microscope, total brightness barely changes through focus, because out-of-focus light still
reaches the camera. On a confocal such as the Stellaris, the pinhole rejects out-of-focus light, so brightness
peaks at the focal plane. Intensity only fails as a measure on a widefield.

## Recommendation

Add two metrics, both cheap score functions in `steps/score_focus.py` beside Brenner:

1. **Vollath F4**: strongest exactly where Brenner is weakest, in dim, noisy fluorescence.
2. **Intensity, as the mean of the brightest percentile**: not the plain mean, so a single speck cannot take
   over and a flat background does not dilute the signal.

The page already offers a metric choice, and the peak rule stays the same for all of them.

Check both against a real confocal stack from the rig before relying on them.

## Caution for intensity

Stack from bottom to top without backtracking, so bleaching takes effect in only one direction. With strong
bleaching the intensity peak shifts towards the planes taken first. Gradient measures shift less, because
they measure contrast, not brightness.
