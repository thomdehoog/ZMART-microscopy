# Review of the rendering-engine plan

Date: 2026-09-02

## Verdict: rework

The plan is a useful inventory, but it is not yet a safe basis for scheduling
the data-layer work. Its central recommendation says that `LivePublisher`
already does two things that it does not do: it does not guarantee a shard at
every retained level, and it does not rebuild the run-wide coarse picture as
part of its publication transaction. The existing coarse-picture patcher is a
separate Viewer path that reacts to an already published run. That distinction
matters scientifically: the marker cannot promise that a newly visible field
and its zoomed-out representation agree if the coarse representation is updated
after the marker.

Phase 0 also cannot yet produce all the evidence the record requires. The
proposed source-read counter is not a source-read counter, the useful-picture
test loses its denominator when coverage is called unbounded, five repetitions
cannot support a ninety-fifth percentile, and the two chosen runs do not cover
the earlier design's minimum fixture classes. These are not reasons to reopen
the product decision to build the engine. They are reasons to repair the plan
before accepting its sequence, estimates, and completion claims.

## Scope and evidence

I read ZMART-microscopy commit
`63befe91c123765bb8e469683055659b7f6bb292`; the plan itself was present from
`c287e8f3`. I read ZMART Viewer commit
`9b67bf8e843b5b80145f210fb3b180e2fce554ff` and Neuroglancer 2.41.2 at source
commit `e13f1f4c62918f2ea07b12f2116bdcb6767b1499`. The two ZMART repositories
were fresh clones, and the Neuroglancer checkout was at the pinned tag. I read
the complete plan, the fourth rendering record, the earlier ten-step trace and
gates, the named code, and `CLAUDE.md`. I did not implement the plan.

## Findings, ordered by consequence

### 1. The proposed publisher path does not presently provide the transaction on which the plan relies

**Facts.** Decisions 3 and 7, and items 2.1, 2.8 and 2.9, say that the
publisher writes sharded levels and rebuilds coarse pieces from committed
positions in the same publication step
(`docs/design/own-rendering-engine-detailed-plan.md:46-72`, `:218-230`,
`:251-260`, `:304-313`). In the Viewer, however, a level's `shard` is optional
(`zmart_viewer/record/model.py:601-630`). `LivePublisher._write_one_level`
passes `shards=None` whenever the profile omitted it
(`zmart_viewer/record/coordinator.py:755-789`). The publisher writes each
position's own pyramid, refreshes pointer metadata and the layout, and then
publishes the manifest marker (`coordinator.py:1686-1696`, `:1783-1806`). It
does not import or call `record/coarse.py`, and nothing else in the Viewer
imports that module.

The run-wide kept coarse picture is maintained separately in `building.py`.
That code reads the committed manifest, derives dirty pieces, and patches a
bake if the opened Viewer source requested one (`zmart_viewer/building.py:900-959`,
`:1024-1109`). It therefore cannot, as written, make the new landing's coarse
pieces current before the publisher advances the marker. This conflicts with
the record's gate that the marker moves only after every dirty coarse piece is
current (`docs/design/own-rendering-engine-and-position-register.md:720-722`).

There is another concrete API mismatch. The plan says the commit event's
`notes` will reference the immutable observation (`own-rendering-engine-detailed-plan.md:262-268`),
but `LivePublisher.publish` constructs `notes` itself from its inspection report
and accepts no observation or notes argument
(`zmart_viewer/record/coordinator.py:1623-1679`). Likewise, the current
manifest has no terminal-publication method; its normal writer always creates a
new pixel event and serialises only the existing marker fields.

**Inference.** Decision 3 cannot be accepted on its stated rationale, and step
3.1 is larger than an integration task. Before choosing the publisher as the
bridge's pixel writer, the data-layer record needs an explicit bridge-facing
transaction: write and validate the observation, write every required sharded
position level, bring any kept coarse pieces current, write the pointer and
layout products, and only then advance the pixel marker. It also needs a
separate locked terminal-only marker replacement that changes no pixel or
layout revision. Reusing `LivePublisher` may still be the best result, but it
requires design and extension; the present code does not make that result a
settled fact.

