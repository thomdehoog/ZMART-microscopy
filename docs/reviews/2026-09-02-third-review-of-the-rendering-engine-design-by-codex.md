# Third review of the rendering-engine design

Date: 2026-09-02

## Verdict: accept with changes

The third revision has kept the architecture that both second reviews accepted.
It now separates the acquisition plan from observations made during capture,
uses three kinds of tile identity, makes the first engine small, authorises the
measurement-harness work before phase 0, and keeps Neuroglancer on the operator
page until a replacement has passed the same tests. Those are substantial and
faithful corrections.

I would not yet hand the record to the data-layer design unchanged. The proposed
terminal publication cannot produce the promised result for an older Viewer,
because the current reader requires every advance of the run or layout revision
to be justified by a pixel commit. The dirty-box protocol also needs one exact
rule for advancing a tile's content generation. Finally, phase 0 still describes
three overlapping browser costs as if subtraction could separate them, and the
request and channel gates refer to fixtures as "named" or "stated" without
actually naming them. These are specification repairs. They do not reopen the
decision to build the engine.

## Scope and evidence

I read ZMART-microscopy commit
`12c5f815195844ee53f4d9395002855d7e1e4d0e`; the design record itself was last
changed in its parent, `d80717b2`. I read ZMART Viewer commit
`9b67bf8e843b5b80145f210fb3b180e2fce554ff` and Neuroglancer 2.41.2 at its pinned
source commit, `e13f1f4c62918f2ea07b12f2116bdcb6767b1499`. I used fresh checkouts for
the two ZMART repositories. I read the whole record, both second reviews, the
rewritten larger-than-memory prior-art note, the applicable earlier gates, and
`CLAUDE.md`. I did not implement or run the proposed engine.

## Findings, ordered by consequence

### 1. The selected terminal-state mechanism does not yet keep its compatibility promise

**Facts.** The record chooses additive fields under the existing schema. It says
that the final layout carries the positions that will never arrive, that the
publication marker carries the terminal state, and that an older Viewer ignores
the additions and therefore displays a stopped run as a slow one
(`docs/design/own-rendering-engine-and-position-register.md:303-319`). The
current layout has only a Boolean `final` field; a skipped-position list would be
new (`zmart_viewer/record/model.py:1271-1281`, `:1365-1395`). Both the layout and
publication-marker readers ignore unknown fields, so additive fields themselves
are compatible (`model.py:1381-1395`; `zmart_viewer/record/manifest.py:168-199`).

The publication rules are the problem. If `signed.json` keeps the same run
revision but names a different layout revision, the current live-state reader
rejects it. If the run revision advances, that reader requires one recognised
pixel event for every new revision and then requires those events to reproduce
`by_store` and the layout revision exactly
(`zmart_viewer/record/live_state.py:261-325`). A terminal or skipped event cannot
supply that event because the closed event list accepts only position committed,
timepoint committed and position replaced
(`zmart_viewer/record/model.py:597`, `:1452-1456`). The record says the lifecycle
record advances the publication marker without being mistaken for pixels, but it
does not say whether "advances" means replacing the file while leaving its pixel
revision unchanged or increasing that revision (`own-rendering-engine-and-position-register.md:309-318`).

There is a related cross-run ordering question. The collection index orders the
governed runs that form one collection (`:209-218`, `:303-305`), while the
display rule says that the position committed later wins an overlap (`:200-205`).
Independent run manifests have independent revision counters, so the word
"later" is not defined between two governed runs.

**Inference.** The additive choice can work, but the record must state the
publication transaction. One compatible form is a new immutable lifecycle
document referenced by extra fields in `signed.json`, with `revision`,
`by_store` and `layout_revision` left unchanged for a terminal-only update. A new
reader would react to the changed marker fingerprint and read the lifecycle
document; the old reader would ignore the extra fields and continue to show the
last pixels. A newly published final layout cannot be part of that compatible
transaction unless the validation rules are changed in a way that an old reader
already accepts. The record should also say whether the collection index order
or a collection-wide landing sequence decides overlap between governed runs.
These choices belong in the rendering record before they become inputs to the
data-layer record.

### 2. Phase 0 is authorised, but its breakdown and two of its gates are still not fully specified

**Facts.** The three promised pieces of harness work are now authorised by name
and placed first (`own-rendering-engine-and-position-register.md:84-101`,
`:705-711`). The phase-0 gate nevertheless still says that phase 0 occurs
"before anything else is built" (`:652-660`). Read literally, that sentence
forbids the harness work that step 1 correctly permits.

