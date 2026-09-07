# Operator transparency proof

Captured on 2026-09-07 by `transparent-middle.spec.js`, using the real operator,
mock microscope bridge, ZMART-viewer 0.2.0 backend and patched Neuroglancer 2.41.2.
These are unmodified browser screenshots, not mockups.

- [Step 4: focusing](step-4-focus.png)
- [Step 5: overview acquisition](step-5-overview.png)
- [Diagnostic three-layer stack](three-layers.png)

In the diagnostic image, magenta is below Neuroglancer and the orange label is
above it. Dark specimen pixels stay dark instead of exposing magenta. The test
also hides only the image viewer and compares screenshots: 137,257 pixels change,
confirming the middle content is real imagery rather than application decoration.

The lower background remains enabled and its cut-out list stays empty throughout
focusing and overview acquisition. The initial empty viewer survives installation
of the first focusing sources. Adding a different acquisition shape still uses
the pre-existing scene-reopen path; that is not qualified as flicker-free here.

See [the review prompt](../../CLAUDE_REVIEW_PROMPT.md) for scope and reproduction.