### 2. Phase 0 would produce reassuring numbers without satisfying the frozen experiment

**Facts.** The plan calls the driver's settled rule two identical photographs
0.2 seconds apart (`own-rendering-engine-detailed-plan.md:113-124`). The loop
actually returns after two consecutive equal comparisons, which requires three
identical photographs, with a sleep after each of the first two
(`viz_studio/options/measure/drive.py:213-226`). If it never settles in sixty
tries, it returns silently rather than recording a timeout. Neuroglancer 2.41.2
does expose per-render-layer visible chunks needed and available
(`src/chunk_manager/frontend.ts:358-377`, `src/sliceview/backend.ts:175-200`),
but equality can initially be the stale result for the preceding view or
`0 == 0`. Item 1.3 does not bind the counters to the gesture's view generation,
require a non-zero need for covered ground, require a post-settle paint, or
make failure and timeout explicit.

The existing `Composer.tile_reads` is incremented once per requested rectangle
before a loop over source chunks (`zmart_viewer/compose.py:1003-1039`). Each
iteration can be a memory-cache hit, and one rectangle can cross several source
chunks; the actual array access is at `compose.py:959-1001`. Consequently it is
neither a physical source-block count nor a byte count. Merely serving it from
`/api/accounting`, as item 1.6 proposes, cannot implement the record's
storage-boundary gate.

The useful-picture definition requires ninety per cent of *covered* visible
ground. Item 1.1 instead makes coverage "unbounded" when the run is opened
through the Viewer (`own-rendering-engine-detailed-plan.md:129-138`). The
result then has no defensible covered-area denominator, especially on the
sparse fixture. The proposed five repetitions per trace step also cannot
support a ninety-fifth percentile; the earlier memory gate itself requires
twenty whole-trace repetitions
(`docs/design/lazy-jpeg-pyramids-for-the-viewer.md:446-464`). Finally, the
earlier design requires at least a representative small run, a plate-scale
multi-channel overview, the largest real run, a live replay, sparse
fluorescence with outliers, and a stack plus overview (`lazy-jpeg-pyramids-for-the-viewer.md:387-400`).
Decision 2 names only a real Leica run and one dense mock run.

**Inference.** Phase 0 needs a new counter at the actual array-read/cache-miss
boundary, with bytes, and a generation-aware settle rule that can fail. It must
obtain committed coverage from the Viewer or calculate the same indexed
footprints independently; "unbounded" may be reported as missing evidence but
cannot pass the useful-picture measurement. The protocol should repeat whole
traces enough times to report its chosen percentiles and should name frozen
datasets that cover all six minimum roles, allowing one dataset to serve
several roles where that is stated and demonstrated.

### 3. Becoming a publisher client changes more of the acquisition contract than the plan records

**Facts.** Today's bridge moves the vendor TIFFs and their metadata into
`<experiment>/<acquisition-type>/data`, writes the acquisition-wide
`zmart-acquisition.json`, and writes each position under
`positions/<type>/*.ome.zarr` (`application/parts/storage/output.py:75-86`,
`:112-120`; `application/framework/bridge.py:683-748`, `:849-897`). The
position writer mirrors stable channel keys, indices, labels, colours, ranges,
display windows and their provenance into a `zmart` attribute, including when
OME cannot legally carry a still-unresolved display window
(`application/parts/storage/zarr_positions.py:121-180`, `:192-214`).

`LivePublisher` instead writes positions as member groups under
`data/survey.ome.zarr` and a linked view under
`views/live/live.ome.zarr` (`zmart_viewer/record/coordinator.py:484-524`). Its
sealed profile serialises channels as strings
(`zmart_viewer/record/model.py:731-747`, `:948-995`); it has no equivalent of
the acquisition document's stable key, index, range, display-window provenance,
or unresolved-window attribute. The plan acknowledges the different folder
shape and early profile, but does not say where the vendor data and acquisition
document move, how their references remain portable, or how the richer channel
contract reaches both the Viewer and independent OME readers.