Neuroglancer's download time runs from the request through decoding. Server work
and transfer happen inside that span, and several requests can overlap. The
record then lists server work, transfer, download-plus-decode, and hand-off,
upload and drawing "by subtraction" as a breakdown (`:654-660`). One residual
can report the combined browser tail, but it cannot separately identify
hand-off, upload and drawing. Subtracting overlapping concurrent spans also does
not yield a valid additive time account.

The request gate says "the named sparse plate" and "the named dense plate", but
neither plate is named in the record (`:678-703`). The visible-channel gate
similarly says "the stated visible-channel fixture" without stating a count or
fixture. The earlier ten-step trace enables four channels, but this record does
not bind that step to this gate (`docs/design/lazy-jpeg-pyramids-for-the-viewer.md:402-416`).
The dirtying gate says "exactly its footprint and nothing else, byte for byte"
without saying whether it compares dirty tile keys, tile payloads, masks, or
screen pixels (`own-rendering-engine-and-position-register.md:692-693`).

**Inference.** Change the phase-0 sentence to "after the named harness work and
before data-layer or engine work." Treat hand-off plus upload plus drawing as one
labelled residual unless new timestamped spans can separate them; do not name
three causes from one remainder. Freeze actual fixture identifiers, the visible
channel count, repetitions and cache states before the run. Define the dirtying
gate as an expected set of output-tile keys plus byte-and-mask comparisons for
the changed and unchanged regions. With those changes, every gate has an
observable pass or failure.

### 3. The new identities have the right shape, but the content generation and placement version need exact meanings

**Facts.** The record now distinguishes a raw source chunk, an assembled slice
tile and a stored projection (`own-rendering-engine-and-position-register.md:419-437`).
The raw identity is tied to a governed run and a position generation. The
assembled identity includes orientation, slice axis and coordinate, placement,
level and tile coordinates. The stored projection adds its axis, half-open range,
kind, recipe version and input generations. Display window, colour and opacity
are correctly kept out of pixel identity.

An assembled tile's content generation is said to advance only for tiles touched
by a dirty box, but the record does not define its value or how a reader derives
it (`:424-430`). It also calls `placement` part of the key without saying whether
that means only a mode name such as low-edge alignment, or the identity and
revision of the presentation transform and calibration. Elsewhere it says that
placement transforms have provenance and that the collection index hangs off
every cache key (`:143-144`, `:209-218`). Neither a placement revision nor a
collection-index revision appears explicitly in the identity list.

The invalidation rule says that one landing's replacements appear together and
that this is exactly what the maintained Neuroglancer patch does (`:495-509`).
The patch does preserve old pixels while fetching replacements, and it sends
staged successes back-to-back. It also has a two-second timeout that flushes only
what has arrived, and it does not mark the old Neuroglancer chunk as stale for a
measurement (`viz_studio/frontend/scripts/patch_neuroglancer.mjs:97-165`). Thus
the patch is strong evidence for keeping the old picture on screen, but it is not
the complete stale/current and all-replacements transaction specified for the
new engine.

**Inference.** Define the content generation of an assembled tile as, for
example, the greatest accepted run revision whose dirty box intersects that
tile. On each landing, enumerate only the tile grid covered by its dirty boxes
and advance those entries; do not scan all cached tiles. A reopened process has
an empty memory cache, while any persistent derivative must carry a durable
validator that can reconstruct the same answer. Make the versioned placement,
calibration and collection-index identity explicit in assembled and stored
derivatives. Describe the existing patch as the visual precedent, and keep stale
labelling, measurement exclusion and complete-group publication as new-engine
requirements with a defined failure rule.

### 4. The scheduler inventory is much better, but two statements are promises to specify a rule rather than rules

**Facts.** The inventory now covers Neuroglancer's visible, prefetch and recent
tiers; item and byte budgets; destination states; request pressure; batched
reprioritisation; time-sliced upload; buffer ownership; needed-versus-available
counters; shared sources; coarse-for-fine drawing; graphics-context recovery;
and a measured decode-worker count (`own-rendering-engine-and-position-register.md:438-494`).
Those features are present in the pinned source
(`src/chunk_manager/README.md:14-59`, `src/chunk_manager/frontend.ts:100-180`,
`src/chunk_manager/backend.ts:660-1087`, and
`src/async_computation/request.ts:17-123` in Neuroglancer).

