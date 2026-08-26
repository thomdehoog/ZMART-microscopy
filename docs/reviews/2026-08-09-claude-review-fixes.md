# Disposition of the independent live-publication review

This records the implementation response to the independent review on
`origin/claude/live-position-timepoint-pub-kw4j30`, reviewed against the real
branch base `claude/omezarr-neuroglancer-structure-srnwu6`. It is a current-state
document; the earlier response documents remain historical snapshots.

## Review findings

| # | Finding | Disposition |
| --- | --- | --- |
| 1–2 | incomplete/ragged mosaics double-own and later overwrite specimen | Fixed by refusing an incomplete planned rectangular footprint before ownership regions can be published. The canonical positions remain available for a future explicit irregular-boundary or stitching path. |
| 3 | an uncommitted moment is copied into both views | Fixed. View membership is `(position, moment)`, and each normal update writes only the affected unit. Both stored views and the HTTP gateway enforce the same unit. |
| 4 | restart loses a replacement generation | Fixed. Every commit records `position_generation`; restart restores it and also infers generations from legacy replacement history. |
| 5 | the production writer does not produce OME-Zarr | Fixed. The live writer describes every canonical position before publication. The seamless view is a multiscale OME-Zarr 0.5 image. Both are exercised through an outside `ngff-zarr` reader and the published schema. |
| 6 | every commit rebuilds the whole history, giving quadratic cost | Fixed at the identified algorithmic boundary. A normal commit opens every pyramid level of only the affected position once per view, so work is linear over the run rather than quadratic. Linkable view chunks are also byte-routed by the backend, although their physical duplicates are not removed yet. |
| 7 | declared Python 3.10 support does not parse | Fixed at both starred-subscript sites in `zmart_storage/canvas.py`; Ruff continues to target Python 3.10. |
| 8 | the real viewer backend is disconnected | Fixed. `zmart-viewer/app/server/server.py` calls the shared manifest-aware gateway before static serving and forwards exact encoded inner-chunk byte ranges, including chunks inside shards. A real-HTTP backend test proves the same URL is 404 before commit and served after commit. |
| 9 | neither view has pyramids | Fixed. Both view groups contain every profile level and readiness compares every advertised level. The seamless group carries standard OME metadata; the raw selector group uses an explicitly non-OME `tile` axis and `.zarr` name. |
| 10 | there is no executable analysis consumer | Deliberately deferred. The user explicitly chose to postpone this phase. The immutable layout still records `analysis_input_roi` and exactly-once `analysis_core_roi` so a later consumer does not have to infer overlap. |
| 11 | the decision record states the opposite seam owner | Fixed. Documentation and model comments now consistently say the lower/right tile owns the shared strip. |
| 12 | the documented dev install skips the independent reader | Fixed. `ngff-zarr[validate]>=0.41` is in the `dev` extra and development requirements. |

## Additional defects found in the wider pass

- The production publisher now persists the content-addressed acquisition profile
  and immutable layout revision that each commit names; previously those helpers
  existed but the production path did not call them.
- The gateway treats a replacement as advancing the whole copied position store.
  Moments already published remain visible in the new generation, while room for
  a moment never published remains withheld.
- The gateway validates the link map's run, profile, layout revision, generation,
  level, view shape, tile placement, and containment before serving it. A damaged
  map fails closed instead of returning plausible pixels from the wrong place.
- The production browser harness had retained position-only arguments even after
  its method-name drift guard passed. It now constructs the same
  `(position, moment)` and affected-unit sets as the coordinator.
- The internal `.generation-N` replacement-store suffix is reserved for new
  identifiers, preventing a replacement of `sample` from colliding with a
  canonical position named `sample.generation-1`. The gateway still resolves a
  lone legacy exact name against its immutable layout before suffix parsing.
- Live requests claimed by the gateway cannot fall through to the older generic
  pointer mechanism when a required physical file is missing.
- Reopening a run now refuses a changed profile, grid, ownership plan, channel
  declaration, axis order, or (once pixels exist) declared timepoint room. Pixel
  stacks whose `(z, y, x)` shape disagrees with the sealed camera/acquisition
  profile are refused before any array is created.
- Profile IDs are checked against their own content fingerprint before being
  stored. Position and profile names that would collapse to one file on a
  case-insensitive Windows filesystem are refused, as are negative/non-integral
  grid indexes and the internal replacement-store suffix.
- Replacement publication installs the candidate generation map before changing
  shared physical chunks. The gateway therefore withholds the position during
  the update; a failed replacement restores the prior seamless/raw pixels and
  old routing before visibility returns.
- Mutation campaigns now turn Ctrl-C/SIGTERM into a restorable interruption and
  prove both source bytes and a clean post-mutation test baseline before moving
  to another subject. SIGKILL and power loss remain inherently unrecoverable.

## Remaining boundaries, stated without release inflation

- Linkable fine/intermediate view chunks are served zero-copy, but the writer still
  materializes duplicates. Removing those duplicate files while retaining only
  physical outer-edge and truly derived coarse chunks is the next storage-scale
  optimization. The review's quadratic rebuild defect is fixed; the remaining
  duplication is still real disk and write cost.
- Manifest-driven automatic refresh in the application frontend remains to be
  wired. The production browser harness explicitly invalidates Neuroglancer; the
  application backend gate is covered by HTTP tests, not yet by that browser suite.
- The concurrent analysis consumer is deferred, not silently claimed.
- Windows/SMB locking, power-loss behavior, multi-terabyte scale, and a multi-row
  mosaic watched through the complete application browser path remain unqualified.

## Validation standard

The final handoff records exact ordinary-suite, independent-reader, mutation, and
real-backend HTTP results. Production browser tests are attempted separately. An
environmental browser block is recorded as an unqualified boundary, never counted
as a pass or silently absorbed into an ordinary-suite total.

## Validation recorded for this fix commit

- `zmart_live/tests`: **510 passed**, with the independent `ngff-zarr` reader and
  published 0.5 schema checks installed and running (no interoperability skips).
- `zmart-viewer/tests`: **385 passed, 238 skipped**. The suite printed its explicit
  “NO PICTURE WAS LOOKED AT” notice: this checkout has neither the Python
  Playwright package nor `zmart-viewer/app/page/dist/index.html`. Those 238 browser
  cases are not counted as passes.
- Real application-backend live HTTP plus gateway regressions: **12 passed**,
  including exact encoded-byte forwarding and HTTP Range slicing.
- Fault injection: **176 seeded faults caught** across manifest, ownership,
  profile/layout identity, planning, coordinator, gateway/replacement rollback,
  scene compilation, OME-Zarr, shard-link and view-route campaigns. Campaigns now
  rerun their clean subject after restoring it.
- Scoped Ruff and `git diff --check`: clean. All **478 committed-or-new Python
  files** parse with Python 3.10 grammar.
- The production Neuroglancer browser suite itself remains **blocked, not
  passed**: its configured Chromium executable and local Playwright package are
  absent. A prior browser-install attempt in this environment was also blocked by
  the restricted download path. The prebuilt synthetic viewer page is present.