The bridge's Viewer is currently optional: failure to import or start it costs
the live picture, not acquisition (`application/parts/storage/viewer_service.py:110-167`).
It opens ordinary position folders through the Viewer's generic open route and
relinks after growth by counting `*.ome.zarr` stores every thirty seconds
(`viewer_service.py:250-349`). A governed run should instead be opened once and
followed through its manifest. The plan says that outcome, but does not name the
new service path, capability/version check, or migration from the old sources.
Nor does it choose `LivePublisher.linked_view`: its default `per_publish` makes
a whole-run pass on every landing, while `at_run_end` has two documented open
operator defects, dead automatic contrast and growth flicker
(`zmart_viewer/record/coordinator.py:207-251`).

The Leica does report frame size and pixel size before capture, but the exposed
state does not provide all exact profile inputs. The plan itself concedes that
data type and plane count arrive with the first capture
(`own-rendering-engine-detailed-plan.md:446-450`). A frame size in micrometres
is also not by itself an exact integer array shape. The fallback of writing the
layout one landing late is contrary to the record's whole-plan-before-pixels
promise.

**Inference.** Step 2 must decide the complete on-disk hierarchy, preservation
of raw provenance and the acquisition display contract, the Viewer's governed
open path, the linked-view mode, cross-repository version compatibility, and
what happens to a scan if publication fails. In particular, making the Viewer
package a required writer changes today's fault boundary: an unavailable or
slow Viewer library could now delay every next stage move or stop conversion.
That operator consequence needs an explicit fail-safe policy. The instrument
interface should expose exact pixel shape, data type, channels, depth and time
room before scan start; "one landing late" should not be an accepted fallback.

### 4. Step 2 omits handed-over choices and defers a design branch until after its implementation

**Facts.** The rendering record leaves five matters to the data-layer record:
dirty-history retention, the tile size at lazy middle levels, the numerical
guard's share, the irregular-z tolerance, and the exact observation and
lifecycle shapes (`own-rendering-engine-and-position-register.md:807-817`).
The plan covers retention and irregular-z tolerance directly, and covers the
document shapes and tile-size table in outline. It never mentions the numerical
guard: the fraction of a level's tiles allowed to exceed the latency budget
before the level is kept.

The record also says phase 0 determines whether coarse levels are kept before
the data-layer record is written (`own-rendering-engine-and-position-register.md:395-401`,
`:696-699`). Item 2.8 instead leaves the cost numbers to step 3's measurement,
after the data layer has been designed and built
(`own-rendering-engine-detailed-plan.md:304-308`, `:330-355`). The storage
profile, omitted position levels, coarse products and publication transaction
all depend on that branch, so it cannot be postponed to validation of the
implementation.

The terminal item checks only that an old marker reader ignores an unknown
field (`own-rendering-engine-detailed-plan.md:270-276`). It does not specify the
new reader that notices a same-revision fingerprint change, reads the lifecycle,
and changes planned positions to "not acquired" or "skipped"; it does not
specify locking, durability, terminal immutability, or refusal to resume a
terminal run. The coordinate item also lacks the run's x/y/z datum and exact
rounding rule that turn absolute stage positions into run-relative whole-pixel
origins. Feeding raw stage coordinates directly to `LivePublisher.positions`
would not define a compact run grid.

**Inference.** Step 2 is not yet a complete hand-off. The phase-0 sentence must
select the coarse-level branch, and the data-layer record must contain the
measured model that justifies it before step 3. The missing numerical guard,
terminal reader/transaction, acquisition-contract reference, schema versions,
coordinate datum, and exact lazy-middle tile choice all need explicit work
items and falsifiable review criteria.

### 5. The dependency and completion tables understate the work

**Facts.** Item 1.4 promises to record item 1.6's breakdown, yet its dependency
row omits 1.6. It runs a bridge-written five-axis fixture, yet omits the adapter
fix in 1.2. Item 1.5 is declared independent even though its completion test is
twenty repetitions of the trace in 1.4. Item 1.7's final size is fixed by the
protocol and Decision 2, but both are absent from its dependency row. Item 1.8
depends on the owner choices for fixtures, accounting, memory, repetitions and
the live landing, not only on items 1.4 through 1.7
(`own-rendering-engine-detailed-plan.md:420-442`). Conversely, implementation
of 1.1 can start now because the record already settles that phase 0 must
measure the Viewer and its composer; it is not waiting on a product choice.