The record says that the composite-priority arithmetic and tie-break are
"stated", but gives neither. It likewise says that ordering between a revision
bump and an in-flight delivery is "stated", without stating which wins
(`own-rendering-engine-and-position-register.md:444-447`, `:473-474`). The
prefetch and upload budgets and permanent retry limit are described as stated
numbers but no numbers or rule for choosing them appears here. Those values may
properly belong to the later engine design, but the present tense makes the
current record sound complete.

There is one direct mismatch with the heading "What neuroglancer does". The
record says a failed request is retried with back-off. Pinned Neuroglancer sets
the chunk to `FAILED` and retains the error; this path has no automatic
back-off retry (`src/chunk_manager/backend.ts:171-174`). Retrying with a visible
permanent-failure state can be a better policy for ZMART, but it is our proposed
policy, not Neuroglancer's behaviour.

**Inference.** Mark the arithmetic, tie-break, delivery ordering and numerical
budgets explicitly as decisions for the later engine record, or decide them
here. Move retry with back-off under a clearly labelled ZMART addition. This
does not block the data layer, but it is needed for the decisions section to say
truthfully that the scheduler finding was carried whole.

### 5. Three cross-section wording errors would send the next designer in different directions

**Facts.** Low-edge aligned placement is both today's default and the placement
of the first engine (`own-rendering-engine-and-position-register.md:145-163`,
`:723-730`). The order of work then lists "aligned placement with its stated
meaning" as a later milestone (`:731-735`). The likely intended later feature is
a selectable placement mode; aligned placement itself is already present.

The glossary correctly defines a composed piece as 512 voxels and a source chunk
as 128 voxels (`:12-18`, `:383-388`). The data-layer section nevertheless says
"the piece size of 128" (`:369-374`). The decision is clear--levels below the
128-voxel source-chunk level may be omitted only when the kept coarse pyramid
exists--but the noun is wrong.

The rewritten prior-art body now removes the universal atlas and WebGPU claims.
One sentence still says that Neuroglancer's volume renderer reuses its slice
cache, "which is the same reuse our design promises"
(`docs/design/prior-art-larger-than-memory-3d-rendering.md:66-73`). The rendering
record promises only separation of source, cache policy and drawing, and says a
later volume renderer chooses its own representation
(`own-rendering-engine-and-position-register.md:249-263`). It no longer promises
one cache for both dimensions.

**Inference.** Say "levels below the 128-voxel source-chunk level", call the
later placement milestone "selectable placement modes", and remove the claimed
same-cache promise from the prior-art note. These are small edits, but leaving
them would turn settled inputs into contradictory instructions.

## Answers to the eight questions

### 1. Were the second-round findings carried faithfully this time?

The classifications below use "carried weaker" when most of a finding appears
but a requested rule is replaced by a promise, placeholder or incompatible
mechanism.

#### My six findings and paste-back

| Finding | Result | Evidence |
|---|---|---|
| 1. Separate planned, observed and lifecycle facts; keep one complete profile per governed run and add the collection index | **Carried weaker.** | Planned layout, per-landing observation, lifecycle record and cross-run index are all present (`:265-338`). The chosen final-layout publication cannot yet be accepted by the old reader as promised, as finding 1 above shows. |
| 2. Replace the run-wide cache key with three identities and local generations | **Carried weaker.** | All three identities, exact slice coordinate, placement, recipe and shader-state separation are present (`:419-437`). The per-tile generation algorithm and versioned placement/index identity are still implicit. |
| 3. Settle plane intervals and later scientific arithmetic before implementation | **Carried whole.** | The data-layer record is required to settle half-open intervals, edge ownership, irregular and reversed observations, channel/time association and calibration (`:126-144`); later projection and side-view records must settle their arithmetic and orientation before those features are built (`:164-193`, `:731-735`). |
| 4. Complete the scheduler and measure worker count | **Carried weaker.** | The omitted behaviours and operator consequences are now listed and worker count is measured (`:438-494`), but priority arithmetic and delivery ordering are still placeholders, and retry is incorrectly attributed to Neuroglancer. |
| 5. Authorise instruments and make every gate measurable | **Carried weaker.** | The harness work, memory rule, cold/warm tolerance, storage-boundary reads, panel test and complete inputs are present (`:652-711`). The contradictory "before anything else", unnamed plates, unstated channel fixture and indivisible browser residual remain. |
| 6. Correct the scale facts and state every numerical case | **Carried weaker.** | The cases, hypotheses, re-scan refusal, sharding rule, worker hypothesis and accumulator correction are present (`:340-417`, `:590-598`, `:644-650`). The 128-voxel "piece" is a terminology error, and the base kept-level build is 150,000 source reads rather than an exact 200,000. |
| Paste-back as a whole | **Carried weaker.** | Every paragraph has a corresponding section, but the terminal transaction, local-generation rule, scheduler details and gate fixtures are not yet complete. |

