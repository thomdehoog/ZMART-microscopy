# Next session: export-to-viewer latency and responsiveness

Recorded 2026-09-11 for `codex/operator-named-views-simulator`.

## Objective

Reduce the time from microscope export completion to a useful image appearing in the viewer. Keep selection, previews, panning, zooming and image refinement responsive while remaining stores and views prepare. Optimize first useful display as well as total completion time.

## Starting point

Read [the issue and validation report](MICROSCOPE_ISSUES_2026-09-10.md) and [installation handover](MICROSCOPE_INSTALL_HANDOVER_2026-09-10.md) before changing the installed operator.

- Repairs 1–3 restored preview dependencies, removed selection-triggered aggregate rebuilding, and kept committed HTTP image generations readable during publication with prompt per-view revisions.
- Native mock validation, committed in `bc475e5c`, covered one overview position, one focus point and two targets. Selection took 84 ms per target; committed chunk requests remained HTTP 200 during a rerun, and finest-level chunks loaded on zoom. This is functional evidence, not a full-scale performance benchmark.
- Earlier diagnostics found expensive pyramid composition and substantial publication lag. The complete breakdown of export, conversion, copying, compression, composition, cache use and rendering is still missing. Store preparation and pyramid composition are likely opportunities, not a newly confirmed ranking of bottlenecks.

## Work order

### User observation: disabling baking appears to show images sooner

On 2026-09-11, the user reported that images seem to arrive on screen faster with baking disabled. This is an observed difference, not yet a controlled timing result. It suggests that baking may delay first display through publication dependencies or competition for CPU/I/O; the mechanism remains to be measured.

The user subsequently clarified that display still seems slightly slow with baking disabled and needs more observation. Responsiveness is therefore not considered resolved. The agreed next step is measurement: time **export completion → canonical store ready → publication → first visible image** with baking both enabled and disabled. Time target selection and zoom refinement separately to distinguish image-loading delays from interaction delays. Record these as preliminary user observations until controlled measurements establish their magnitude and cause.

Make baking enabled versus disabled an explicit baseline comparison using the same recorded data, view, viewport, channels and matched cache conditions. Measure first useful display, subsequent pan/zoom/refinement latency, publication completion, CPU/I/O and cache growth. Check both initial and repeated viewing: faster first display alone does not establish which mode provides the best sustained responsiveness.

If the comparison confirms an advantage, evaluate an interactive path with baking disabled or deferred until after first display, with bounded background work. Preserve correctness and readable publication in either mode. Do not change the default solely on this observation.

### Planned steps

1. **Measure an export-to-display baseline.** Correlate timestamps by acquisition, position, view and source revision: microscope export completion, conversion start/end, canonical store readiness, publication queue/start/commit, operator revision delivery, first viewer request, first useful displayed image and fine-detail arrival. Separate queue delay from active processing. A successful HTTP response alone does not establish that pixels appeared on screen. Record dataset size, channels, Z depth, bake settings and cache conditions.

2. **Make completed positions visible sooner.** Inspect current scheduling before adding concurrency. Determine whether conversion/publication can overlap the next capture without reading incomplete exports or competing excessively for disk access. Verify that Top becomes usable before Slice/MIP completion, using the existing per-view publication support. Remove any remaining unnecessary wait for an entire batch or all views.

3. **Reduce repeated preparation work.** Measure source copying, compression and pyramid composition separately. Check reuse of existing source data and compatible pyramid levels, and whether changed images invalidate more regions than necessary. The current viewer already shares frozen source revisions across views/generations; build on that rather than duplicating it. Preserve committed-generation consistency while reducing work.

4. **Give visible interaction priority.** Measure competition between background preparation and requests for visible chunks/previews. Bound background CPU and I/O concurrency so panning, zooming, selection and refinement retain capacity. Keep routine operator interactions independent of publication and let Neuroglancer manage loading/refinement without unnecessary operator resets or rebuild requests. Do not add more workers without measuring their effect.

5. **Repeat the original 20-target workload.** Compare before/after results under matched settings, distinguishing cold and warm cache runs. Report time to first useful image, per-target export-to-visible delay, publication queue delay, selection latency, zoom-to-fine-detail latency and total completion time. Include slow cases, not only averages. Use recorded data or the mock driver for repeatable measurements; real microscope acquisition requires an agreed operational run.

## Completion evidence

- Save a reproducible command or profiling harness, settings and timestamped results alongside a concise findings report.
- Identify the largest measured costs and make targeted changes in that order. Set numerical improvement targets after the baseline; no overall speedup is established yet.
- Verify that preview correctness, selected-target synchronization, readable committed images, source revision updates and viewer continuity survive each change.
- Show improvement on the larger workload without trading away image correctness or interactive responsiveness. Run focused regression checks appropriate to the changed paths.

## Separate open repairs

Keep the additional findings from native validation visible: long Windows paths can break canonical conversion; focus conversion failures need clearer error/action state; carrier blur can consume navigation clicks. Exhaustive native rendering/cache investigation and navigation across multiple focus points also remain open. They are not established causes of all export-to-viewer latency and should not replace the performance baseline.