Only item 1.2 has a strong binary completion condition. Several others can
pass while measuring the wrong thing: 1.1 proves that a path opened but not
that it stayed read-only or opened the whole run; 1.3 compares one uncertain
clock with another; 1.5 accepts any produced number; and 1.6 defines a residual
from the total and then uses equality with that residual as its test. Item 1.7
has no `Done when`. Step 2's group condition proves that a document was reviewed,
not that any of its eleven subjects is complete. Items 3.2 through 3.4, 4.2 and
4.3, and the later milestones likewise have no individual observable finish.

**Inference.** The table is not a reliable schedule or acceptance plan yet.
Dependencies should describe what is needed to finish, even if exploratory
coding can start sooner. Each item should name an output and a test or
measurement that can fail independently. The estimates for counter-based
settling, cross-process memory, two-sided accounting, the data-layer record,
and the publisher integration should be increased after the missing work is
made explicit.

## Answers to the eight questions

### 1. Are the claims about the code true?

| Claim | Assessment | Evidence |
|---|---|---|
| The external-run door serves one store through the rig's server | **True.** | `real_run.the_store_to_open` selects a composed store or the first position store, and `measure` gives its parent and name to `drive.Harness` (`viz_studio/options/measure/real_run.py:40-68`, `:92-124`). |
| Settled is two identical photographs; the adapter lacks needed/available counters | **False as written.** | The adapter part is true (`viewer.js:302-308`, `:2491-2523`, `:2693-2695`). The driver requires three identical photographs, and a failure to settle is silent (`drive.py:213-226`). |
| No memory reader, executable ten-step trace, or protocol exists | **True.** | No such reader or protocol is present; the trace remains prose at `lazy-jpeg-pyramids-for-the-viewer.md:402-416`. |
| The composer has an unserved storage-boundary read counter and timers; the server lacks route counts | **False as written.** | The timers are real and unserved, and the server has no per-route ledger. `tile_reads` counts `_read_from` calls, not physical source reads or bytes; `_a_block_of` performs zero or several actual array reads for that unit (`compose.py:959-1039`). |
| The record's production writer is `LivePublisher`, called live only by replay; the bridge writes unsharded, z-zero position stores | **True with qualification.** | Replay is the only product caller; benchmarks, measurement scripts and tests also instantiate it (`zmart_viewer/rehearsal.py:199-205`). The bridge facts hold (`application/parts/storage/zarr_positions.py:92-189`). Calling it the only writer means the production orchestration, not that `RunManifest.publish` is inaccessible. |
| `record/coarse.py` is imported by nothing | **True within the Viewer repository.** | A repository-wide import search finds only the module itself and prose references. The active bake law is separately implemented in `building.py`. |
| The marker reader accepts an extra field | **True.** | It checks the schema and reads named fields without rejecting other keys (`zmart_viewer/record/manifest.py:168-190`). Its serializer drops extra fields, and the live-state reader currently treats a same-revision marker as no pixel advance (`live_state.py:261-283`), so this fact alone does not implement terminal publication. |
| Leica reports frame size before capture; neither instrument records a landing wall clock | **True with a material qualification.** | Leica state reports pixel and frame size from job settings before capture (`zmart_adapter.py:1131-1180`), and neither bridge record has a landing timestamp. But the broader plan sentence "No wall-clock time is recorded anywhere" is false: Leica records acquisition start/finish epoch times and embeds `provenance.exported_at` (`acquisition/capture.py:21-63`; `zmart_adapter.py:809-837`). Those are not the bridge landing time the new observation needs. |
| The five-axis placement bug is a strict expected failure | **True.** | The decorator has `strict=True` and explains the empty photograph (`viz_studio/tests/test_a_foreign_run_can_be_measured.py:129-158`). |

