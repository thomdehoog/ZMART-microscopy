# Viewer responsiveness — what was slow, what changed, what was measured

Date: 2026-09-21. Operator branch `codex/operator-named-views-simulator`; companion viewer
`codex/operator-embedding` at `6791d289` (local, not pushed).

## What made loading and browsing slow, ranked

1. **The scan poll shipped every record three times a second and redrew the whole page each time.**
   `parts/microscope/live.js` polled `/api/scan` every 300 ms; the bridge answered with the full record
   list; `framework/window/main.js` answered every poll with a full render (rail, tabs, cards, the channel
   remounted). Payload and parse grew with the field count, so a scan cost O(N²), and the redraw starved the
   picture engine's paint and decode callbacks.
2. **Every chunk was refused with a 503 while a publication ran**, and a publication ran once per landed
   field (`zmart_viewer/server.py`, the `pending.json` gate). The picture went cold exactly when it was told
   to refetch.
3. **Baking was off by default**, so the zoomed-out picture was composed on demand from every position: the
   coarsest level of a 100-position canvas measured 3.4 s unbaked against 12.6 ms baked
   (`PUBLICATION_OWNER_AND_COARSE_COST_2026-09-08.md`); the churn ladder settled in 17 s at 100 positions and
   90 s at 1,000 unbaked, 4 to 8 s baked.
4. **The whole product's decoded cache is dropped on every publication** (`source-refresh.js`), image and
   coverage layers both, about every 1.5 s during a scan. Documented as an accepted trade-off; the publisher
   already computes the exact dirty chunk set.
5. **Publish-side bookkeeping is O(N) per landed field** in the process that serves chunks: the whole order
   re-announced with a stat per position, two JSON reads per position, the snapshot re-read, the manifest
   rewritten twice, the per-level tile index rebuilt for both composers. The pixel work itself is incremental.
6. Page churn per publication: rows computed twice, every layer reordered, a 10 Hz reconciliation timer.
7. JPEG copies are exonerated: none is made per capture.

## What changed

- **A1** `/api/scan?since=N` answers only the records after the N the page already holds; the page keeps
  them. The progress handler returns at once when the landed count is unchanged, so nothing is redrawn.
- **A2** (viewer) A reader holding the previous generation keeps answering from it during a publication and
  withholds only the pieces the publication names in `pending.json`. It never waits on the publication's lock.
- **A4** Baking is on unless the operator switches it off in the session card.
- Not done: A3 (a publish debounce) because publications already coalesce every field that lands while one
  is running; A5 (chunk-selective invalidation) and A6 (page churn), deferred until A1 to A4 are seen on a
  real scan.

## Measured

Scan poll payload, one answer (`bridge._the_scan`), this machine:

| records | whole answer | serialised | since the cursor |
| --- | ---: | ---: | ---: |
| 100 | 63 KB | 0.6 ms | 129 B |
| 864 | 544 KB | 4.6 ms | 129 B |
| 8,436 | 5.3 MB | 38.7 ms | 130 B |

At 3.3 polls a second the whole answer was 1.8 MB/s at 864 fields and 18 MB/s at 8,436, before parsing and
the redraw. The redraw count now equals the number of fields that landed, not the number of polls.

Chunk answers while a publication ran, 120 positions, three publications, one untouched piece and one
rewritten piece asked for in a loop (`scratchpad/measure_availability.py`):

| | untouched piece | rewritten piece |
| --- | --- | --- |
| before | 7 × 503 | 7 × 503 |
| after | 4 × 200 | 4 × 503, 1 × 200 |

The samples are small because a publication at this size lasts under half a second; the direction is what
the change is for. The one 200 on the rewritten piece came from the instant between the commit and the
observation.

Baking: no new measurement; the numbers under 3 above are the ones the default rests on.

## Verified

- Operator: JS unit suite 528 passed; `test_operator_bridge.py` 61 passed; the nine-step walk with bake on, 2.6 min, 350 image requests, 0 idle (one earlier attempt stalled at the Step 8 settings import with "failed — retry"; the import answers in isolation and the next walk passed, so it stands as a one-off not reproduced).
- Viewer: publication, lifecycle, named-view and server tests, 121 passed. Two failures are pre-existing
  on the unchanged viewer: `test_optional_bake_is_one_source_and_updates_in_the_browser[True]` (a page
  waiting for a revision it never sees) and, before this change, `test_interrupted_bake_can_reopen_and_recover`
  and `test_interrupted_publication_is_refused_until_retry_recovers`, both rewritten to the new contract: a
  reader with the previous generation in hand keeps it and is refused only the rewritten pieces; a fresh
  reader on a leftover note is refused whole.