#### The internal review's sixteen findings and paste-back

| Finding | Result | Evidence |
|---|---|---|
| 1. Phase 0 lacked authorised instruments | **Carried weaker.** | The three tasks are authorised in step 1, but the gate still says phase 0 is before anything else is built and subtraction cannot split three browser costs. |
| 2. Replace stale tiles; do not drop them | **Carried whole.** | The design rule keeps stale pixels, groups replacements, excludes stale measurements and handles removed coverage (`:495-509`). The sentence claiming exact equivalence with the existing patch is separately too strong. |
| 3. Rewrite the prior-art body | **Carried weaker.** | The two universal sections were rewritten, but the body newly retains a same-cache promise that the rendering record withdrew. |
| 4. Keep micrometre observations out of the whole-pixel layout | **Carried whole.** | The observation is a separate per-landing document; the store's regular step draws and raw heights remain provenance (`:292-302`). |
| 5. Treat each complete profile as a governed run and add a cross-run collection index | **Carried whole.** | Both decisions are explicit in the collection and register sections and in step 2 (`:209-218`, `:303-305`, `:712-719`). |
| 6. Choose a lifecycle compatibility mechanism | **Carried weaker.** | Additive fields and the intended old-Viewer experience are chosen (`:309-319`), but the proposed final-layout publication is incompatible with the existing revision checks. |
| 7. Put the `(channel, kind)` authority change in the work order | **Carried whole.** | The contract, `setChannel` addition, label exclusion and step-2 work are explicit (`:219-230`, `:578-579`, `:718-719`). |
| 8. Name the refused absolute-first recommendation | **Carried whole.** | It is named and answered under "Not taken" (`:606-612`). |
| 9. Restore the process-level memory gate | **Carried whole.** | The 1 GiB, twenty-cycle and growth rules sit beside the cache budget (`:688-691`). |
| 10. Name sparse and dense request fixtures | **Carried weaker.** | The two cases are distinguished, but "named sparse plate" and "named dense plate" are placeholders rather than names (`:686-687`). |
| 11. Keep one plate case per numerical statement | **Carried whole.** | The 512 and 2048 cases are separate and the common assumptions precede them (`:340-355`). |
| 12. Complete the Neuroglancer scheduler inventory | **Carried weaker.** | The inventory is substantially complete and readable (`:438-487`), but two rules remain self-referential promises and failed-request retry is not Neuroglancer behaviour. |
| 13. Decide single-plane thickness, turned positions, time and drawing height | **Carried whole.** | A flat field persists through aligned offsets, the first engine refuses turned layouts, time is a collection moment index, and the regular store step draws (`:114-120`, `:126-174`). |
| 14. Remove position generation from composed tiles and add placement and slice units | **Carried weaker.** | These fields are corrected (`:421-437`), but placement is not explicitly a versioned transform and the new content generation has no advancement rule. |
| 15. Shard every retained multi-chunk level and omit sub-128 levels only if coarse levels are kept | **Carried whole.** | The conditional and the estimated remaining file count are explicit (`:362-379`). "Piece size of 128" is a wording error, not a different sharding decision. |
| 16. Correct shard, re-scan and glossary details | **Carried whole.** | The shard rewrite is described as about half and growing; refusal is placed at the vendor-file move; and every term named by the review is glossed (`:12-41`, `:284-291`, `:375-379`). |
| Paste-back as a whole | **Carried weaker.** | Its architectural choices all landed, but findings 1, 3, 6, 10, 12 and 14 above are not yet whole. |

No second-round finding was silently refused. The only explicit refusal in that
round, the absolute-first milestone, is now named and reasoned openly.

### 2. Is the record ready to hand to the data-layer design?

Not unchanged. The planned layout, observation document, complete profile per
governed run, collection index, committed-only coverage, old-and-new dirty boxes,
tile sizes, cost-model inputs, sharding rule, conditional single-file-level rule,
new-collection re-scan rule and `(channel, kind)` window authority are clear
enough to design. Phase 0 is also correctly placed before that record, so its
result can choose the coarse-level branch.