### 2. Are the nine decisions the right decisions and recommendations?

| Decision | Who decides, recommendation, and omitted consequence |
|---|---|
| 1. Through the Viewer | **Already settled by the record; recommendation right.** Phase 0 asks for the current Viewer's composer timings, so its run must pass through the Viewer. Use a temporary writable `data_dir`, the real run as `open_from`, the narrowest open capability, and a before/after source-tree check. `data_dir=<run>, allow_open=True` unnecessarily makes the external run the annotation location and enables manual construction/replay routes. Direct and Viewer modes do not show the same picture: one opens one store and the other composes a run. |
| 2. Two phase-0 runs | **The owner chooses exact fixtures, but the minimum roles are settled. Recommendation incomplete.** Name immutable folders and hashes, not "as large as the PC holds", and cover all six earlier fixture roles. State which one tests four channels, sparse coverage, live rate, and the stack/overview z contract. |
| 3. Bridge uses `LivePublisher` for pixels | **A data-layer architecture decision, not an informed up-front product choice yet. Recommendation unsupported as written.** The missing costs are the absent coarse pre-commit transaction and shard guarantee; early exact profile inputs; the new folder hierarchy; preservation of vendor TIFFs, `zmart-acquisition.json` and rich channel attributes; a governed-run Viewer open path; `linked_view`'s scale versus current operator defects; the observation/terminal API; a required cross-repository dependency; and publication failure or delay on the acquisition loop. |
| 4. Document locations | **Broad location is settled; exact paths belong to step 2. Recommendation reasonable.** The record already puts observation/lifecycle data beside the marker and the collection index above governed runs. Step 2 must add schema versions, relative portable references, atomic replacement, concurrent/index revision rules, and the complete folder example including raw data and acquisition description. |
| 5. Viewer-side accounting | **An allowed owner/engineering choice; recommendation broadly right.** Count at the server that really answered, but expose monotonic snapshots or a trace identifier rather than globally resetting shared counters. Count route, status, ranges, body bytes and errors. The accounting request itself and late requests from a previous step must not contaminate the next step. |
| 6. Per-process memory | **Already settled by the record; recommendation right.** Define Windows resident/working-set measure, sampling and peak; associate every renderer process with the measured page; and state how a browser-wide graphics process is treated when other pages exist. |
| 7. Orphan coarse module | **A maintainer/data-layer choice, not a product decision. Recommendation is not a choice yet.** "Route or retire" only restates the alternatives. Given the separate active bake, retirement plus migration of its invariant tests is the simpler starting recommendation unless step 2 proves that its API fits the new pre-commit transaction. |
| 8. Protocol numbers | **Mostly owner choices; dirty retention correctly belongs to step 2. Recommendation wrong on repetitions.** Five samples do not support p95. Use at least the twenty whole traces already required for memory, define percentile calculation, and collect enough independent live landings. Apply tolerance only to comparisons, never to the absolute 500 ms and 1 GiB gates. Explain how a 512 MiB cache fits inside the combined 1 GiB process ceiling. |
| 9. Live Leica landing | **A protocol choice; recommendation needs two modes.** Use a reproducible scripted bridge landing for the quantitative repeated trace, plus a real Leica landing as confirmation. A hand-staged directory must be completed outside the watched run and renamed into place atomically; copying files into the visible folder would measure partial arrival. Before the register exists, the protocol must define the start signal corresponding to "publication" in today's bridge. |

These are more than nine independent choices once Decision 3 is expanded. The
profile contract, linked-view mode, publication failure policy, raw-data folder,
channel authority and coarse transaction cannot safely be hidden under one yes
or no.

### 3. Does step 1 deliver phase 0 and keep the three promises?

Step 1 stays within the work the record authorises: Viewer-run opening, the
five-axis adapter fix, the ten-step trace, counter-based settle, memory reader,
two-sided instrumentation, source-read counting, request logging, frozen
protocol and then the microscope-PC run. It builds neither the new data layer
nor the new engine. `/api/accounting` and the adapter correction are changes to
the existing measurement path, but both are expressly authorised.

