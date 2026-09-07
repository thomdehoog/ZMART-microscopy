# Operator transparency proof

Run `transparent-middle.spec.js` to generate screenshots in Playwright's output
directory, using the real mock bridge and operator. These are browser captures,
not mockups or golden-image fixtures.

- `step-4-focus.png`: focusing images above the plan and heatmap.
- `step-5-partial.png`: overview acquisition in progress.
- `step-5-overview.png`: completion evidence, not alone proof of transparency.
- `three-layers.png`: a diagnostic three-surface stack.

In the diagnostic image, magenta is below Neuroglancer and the orange label is
above it. Dark specimen pixels stay dark instead of exposing magenta. The test
also hides only the image viewer and compares screenshots, attaching its pixel
measurements to confirm real imagery rather than application decoration. The
JPEG fallback spec also measures differential composite pixels.

The lower background remains enabled and its cut-out list stays empty throughout
focusing and overview acquisition. All planned records and focus slices must
arrive without storage errors or lost points. The same viewer survives new
acquisition rows; the nine-step walk extends this check to target acquisition.
Source removal or replacement still reopens a different scene.

Screenshots are generated review artifacts, not tracked files.

See [the review prompt](../../CLAUDE_REVIEW_PROMPT.md) for scope and reproduction.