The data-layer designer would still have to invent the terminal publication
transaction, the ordering of overlapping commits across governed runs, and the
durable rule that maps dirty boxes to tile content generations. Those are inputs,
not harmless coding details. The designer must also resolve two textual
contradictions: low-edge alignment is both the first engine's placement and a
later milestone, and 128 voxels is called a piece even though a piece is 512.
The coordinate record is correctly required to choose z direction, centre-to-edge
conversion, outer edges, irregular/duplicate/reversed observations and
calibration. Those remain design tasks, but step 2 and its review keep them out
of implementation code.

### 3. Are the three phase-0 promises enough, and are they kept by the rest of the record?

The three promises are enough as product controls. They make the measurement
runnable, prevent an unproved renderer from replacing the operator's current
engine, and allow a successful data layer to reduce the first engine. Promises 2
and 3 are repeated consistently in the choices, gates and work order
(`:94-101`, `:111-113`, `:720-730`). Promise 1 is honoured by step 1 but
contradicted by the gate's phrase "before anything else is built." It also
promises more attribution than subtraction can supply. With one wording change
and one combined browser-residual category, the rest of the record keeps all
three promises.

### 4. Are the three tile identities right?

They are the right three identities and most fields are right. A raw chunk is
properly tied to the sealed governed run and its position generation. An
assembled slice properly includes placement, orientation, slice axis and exact
coordinate. A stored projection properly includes its scientific range, kind,
recipe and input generations. Placement belongs in the assembled and derived
keys because the same source pixels compose differently under low-edge and
absolute placement.

The dirty-box protocol can advance content generations without a global scan,
but the record must say how. Enumerating the tile rows and columns intersected by
each box updates only touched entries; using the greatest intersecting accepted
revision as their generation gives a reproducible validator. A memory cache can
start empty after reopen. Stored products need that validator durably. The still
missing invalidators are explicit versions for the placement/calibration and the
collection index. If those identities are included, later calibration, changed
run membership or overlap order cannot silently reuse old assembled tiles or
projections.

### 5. Does the scheduler section match Neuroglancer where it says it does?

Mostly. The tier and admission order, view-velocity prefetch, item and byte
capacities, destinations in worker/main/graphics memory, pressure-driven abort,
batched maximum priority, asynchronous decode pool, time-limited upload,
buffer transfer, shared sources, and needed-versus-available counters all have
counterparts in the pinned source. The record's single worker as a starting
point, with a pool if decode becomes the bottleneck, is a measured ZMART choice
and does not claim to copy Neuroglancer's worker count.

Three qualifications remain. Neuroglancer's failed state does not automatically
retry with back-off, so that policy must be labelled as ours. The record does not
actually give the promised priority arithmetic/tie-break or revision-versus-
delivery ordering. Its no-pixel outcomes are understandable as never requested
because coverage is absent, requested and confirmed empty, and failed; a queued
or downloading tile is represented by needed-but-not-available counters, but
naming that pending state would make the list easier to follow.

### 6. Are all gates measurable after the authorised harness work?

Not all as written.

| Gate | Assessment |
|---|---|
| Phase-0 breakdown | **Not separable as written.** Timestamped server and browser spans are measurable, and one combined residual is measurable. Three residual causes cannot be obtained from one subtraction. |
| Open without listing positions | **Measurable.** Count file operations on the Viewer side. |
| Relink by fingerprint | **Measurable.** Count the marker stat and subsequent reads. |
| Kept coarse tile and publication order | **Measurable.** Count storage reads and assert that every dirty piece is current before publication. |
| Coverage suppresses empty output tiles | **Measurable after the plate is identified.** Compare the request ledger with output-tile footprints. |
| Landing visible at p95 | **Measurable.** The record names start and finish and requires enough landings. |
| First useful picture and navigation | **Measurable.** The earlier 90%-coverage definition, cold/warm split and declared tolerance make these honest comparisons. |
| Requests and bytes | **Not runnable yet.** Sparse and dense are categories, not fixture names. |
| Process and cache memory | **Measurable.** The process-level repetition and growth bounds catch memory that cache accounting misses. |
| Exact dirtying and stale exclusion | **Ambiguous.** Define the expected dirty-key set, payload/mask comparison, and what a timed-out replacement group does. |
| Panel states and absent shader window | **Measurable.** The record correctly assigns this to application-level tests. |
| Native TIFF and OME-Zarr inputs | **Measurable.** Complete fixture requirements are stated. |
| Visible-channel limit | **Not runnable yet.** State the fixture and count; four channels from the earlier trace is a defensible initial choice. |