It does not yet deliver the promised experiment. Source reads, covered area,
counter generation, timeout, percentile sample size and all fixture roles are
missing or wrong, as finding 2 shows. It also does not independently instrument
"transfer": Neuroglancer's `totalTime` covers retrieval through successful
decode (`src/chunk_manager/backend.ts:403-447`), while server work occurs within
that interval. The protocol must describe timestamped, non-overlapping spans or
report a combined category; arithmetic over overlapping requests is not a time
breakdown.

The through-Viewer mode changes today's external-run measurement from one raw
store to the current whole-run service and composer. That is the right change
and is what the rendering record describes. Results from the two modes should
not be presented as if they differed only by server, because their scientific
extent differs. The Viewer mode must retain the external door's read-only
promise and use real coverage.

### 4. Can every `Done when` fail?

| Work item | Assessment of its completion condition |
|---|---|
| 1.1 Viewer door | **Partial.** Opening and recording the mode can fail, but does not prove whole-run extent, no source mutation, real coverage, or Viewer accounting. |
| 1.2 adapter fix | **Yes.** Removing a strict expected failure while retaining its companion is a clear regression test. Add the intended navigation/placement values to prevent a photograph-only pass. |
| 1.3 settled clock | **Partial.** The comparison can fail, but two potentially stale clocks can agree. Require post-gesture generation, non-zero needed covered chunks, equality, a following paint, explicit timeout/failure, and forced delayed/out-of-order cases. |
| 1.4 trace | **Partial.** "Runs end to end" does not prove each gesture occurred or every required field was recorded. Validate a result schema and invariants for all ten numbered steps, including useful picture and live landing. |
| 1.5 memory | **No.** Any twenty readings produce a growth number. Pin process identity, an injected allocation/deallocation check, peak sampling, and the exact 1 GiB/final-ten calculation. |
| 1.6 breakdown | **No.** A residual defined as total minus parts makes the stated sum tautological. Test source-read/cache-hit counters with known reads and bytes, route counts with known requests, clock spans with injected delays, and isolation between two trace epochs. |
| 1.7 dense fixture | **No individual condition.** Assert the frozen position count, field shape, channel/depth/time shape, bridge-written file lineage, completed scan, and successful Viewer open. |
| 1.8 protocol | **Partial.** Presence before phase 0 is checkable. Add a validator/checklist for immutable fixture identities, environment, complete matrix, repetitions, cache definitions, thresholds and result schema. |
| 1.9 phase 0 | **Partial.** A sentence and table can exist with missing runs. Require every frozen fixture-by-storage-by-cache cell, all repetitions, explicit failed measurements, commit identities, and the one-sentence conclusion. |
| 2.1-2.11 data-layer record | **No individual acceptance conditions.** The group condition proves authorship and review, not that each handed-over decision, transaction and gate is specified. Give each numbered item its own evidence checklist. |
| 3.1 publisher client | **Partial.** The three named tests are useful, but omit pixel equivalence, pre-pixel profile/layout, sharding, raw provenance and channels, the coarse-before-marker rule, all terminal outcomes, failure recovery, no relink, and performance independent of position count. |
| 3.2 coverage/dirty boxes | **No condition.** Test committed-only coverage, revision/range queries, exact boxes at every level, the retention gap, and page delivery. |
| 3.3 window key | **No condition.** Test two kinds on one channel, labels never measured, every panel state, and refusal of an absent window at the shader. |
| 3.4 collection index | **No condition.** Test stable identity, ordering, revision, same-type re-scan, interrupted index write, and Viewer grouping. |
| 3.5 measurement | **Mostly yes if the record's gates become executable.** Require a versioned result artifact for every gate on local and share, rather than the assertion that all hold. |
| Step-4 record and 4.1 | **Partial.** Review and "testable headless" are not acceptance tests. Enumerate the state-machine, eviction, generation, retry and dirty-range cases. |
| 4.2 worker and 4.3 renderer | **No individual conditions.** Add transfer-ownership, cancellation, decode failure, context loss, stale-frame, texture-budget and pixel-reference tests. |
| 4.4 fourth option | **Partial.** Require every existing harness row and the same trace result schema, not only interface similarity. |
| 4.5 numbers | **Yes in principle.** It refers to all engine gates, but must use the complete frozen fixtures and sufficient repetitions established in phase 0. |
| Steps 5 and 6 | **No.** They are roadmap descriptions; each future short record may supply its gates, but the present plan should say that no implementation starts until it does. |

