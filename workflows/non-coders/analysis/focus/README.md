# `focus` workflow

Finds where a sample is sharp. It scores every plane of a z-stack and
returns the height of the sharpest.

| Pipeline | Steps | What it measures |
|---|---|---|
| `focus.yaml` | `read_images` → `score_focus` | How sharp each plane of a z-stack is, and the height of the sharpest. |

`read_images` reads the planes the input names, and `score_focus` never
opens a file. The docstring of each step, in `steps/`, says what goes in and
what comes back.

## Choose a measure

The operator page sends one stack per focus point: the planes as files with
their heights, or one OME-Zarr position with a z axis. All four sharpness
measures are scored, so their curves can be compared; `metric` in
`focus.yaml` says which one decides.

| Measure | Good at | Watch out for |
| --- | --- | --- |
| `brenner` (default) | A sharp, clear peak on structured tissue | Noise in a dim image looks like sharpness |
| `dct` | Does not care how bright the image is | A broader peak; empty, noisy planes score high |
| `vollath_f4` | Dim, noisy fluorescence | A slightly flatter peak than Brenner |
| `intensity` | Sparse or faint samples on a confocal | Confocal only; bleaching and bright debris mislead it |

Start with `brenner`. Try `vollath_f4` on a dim, noisy sample, and
`intensity` on a sparse sample on a confocal: there the pinhole makes the
image brightest at focus, while on a widefield brightness barely changes.
Pertuz, Puig and Garcia (2013, *Pattern Recognition* 46:1415) compare these
measures.

The first and last planes of a drive often carry artefacts with hard edges,
which every measure rewards. `skip_ends` (2 by default) stops that many
planes at each end from winning; they are still scored and returned.

## Environment

Both steps run in `ZMART--focus--main`: numpy, scipy and the image
readers. No PyTorch, no GPU. Create it once with:

```bash
conda env create -f workflows/non-coders/analysis/focus/environments/main.yml
```