No gate is impossible in principle. The two unnamed fixtures, dirty comparison
and browser residual must be fixed before results can be called pass or fail.

### 7. Are the numbers and their cases right?

The two plate cases are right for the printed assumptions. For a 512 by 512
`uint16` field, the seven position levels contain 25 chunks per channel and
eight Zarr description files, giving about 330,000 files and 6.51 GiB for
10,000 one-channel positions. For a 2048 by 2048 field, the nine levels contain
345 chunks per channel; three channels plus descriptions give about 10.45
million files and 312.5 GiB.

After retaining levels 0 through 4, sharding levels 0 through 3 once per
channel-plane, and omitting levels 5 through 8, one position has approximately
12 shard files, three level-4 chunks and six Zarr metadata files. That is about
210,000 position-store files for the plate, so "about 200,000" is fair. It does
not count the vendor TIFFs, whose count depends on the acquisition, and the
record should keep that boundary explicit.

The kept-level cost is also right. There are 625, 169, 49, 16 and 4 composed
pieces at levels 4 through 8, or 863 per channel and 2,589 for three channels.
At 512 by 512 by two bytes, that is about 1.26 GiB, reasonably written as about
1.3 GiB.

The read estimate needs a label. On the stated aligned, no-overlap 100 by 100
plate, building all five kept levels reads one single-chunk position level per
position, channel and level: `10,000 x 3 x 5 = 150,000` source reads. Multiplying
every output tile by its maximum fan-in, including partially filled edge tiles,
gives 198,384 and explains "on the order of 200,000", but it is an upper
estimate, not the base-case count. Once the kept product exists, reading every
kept output piece once is 2,589 reads. The phrase "warming the kept levels"
should say whether it means building them from position stores or reading the
already-kept product. The local/share durations are correctly labelled as
estimates.

### 8. What is still wrong?

The false or over-strong statements are these: the present patch does not
provide the whole stale/current measurement contract or an unconditional
all-replacements transaction; Neuroglancer does not retry failed chunks with
back-off; and the prior-art note says this design promises slice/volume cache
reuse when it deliberately does not. The terminal compatibility claim is not
yet supported by the current reader's validation rules.

The hypotheses about share scan time, raw-versus-compressed bytes and worker
count are now labelled honestly. The glossary is long but useful, and the
scheduler's statements about what the operator would see make a difficult
section much easier to follow. I would still gloss *landing*, *governed run*,
*half-open interval* and *settled*, because all four carry important meaning for
a microscopist.

The "Not taken" reasons are open and mostly hold. The refusal of an absolute
first slice is justified by what it would show on a flat plate and by the need to
match today's useful view first. Its claim that absolute placement has no data
is only temporary: step 2 is intended to record the heights and calibration
before the first engine is designed. The lasting reason is therefore operator
usefulness, not permanent absence of data. The engine decision itself remains a
legitimate product decision under the three promises.

## Readiness for the data-layer design

The record is ready to start the data-layer design after the changes in findings
1 through 3 are pasted back; it is not ready to be treated as a closed hand-off
at `12c5f815`. The data-layer direction is stable, and no architecture needs to
be reconsidered. What remains is to make the terminal transaction compatible,
define the local content-generation rule and its versioned placement inputs,
and replace gate placeholders with actual fixtures and one honest browser
residual. The scheduler and editorial corrections can be made in the same edit
without delaying phase 0.

## Paste-back before the data-layer design record

> Define a terminal-only publication that an old Viewer already accepts. If
> compatibility is kept, reference an immutable lifecycle document from
> additive marker fields without changing the pixel or layout revision; do not
> publish a new final layout through a path that requires a pixel commit. Define
> overlap order between governed runs in one collection.
>
> Say that phase 0 follows the three named harness tasks and precedes data-layer
> or engine work. Report hand-off plus upload plus drawing as one residual unless
> timestamped spans separate them. Name the sparse plate, dense plate and visible
> channel fixture, and define the dirtying comparison and timeout outcome.
>
> Define a tile's content generation from intersecting dirty boxes and make the
> placement/calibration and collection-index revisions explicit in derived tile
> identity. Describe the existing patch as evidence for no blank frame, not as
> the complete stale-measurement transaction.
>
> Label retry with back-off as ZMART policy, leave the exact scheduler choices to
> the engine record explicitly, change "piece size of 128" to "source-chunk
> level of 128", call the later milestone selectable placement, remove the
> prior-art same-cache promise, and label 200,000 reads as an upper estimate
> beside the 150,000 aligned base case.