### 5. Is the sequence right?

The high-level sequence is right: measurement instruments, phase 0, data-layer
record, data layer under Neuroglancer, engine record, engine, later scientific
features, then three dimensions. It honours all three promises.

The dependency table needs these corrections:

- 1.4 depends on 1.2, 1.3 and 1.6, as well as 1.1; its completed mock run also
  depends on a suitable fixture from 1.7.
- 1.5's reader can be developed independently, but its stated completion
  depends on 1.4 and therefore its upstream items.
- 1.7 can be scripted now, but its final frozen shape depends on Decision 2 and
  the protocol.
- 1.8 depends on Decisions 2, 5, 6, 8 and 9 and can be drafted earlier than
  1.4; it is frozen only after the instruments' exact fields are known.
- 1.9 also depends on a named Leica dataset, a reproducible landing source and
  the target-machine environment, not merely on merged code.
- Step 2 depends on the phase-0 coarse-level result and all relevant settled
  data decisions, not just Decisions 3, 4 and 7.
- Viewer-side parts of 3.2, 3.3 and 3.4 can start after the data-layer record;
  they need 3.1 for integrated completion, not for all development.

Items 1.2 and 1.3 genuinely can start now. The implementation part of 1.5 can
start now, but its current `Done when` cannot. Item 1.7 can start as a
parameterised generator, but its frozen fixture cannot be completed before the
fixture decision. Item 1.1 can also start now because Decision 1 is already
settled by the rendering record.

### 6. Are the sizes believable?

I would double these estimates:

- **1.3, medium to large:** it reaches into pinned Neuroglancer internals and
  must associate asynchronous statistics with the current view, failures and a
  final paint rather than merely expose two numbers.
- **1.5, small-to-medium to medium:** reliably mapping a Playwright page to all
  Chromium renderer processes and a shared graphics process on Windows, then
  sampling peaks, is not a small reader.
- **1.6, medium to large:** it spans both repositories, needs a genuine physical
  read/byte counter, thread-safe trace scoping and independent tests for server
  and browser spans.
- **Step 2, medium to large:** eleven subjects include a new publication
  transaction, two schema extensions, a storage layout, cross-run indexing and
  a measured cost branch. That is more than a one-week record for one person if
  reviewed honestly.
- **3.1, one large item to several large items:** split profile/layout creation,
  canonical pixel writing, observation/commit, terminal publication, Viewer
  opening and backward-compatible provenance. The current single item hides
  independent failure boundaries.
- **3.2 and 3.4, medium to large:** revisioned dirty history and a durable
  cross-run index each require recovery and compatibility tests, not just new
  fields.
- **3.5 and 4.5, medium to large or days on site:** both run a matrix over real
  and mock data, local disk and share, cold and warm states, with repeated
  percentiles.

I would not halve any item before the completion conditions are repaired. Item
1.7 may remain small if it only parameterises the existing mock bridge helper;
generating, validating and retaining the full frozen fixture is medium work.

### 7. What does step 2 leave out or decide at the wrong time?

Against the record's hand-over, step 2 has these results:

| Handed-over matter | Plan coverage |
|---|---|
| Dirty-box retention N | Covered in 2.7. |
| Lazy-middle tile size | Implicit in 2.8's all-level table; name this choice explicitly. |
| Numerical guard's share | **Omitted.** |
| Irregular-z tolerance | Covered in 2.5. |
| Exact observation and lifecycle shapes | Begun in 2.2/2.3, but schema, coordinate/acquisition references, terminal transaction and new-reader behaviour remain. |

