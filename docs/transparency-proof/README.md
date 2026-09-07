# Operator transparency proof

Run `transparent-middle.spec.js` to generate screenshots in Playwright's output
directory, using the real mock bridge and operator. These are browser captures,
not mockups or golden-image fixtures.

- `step-4-focus.png`: focusing images above the plan and heatmap.
- `step-5-plan.png`: the lower plan with the image temporarily hidden.
- `step-5-partial.png`: one real overview field surrounded by unacquired plan.
- `three-layers.png`: a diagnostic three-surface stack.

In the diagnostic image, magenta is below Neuroglancer and the orange label is
above it. Dark specimen pixels stay dark instead of exposing magenta. The test
also hides only the image viewer and compares screenshots, attaching its pixel
measurements to confirm real imagery rather than application decoration. The
JPEG fallback spec also measures differential composite pixels.

The partial proof compares the saved screenshot to the image-hidden plan: it
requires dark specimen pixels and unchanged plan pixels in the same frame,
with identical canvas dimensions. The viewer's synthetic fixture separately
checks exact zero-valued image pixels remain opaque.
One field is acquired through the real bridge, so this does not race the
mock's acquisition speed. The separate nine-step walk exercises the full
UI-driven overview and target acquisition. Starting a second overview here
would replace the first scan's sources, not exercise continuous growth.

The lower background remains enabled throughout focusing and overview acquisition.
The acquired overview record and focus slices must arrive without storage
errors or lost points. The same viewer survives new acquisition rows; the
nine-step walk extends this check through a full overview to target acquisition.
Source removal or replacement still reopens a different scene.

Screenshots are generated review artifacts, not tracked files.

See [the review prompt](../../CLAUDE_REVIEW_PROMPT.md) for scope and reproduction.
