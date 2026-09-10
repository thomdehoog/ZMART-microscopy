# Live Leica simulator verification — 10 September 2026

Result: bounded simulator checks passed. This is not real-microscope certification.

## What actually ran

- The live CAM API reported `SystemType: SIMULATOR`, serial `STELLARIS SIMULATOR`, and idle before acquisition.
- Seven live captures total, through the existing Leica driver; no job definitions or calibration files edited.
- The four-job capture probe produced TCZYX arrays: Overview `(1,3,1,512,512)`, Overview Stack `(1,3,18,512,512)`, HiRes `(1,3,1,512,512)`, HiRes Stack `(1,3,10,512,512)`.
- Three additional captures exercised the real operator bridge's scan worker: a flat target, a later stack target in the same acquisition, and an overview stack. Baking was enabled. No source/pixel mocks were substituted at the driver boundary; the existing guarded synthetic-pixel ingestion option was enabled.
- All publications reached ready without restarting or manually refreshing. After capture, the observed publication waits were 1.41 s, 9.62 s and 12.62 s respectively. These are small-run measurements, not scaling guarantees.
- Saved captures were replayed into a fresh verification run for preview, detection and browser checks. This was test-controlled ingestion, not a claim that the operator supports resuming an old run across restart.
- Detect previews matched independent array maximum + display math exactly: maximum decoded pixel difference 0 for all three records.
- The real operator detection/finalization worker completed with 324 objects, no failed fields, no detection error and no embedding error, in 34.27 s.
- Actual simulator-capture browser proof: 14 mode/plane cases, 45 pixel samples each (630 assertions), maximum allowed shader quantization error 1, all passed. Top, specimen Slice and MIP were exercised for the target and overview stacks. 1,197 image requests during loading/switching; 0 during the idle/status-read check.
- Four existing named-view browser regressions passed (bake off/on, both arrival orders), including cold Z holds, fine/coarse detail, gaps and acquired black. Each idle window made 0 image requests.
- Twelve backend tests passed, including the opt-in replay of the four new live captures. The projection and detector inputs matched independent NumPy maxima; captured TIFF hashes remained unchanged. Ascending/descending sampling and simulator identity rejection are covered by the automated fixtures, not by changing the live jobs' scan directions.

The browser proof drives the actual operator rendering adapter with its publisher's real sources; it is not a click-through of all nine workflow panels. Focus search/scoring and physical stage calibration were not certified by this run.

## Warnings and test-harness corrections

- A preflight job-list query timed out once. A subsequent attempt succeeded; other calls occasionally needed the driver's existing retry. No timeout/retry policy was changed.
- The simulator's sole saved configuration is `configuration_2026-07-21T14-06-07-867790Z`. Its limits file lacks required entries, so the driver reports fallback to bundled defaults. Its orientation lacks an explicit focus-drive direction. These remain unresolved; do not infer real-instrument readiness from this simulator pass.
- The first custom operator harness omitted the mandatory configuration ID. It was corrected to use the sole published configuration, without editing it.
- The first custom preview oracle passed RGB arrays to the preview API, which expects hex colors. That harness assertion failed; it was corrected and replayed from the already saved TIFFs. Exact equality then passed. No production preview code was changed.
- HTTP keep-alive connection resets were logged when test clients closed sockets; acquisition/publication completed successfully.

## Evidence

Under `C:/ProgramData/MinicondaZMB/home/t.de/_op050/`:

- `sim-verification-2129/records.json`: four-job live capture geometry, synthetic recipe and original hashes.
- `sim-operator-verification-2/records.json`: three captures through the real bridge scan worker.
- `sim-operator-replay/result.json`: preview comparisons, complete detection results and ready publication state.
- `sim-actual-pixel-proof/`: fourteen screenshots from actual captured arrays rendered in the operator adapter.
- `sim-mode-regressions/`: four controlled browser regression cases.

Optional regression: `application/parts/canvas/simulator-capture.spec.js`; set `SIMULATOR_OPERATOR_RECORDS` to the replay records and `SIMULATOR_OPERATOR_URL` to the running, already-published verification bridge. The test does not acquire data or connect to a microscope. Its oracle reads original arrays in `fixtures/simulator_pixel_oracle.py`.

After verification the selected Leica job was restored to Overview, the test session disconnected, and the normal simulator-enabled operator window reopened on port 8865 for manual testing. Saved data was retained. No commits, pushes, dependency-pin changes, or real-microscope operations were performed.

## Follow-up: synthetic specimen focus reference

The fixed synthetic focus at 8 um was wrong for the user's later 400–441 um sweep: extreme defocus quantized the kidney image into two values, producing blobs after contrast. Simulator-enabled connections now read specimen Z once and keep that synthetic focus reference fixed for the session. The run records it in `synthetic-specimen.json`. It is not reset per position or job. Existing captures are not rewritten.

Live simulator proof (`_op050/session-kidney-live/result.json`): session anchor 426.980 um; autofocus result 426.9657 um; subsequent overview acquired successfully with 17 distinct stored values rather than two. Both focus and overview publications reached ready with baking enabled. The near-focus canonical JPEG was visually checked for kidney detail. The selected job and original stage coordinates were restored after the test.

100 targeted regressions passed in 22.36 s. They cover normal connections doing no synthetic-reference read, session anchoring/reconnection, translated focus references, simulator identity rejection, ascending/descending plane order, canonical focus scoring and previews, and bridge acquisition. The Leica driver and motion limits were not changed. Canonical OME-Zarr focus scoring/previews are shared with real acquisition and remain a real-instrument validation item; these tests do not certify microscope safety.