Against the record's full step 2, the plan also omits or weakens: the compatible
terminal transaction; explicit schema versions; the acquisition-display
contract reference and stable key-to-index/window map; x/y/z datum and rounding;
the new reader's planned/arrived/skipped states; and a tested shard declaration
for every retained multi-chunk level. It must state how dirty boxes give the
later engine a reproducible per-tile content generation, even if the engine
record defines the cache data structure.

The plan reopens the kept-coarse decision by postponing its numbers to step 3,
although phase 0 is supposed to settle that branch before step 2. It also treats
use of `LivePublisher` as settled before the data-layer record has compared the
transaction and migration costs. Conversely, it selects "the lower plane owns
a shared edge" and concrete document paths. Those are legitimate data-layer
choices, but they should be decisions *inside* step 2 with reasons and tests,
not presented as already settled inputs. The record's broad half-open rule and
document neighbourhood do not by themselves choose those exact forms.

### 8. What is still wrong?

The false statements are that `tile_reads` is a storage-boundary source-read
count, that `LivePublisher` already shards every level, that it performs the
run-wide coarse rebuild in its publication step, that settled means two equal
photographs, and that no wall-clock time is recorded anywhere. The unsupported
inferences are that the Leica frame-size report is enough to seal a complete
profile, that the current publisher can accept an observation reference in its
commit, and that opening a governed run once follows merely from switching
writers.

The risk list names genuine issues around the early profile, network-share
visibility and cross-repository delivery. Its 500 ms item is a prerequisite,
not yet the more important risk: Neuroglancer's counters can describe an old or
empty view unless tied to the gesture generation. The list omits the
coarse-after-commit split, linked-view choice, loss of the acquisition channel
contract, changed optional-dependency/failure boundary, synchronous publication
slowing acquisition, non-atomic staged arrival, global accounting-reset races,
and migration of existing run consumers.

For a microscopist, most of the plan is admirably concrete. The sections using
*residual*, *inode*, *route*, *dirty box*, *fingerprint* and *shard* still need a
short plain-language explanation of what the operator would see when each goes
wrong. For example, the coarse transaction is not bookkeeping: without it, the
same newly acquired field can appear at one zoom and remain old at another.

## Decisions I would take differently

I would treat Decision 1 and the process-level part of Decision 6 as settled,
not ask the owner to decide them again. I would expand Decision 2 to the six
frozen fixture roles and replace Decision 8's five samples with at least twenty
whole traces. I would use a scripted bridge landing for repeated numbers and a
separate live Leica confirmation for Decision 9. Most importantly, I would not
take Decision 3 until step 2 has designed a narrow publisher transaction and
proved, with a small compatibility spike, how it preserves the TIFF provenance,
acquisition-wide channel contract, sharding, coarse-before-marker rule and
single-open Viewer path. My preference remains one Viewer-owned publication
API, but "one API" does not require accepting the current `LivePublisher`
unchanged or allowing it to become a second account of the experiment.

## Paste-back before this plan is used for the data-layer discussion

> Recast Decision 3 as a data-layer architecture decision. The current
> `LivePublisher` writes position pyramids but neither guarantees shards nor
> updates the kept run-wide coarse picture before the marker. Specify or spike
> one bridge-facing transaction that also accepts the observation reference,
> preserves the acquisition channel contract and raw provenance, publishes a
> compatible terminal state, and opens the governed run once in the Viewer.
>
> Repair phase 0 before freezing its protocol: count actual source-array reads
> and bytes, bind needed/available counters to the post-gesture view and paint,
> make timeout a failure, retain real coverage, use enough whole-trace repeats
> for p95, and name datasets covering all six earlier fixture roles. Define
> non-overlapping timing categories rather than proving a residual by
> subtraction.
>
> Move the kept-coarse choice and its measured cost into phase 0 and step 2,
> before implementation. Add the numerical guard, lazy-middle tile size,
> coordinate datum and rounding, schema/acquisition references, terminal-reader
> behaviour, and exact sharding rule to step 2.
>
> Replace procedural `Done when` clauses with a failing test or measurement for
> every numbered item, correct the dependency table, split 3.1, and increase
> the estimates for settling, accounting, memory, the data-layer record and
> publisher integration.
