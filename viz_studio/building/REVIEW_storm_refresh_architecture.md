# Review of the storm fix and the live-view architecture

This answers `PROMPT_fable_review_storm_refresh_architecture.md`. It reviews the
work on branch `codex/diagnose-storm-bake-catchup` in the range
`f4056177..184d0931`, against the record in
`HANDOVER_codex_storm_bake_and_client_staleness.md`.

## What this review could and could not see

The review was carried out by reading the code, the tests and the campaign's
written record. Two limits are worth stating plainly at the start, because they
decide how much weight several findings below can carry.

The saved evidence under `D:\zmart-codex-diagnosis-20260814` lives on the
operator's Windows workstation and was not reachable from here. Every number
quoted from a run is therefore taken from the handover and the prompt as
written, not independently re-measured.

More importantly, `viz_studio/frontend/node_modules` is not installed in this
checkout, so the pinned Neuroglancer source could not be read. Several questions
the prompt asks are questions *about Neuroglancer's own behaviour*, and those
are marked below as inferred rather than established. Finding C4 in particular
rests on a mechanism that a twenty-minute read of the installed
`chunk_manager/backend.js` on the T400 would either confirm or dismiss, and that
read is the single most valuable next step in this whole review.

---

## 1. Executive verdict

**Ship the backend fix. Do not yet accept that the client defect is closed.**

The backend work is the strongest part of the campaign. Serializing derive →
patch → stamp → install, making installation forward-only by folded identity,
giving catch-up an announcement-driven driver that no longer depends on a client
happening to ask, and retrying only Windows sharing-shaped replacement failures
are all correct, and each is backed by a named regression test. I found no way
to falsify that part.

The client work is also, as far as I can tell, correct in direction: removing the
arbitrary two-second deadline is right, single-flight per source is right, and
preserving the chunk object's identity rather than replacing it is right. The
evidence behind it — exact warm-versus-reload pixel equality at every band, all
six pumps ending idle with no failures, and the operator's own verdict that the
picture heals — is real evidence and it is better than what the previous campaign
produced.

What blocks the claim of closure is not the fix. It is the guard. The committed
regression asserts a great deal less than the campaign measured (finding C2), so
the branch's best evidence is a manual artefact rather than something CI will
defend. Alongside that, two genuine holes remain open: a transient backend fault
is still served to the client as a confident empty chunk (C1), and removing the
deadline replaced a bounded-abandonment failure with an unbounded-stall failure
(C3).

None of the three is expensive to close. C2 in particular is roughly twenty lines
and turns the campaign's strongest measurement into a standing guard. My
recommendation is to merge the backend, land C1, C2 and C6 before calling the
client work done, and treat C3, C4 and C5 as the medium-term hardening pass.

---

## 2. Correctness findings, most severe first

### C1 — A transient backend fault is served as a successful empty chunk. High. Confirmed from code.

This is a direct answer to the prompt's backend question 5, and the answer is
yes: there are three production paths that turn a temporary fault into
indistinguishable, permanent-looking absence.

- `served.py:196-203` — any exception while opening a picture is caught, the
  store is remembered in `_refused` for two seconds, and `None` is returned.
- `served.py:320-324` — a `GovernedRun.composer()` that raises is logged and
  answered with `None`.
- `served.py:351-354` — any failure inside `bytes_for` is logged and answered
  with `None`.

All three arrive at `server.py:427` (and `:412` for the built door), which sends
`_send_empty(HTTPStatus.NOT_FOUND)`. The prompt states that Neuroglancer's HTTP
kvstore treats 403, 404 and network status 0 as legitimate missing data. A 404 is
therefore not a fault the client will retry; it is an answer, and the answer is
"there is nothing here."

The failing sequence is short. A second process patches the same store — the
configuration `_holding_the_bake_lock` exists to support — and holds the bake
lock for more than the ten seconds `msvcrt.locking(LK_LOCK)` waits at
`governed.py:120-133`. The derive raises. `the_bytes_behind` answers `None`. The
server sends 404. The client paints fill and stops asking. If the chunks that
were requested during that window cover ground whose positions are already
committed, no later announcement will ever name them dirty again, so nothing will
correct the hole for the rest of the session. The operator sees exactly the
symptom this campaign has been chasing — a warm view with less picture in it than
a reload produces — arriving through a door nobody was watching.

The docstring at `governed.py:126-128` says the derive failure "is answered as
absence and retries: the fail-closed direction, never a stale file." The first
half is right and the second half does not hold at the client: nothing retries,
because nothing was told there was anything to retry.

The fix is small and uses machinery this very campaign chose to rely on. Answer
`503` (or `429`) for "I cannot answer this right now" and keep `404` for "there
is no ground here." Neuroglancer's HTTP reader already retries 429, 503 and 504
with bounded exponential backoff — that property is the stated reason the worker
pump was allowed to drop its own retry policy, so the same property should be
made to serve the file door too. This also happens to be the first concrete step
of the prompt's architectural point 6 (status semantics), delivered for almost
nothing.

### C2 — The committed gate does not assert what the campaign measured. High. Confirmed from code.

The operator-scale gate's only assertion is at
`test_a_commit_storm_under_zooming.py:1334-1344`:

```python
assert stormy >= reloaded - 0.03
```

`stormy` and `reloaded` are `fraction_lit` — the fraction of sampled pixels
brighter than a threshold. Meanwhile the pixel-identity measurements the handover
leads with — `missing_fraction`, `changed_fraction` and `mean_absolute_error` —
are computed at `:1196-1246` inside `if debug_folder is not None`, written to
`diagnostics.json`, and never asserted anywhere.

Four consequences follow.

A regression of up to three percentage points passes. Content staleness at equal
brightness is entirely invisible, because counting lit pixels cannot see that the
lit pixels are the wrong ones — and "the same amount of picture, but showing an
older generation" is precisely the defect class a governed run exists to prevent.
The assertion is one-sided, so a warm view *brighter* than a fresh one always
passes, which means withdrawal and rollback staleness — the warm client still
showing ground a commit took away — cannot fail this gate at all. And the
headline claim that missing, changed and mean-absolute-error were "exactly zero at
every band" describes a manual run with a debug folder configured; a CI run
computes none of it.

The remedy is to assert the three numbers that are already being computed, and to
compute them unconditionally rather than only when a debug folder is set. Keep
writing the rich diagnostics under the debug folder; move the oracle out of it.
This is the highest value-per-line change in the review: it converts the
campaign's best evidence into the guard the next campaign will need.

One related point on the same gate, in the other direction. I expected the
warm-versus-reload comparison to be invalidated by the storm's panning, since a
reloaded page starts at the default camera while the stormed page has been
dragged around. It is not. `zoom_to` at `:747-770` recentres to the midpoint of
the coordinate space on every call, and `opening_zoom` is captured once and reused
after the reload, so both sets of bands are photographed from the same camera at
the same absolute zoom. The pixel-equality claim is methodologically sound, and
the comment at `:748-751` shows this trap was already found and closed once.

### C3 — Removing the deadline traded bounded abandonment for unbounded stalling. High. Confirmed from code, consequence inferred.

This is the prompt's worker question 2, and the answer is that yes, one hung key
can starve every later invalidation for that source, indefinitely.

`patch_neuroglancer.mjs:167` awaits `Promise.allSettled(jobs)` inside
`while (source.zmartPendingRefresh.size !== 0)`. The batch is a barrier: no key in
the next batch moves until every key in this one settles. A request that never
settles therefore holds the pump forever. `zmartRefreshRunning` stays true, so the
RPC handler at `:177-182` keeps adding keys to `zmartPendingRefresh` that will
never be delivered, and the probe would report a pump running with pending keys
and no failures — healthy-looking, permanently stuck.

The removed two-second timer was not the right answer; the campaign proved that
convincingly, and the evidence around abandoned composition is the most valuable
single measurement in the whole record. But the replacement has no liveness bound
at all. `fetch` has no default timeout. Neuroglancer's bounded retry covers 429,
503 and 504 — status codes, which presuppose a response. It does not cover a
socket that stalls, a server thread wedged behind the bake lock, or a response
whose body never finishes arriving. The new failure is rarer than the one that was
fixed and worse when it happens, because the old one recovered on the next batch
and this one does not recover at all.

The prompt's own proposal 3 is the right fix, and it is worth stating why it beats
both alternatives. Per-key sequencing — one in-flight request per chunk key, with
latest-wins intent — keeps the property that made single-flight work (the same
mutable chunk is never downloaded twice at once) while removing the property that
causes this (unrelated keys waiting on each other). No deadline is reintroduced, so
useful slow composition is still never abandoned; a stuck key stalls only itself.
The cost is per-key bookkeeping instead of a per-source flag, which is a modest
amount of code and strictly less coupling.

### C4 — The refresh downloads into a chunk the queue manager still believes is resident and idle. Medium-high. Mechanism inferred, dead code confirmed.

`patch_neuroglancer.mjs:136-153` deliberately leaves the chunk in `GPU_MEMORY` or
`SYSTEM_MEMORY` — that is what lets the stale pixels keep drawing — and calls
`source.download(chunk, abort.signal)` outside the state machine. The comment at
`:100-113` describes this as working "beside the state machine", which is exactly
right and is also the risk: from the queue manager's point of view that chunk is
resident and nothing is happening to it, so it remains eligible for eviction,
freeing or recycling while the download is writing into it.

Two things are certain from the code. The `AbortController` created at `:139` is
never aborted — no call to `abort.abort()` exists anywhere in the file, so it is
dead code today. And nothing in the pump observes eviction or disposal: the
success continuation at `:141-148` runs `chunk.serialize(msg, transfers)` and
invokes `Chunk.update` unconditionally, whatever became of the chunk while the
request was in flight.

What is inferred is whether Neuroglancer will actually evict such a chunk mid-flight.
I could not read the installed library to check. If it will, this is the same bug
class the single-flight change fixed — two writers into one mutable chunk — with
eviction playing the part of the second refresh, and it would be capable of
producing precisely the family of symptoms the campaign chased.

The memory-budget experiment does not settle this. Raising the budgets makes
eviction *less* likely; observing that the persistent 47% symptom did not move
tells us that symptom was not eviction. It does not tell us eviction is safe.

Two actions follow. Immediately, either delete the unused controller or wire it to
disposal so that an evicted or disposed chunk aborts its in-flight refresh — the
hook is already there and costs nothing to connect. Then, on the T400, read the
pinned `chunk_manager/backend.js` eviction path and settle the question. If a
`GPU_MEMORY` chunk can be freed while `download` is writing into it, this is a
correctness bug rather than a hygiene note, and it should be fixed before the
branch is called finished.

### C5 — Object preservation frees GPU memory outside the accounting, and copies a foreign object wholesale. Medium. Confirmed from code, consequences partly inferred.

`patch_neuroglancer.mjs:236-239` frees the old texture and then merges a freshly
constructed chunk into the held one:

```js
if (chunk.state === ChunkState.GPU_MEMORY) chunk.freeGPUMemory(this.gl);
Object.assign(chunk, source.getChunk(update));
```

The prompt asks (frontend question 1) whether this is a sound contract or the
least-bad patch for a pinned version. It is the second, for three reasons.

`Object.assign` copies own enumerable properties only. Anything held on the
prototype, anything non-enumerable, and any accessor semantics are not carried
across; and — the part that is easy to miss — any field present on the held chunk
but absent from the fresh one *survives*. The result is not the new chunk. It is a
merge of two generations, and which fields come from which generation depends on
details of a class this repository does not own.

The temporary from `source.getChunk(update)` is constructed, harvested and dropped.
If `getChunk` registers the object, counts it in statistics, or draws it from a
recycle pool, that bookkeeping is now wrong by one object per refresh. I could not
check which of those it does.

And `freeGPUMemory` is called directly rather than through the normal state
transition, so whatever the frontend uses to account for GPU bytes may not learn
that those bytes came back.

That last point matters most for the thing the evidence does not cover. The
acceptance run is roughly ninety seconds of storm. Accounting drift is a slow leak;
a real acquisition runs for hours with the viewer open. Nothing in this campaign
measures a long run, so the question "does this hold up over an afternoon" is
currently unanswered rather than answered well.

The prompt's frontend question 4 asks whether identity can be preserved without
copying a foreign object. It can, and it should be. Give the chunk class an
explicit `installPayload(update)` method that assigns the specific fields an update
actually carries — data, state, sizes — and goes through the ordinary state
transition so the accounting is told. That is a small named contract instead of a
structural graft, it says out loud which fields are part of the deal, and it has a
fighting chance of surviving an upstream version bump. It is also far easier to
review than `Object.assign` against a class nobody in this repository maintains.

On the prompt's frontend question 2 — why stock replacement left the full storm at
72.2% when the small no-blink test passed — I can offer the mechanism but not
confirm it. Replacement frees the texture the render pass still points at, so a
render-side reference survives pointing at freed GPU memory. A short test with few
chunks and little navigation rarely holds a stale reference across the swap; a
long storm with continuous wheel and drag input holds many. That is consistent
with everything recorded, and it is consistent with the small red test the
handover describes at the point where the source map claimed five of five visible
chunks while a render pass pointed at an object whose texture had been freed. I
would call it well-supported, not proven, until someone instruments retained
references directly.

### C6 — The Windows sharing retry is bounded per operation, not per derive. Medium. Confirmed from code.

`_after_a_windows_reader` at `governed.py:159-170` retries for five seconds per
call. `_keep_the_bake_true` calls it once per dirty piece per plane through
`_replace_one_piece` at `:681-687`, and again per piece in `_rehalve_one_level`.
The whole loop runs inside `_derive_guard` and the cross-process bake lock, which
is where every page request for that picture is waiting.

The retry predicate at `:165-166` accepts `errno` 5 and 13. Thirteen is `EACCES`,
which is what a genuine permissions problem raises — a read-only disk, an ACL
change, an antivirus tool holding a file. In that case every dirty piece costs its
own five seconds, serialized in front of serving. Fifty dirty pieces is four
minutes of a blocked picture for a fault that will never clear.

The bound should belong to the patch pass, not to each file within it: take one
deadline before the loop and let every replacement share it. A pass that cannot
finish inside its budget should fail once, promptly, rather than fifty times
slowly.

### C7 — The full-survey recovery path is not as rare as its docstring claims. Medium. Confirmed from code.

`_the_ground_the_bake_missed` builds `everything` at `governed.py:719-722` — every
row and column of every level — before deciding whether it needs it. At survey
scale that is a large allocation and sweep on a path taken whenever
`stamped != self._stamp_installed` at `:675`.

The docstring at `:711-715` describes reading the events file as "the one
deliberate second reader, bounded to the first derive of a session and to
recoveries". That bound holds for one process. `_stamp_installed` is per-instance,
so with two writers on one store — a second server, or `declare --bake` running
beside a running one, which is exactly the configuration `_holding_the_bake_lock`
was built to support — each process sees the other's stamp on every commit, takes
the recovery path every time, re-reads the whole events file at twenty commits a
second, and materialises the full-survey dirty set each time.

So the cheap path and the expensive path are chosen by a per-process variable
while the lock protecting them is cross-process. Two mechanisms, two scopes. The
fix is to make the comparison anchor something both processes can see — the
stamp's own identity is already exactly that — rather than a private memory of
what this instance last wrote.

### C8 — The rate scheduler repays a stall as a burst. Low-medium. Confirmed from code.

This is the prompt's question 5 about `show_a_run_growing.py`, and the answer is
that yes, it does create a catch-up burst.

`show_a_run_growing.py:341-343` computes an absolute deadline,
`next_due = schedule_started + (number + 1) / asked.rate`, and sleeps until it
with no clamp. After any stall — a slow publish, a garbage-collection pause, an
announcement that blocks — the accumulated deficit is repaid at full speed:
commits fire back to back until the schedule is caught. The same pattern is in the
gate at `test_a_commit_storm_under_zooming.py:818-822`.

What makes this worth fixing is the statistic reported next to it.
`:346-350` computes `(len(landed_at) - 1) / elapsed` — an average over the whole
run, which is precisely the statistic that cannot reveal a burst. "Sustained 19.95
commits per second" is equally consistent with a steady twenty per second and with
a run containing stretches at forty. Since burst behaviour is what the storm defect
is sensitive to, the harness is currently unable to tell us whether the thing it
measured is the thing it intended to measure.

Two small changes fix it: clamp the deficit to one interval so a late iteration
cannot compound, and report the maximum instantaneous rate and the worst gap
alongside the mean.

### C9 — The clean-install blocker, with its mechanism. Low. Confirmed from code.

`viz_studio/frontend/package.json:8` runs the patcher at `postinstall`, while
`build` runs `precompile-workers.mjs` *first* and the patcher second.

The patcher's worker entries carry `also: workerBundle` pointing at
`lib/chunk_worker.bundle.js` (`patch_neuroglancer.mjs:45`, applied in the loop at
`:250`). On a fresh install that file is still the un-flattened stub, so it
contains neither the marker nor the anchor; the anchor branch at `:268` sets
`failed = true` and the script exits nonzero at `:285`. The documented
`npm ci && npm run build` therefore stops at the first command, which is precisely
what the handover reports.

The narrow fix keeps the loud failure intact: give the patcher a `--modules-only`
flag and use it for `postinstall`. The file's own header comment at `:24-32`
already explains why that is sufficient — on a fresh install the postinstall
patches the modules, and the first precompile carries them into the bundle. The
full pass stays in `build`, where the bundle exists. Do not relax the anchor check
to make the error go away; that check is what catches a Neuroglancer version bump.

### C10 — The legacy migration leaves the superseded comment behind. Low. Confirmed from code.

`legacyStart` at `patch_neuroglancer.mjs:92` is the function line,
`"async function zmartPumpRefreshes(source) {"`, so the excision begins at the
function and leaves the old explanatory comment block standing above it. The new
addition then contributes its own comment. A maintainer reading the patched module
finds two descriptions in a row, the first of which documents the two-second
deadline that was just removed. In the compiled bundle this is invisible because
esbuild strips comments — which is also exactly why moving the marker to a code
identifier was the right call, and that part is well done.

A second, smaller asymmetry: the legacy branch at `:263` never checks the anchor.
On a future Neuroglancer version, a tree carrying the legacy block would be
migrated silently where a fresh install would fail loudly. Extending `legacyStart`
to include the comment's first line, and checking the anchor on both branches,
closes both points.

I also checked the case that worried me most about this migration — `legacyEnd` is
`"  void zmartPumpRefreshes(source);\n});"`, and that call appears twice in the
legacy code, once inside the `finally` block and once in the RPC handler. The
`finally` occurrence is followed by `\n    }` rather than `\n});`, so `indexOf`
correctly skips it and the excision ends where it should. The indentation is doing
load-bearing work here, which is worth knowing if anyone ever reformats the
addition.

---

## 3. What the tests prove, what they do not, and one flaky oracle

**They prove.** That derive, patch, stamp and install cannot interleave; that an
older derive cannot regress the bake behind a newer one; that a bake catches up
after demand stops without a client asking; that background catch-up waits for the
announcement storm to quiet; that a transient Windows sharing violation is
survived; that dirty pieces reach the level they name even when several sources
hold that level; that the small no-blink guard passes in three variants; and that
after a 20/s storm the warm view is not more than three percentage points darker
than a reload at four zoom bands.

**They do not prove.** Pixel identity between warm and reloaded views — computed,
never asserted (C2). Anything about withdrawal or rollback staleness, since the
assertion is one-sided. Anything about runs longer than about ninety seconds, which
is the gap that matters most for a real acquisition and for C5. Anything about
several viewers on one picture. Anything about two processes on one store, which
is the configuration C7 degrades. Anything about transient faults, since no test
induces a derive failure and then checks that the client recovers — the hole C1
describes is untested in both directions. And nothing about pump liveness when a
request never settles (C3).

**One flaky oracle.** `test_a_commit_storm_under_zooming.py:862` asserts
`19.5 <= achieved <= 20.5`. That fails the test when the *machine* cannot hold the
rate, which is a red that says nothing whatever about the defect under test. On
anything slower than the 24-core T400 this gate will fail for reasons unrelated to
correctness, and a gate that fails for irrelevant reasons is a gate people learn to
ignore. It should skip, or record the achieved rate as context on a failure of the
real assertion, rather than fail in its own right.

**On the diagnostic machinery.** The gate is 1,348 lines and carries two
environment-gated investigation blocks — `ZMART_STORM_HEAL` at `:896` and
`ZMART_STORM_DEBUG` at `:1004` — that print swap ledgers, believed bounds, chunk
data means and memory ledgers. That work earned its keep during the campaign and
should be kept, but not here. The reusable parts (per-frame or per-band pixel
measurement, the worker probe, the network census) belong in a small shared helper
module; the investigation blocks belong in a `stress/` harness that a person runs
deliberately. What should remain in the regression file is the scenario and the
oracle.

---

## 4. Architecture diagnosis

**The deepest problem is that freshness is a hope rather than a value.** An
announcement names keys. An HTTP response carries bytes. A worker install carries
a payload. Not one of them carries a generation. Because of that, no layer in the
system can answer the question "is what I am holding current?" — it can only
answer the much weaker "was I told to refetch this, and did that refetch happen to
succeed?"

Every defect in this campaign is a consequence of that gap. Work is abandoned
because nothing can say the answer is still wanted. Batches are superseded because
nothing can say which batch was later. Absent keys are dropped because nothing can
say whether their absence is current. Stale GPU objects survive because nothing
can say the object is a generation behind. And a 404 becomes a permanent hole
(C1) because nothing can say the emptiness was provisional. The campaign fixed
each of these individually, and each fix was correct, but they are five symptoms
of one missing field.

**The second problem is that a chunk has two owners and no protocol between
them.** The queue manager owns eviction, memory accounting and state transitions.
The ZMART pump owns refresh, and does its work "beside the state machine" by
design, because that is what lets stale pixels keep drawing. Neither tells the
other anything. C4 is what that costs, and the unused `AbortController` is the
place where the missing protocol was meant to go.

**The third problem is that status is one bit at the wire.** Sparse ground never
imaged, ground not yet published, a bake that is lagging, damaged committed
ground, a server briefly overloaded and a genuinely broken picture are all a
zero-length 404. The client cannot behave differently towards them because it
cannot tell them apart, and neither can the operator reading a log.

---

## 5. Three refactoring horizons

### Immediate hardening, safe before merge

Assert the pixel-identity metrics that are already computed, unconditionally
(C2). Answer 503 rather than 404 for "cannot answer right now" (C1). Give the
Windows retry one deadline for the whole patch pass instead of one per file (C6).
Add `--modules-only` to the patcher and use it from `postinstall` (C9). Clamp the
rate scheduler's deficit and report the maximum instantaneous rate beside the mean
(C8). Make the rate assertion skip rather than fail. Either delete the unused
`AbortController` or wire it to disposal (C4). Extend `legacyStart` over the stale
comment and check the anchor on both branches (C10).

None of these changes behaviour the acceptance run depends on, and together they
close the two holes that are cheapest to close.

### A medium professionalization pass

Replace the per-source batch barrier with per-key sequencing — one in-flight
request per key, latest-wins intent, explicit disposal and cancellation (C3).
Replace `Object.assign` with an explicit `installPayload` method that names the
fields it carries and goes through the ordinary state transition (C5). Replace the
ad-hoc probe fields with a small bounded set of structured counters that a support
person can read without knowing the campaign's history: manifest revision, bake
revision and lag, dirty-queue depth, in-flight count per key, response age, install
age, and time from landing to visible. Move the diagnostic machinery out of the
regression file into a stress harness. Split the gate into a fast deterministic
model test for ordering and ownership, and a slow opt-in soak test for the visual
promise. Split the bake patcher out of `governed.py`, which currently holds frame
geometry, snapshot derivation, bake patching and thread orchestration in one
999-line module.

### An ambitious redesign

Carry a generation end to end. The manifest revision travels through the
announcement, into an HTTP response header on every chunk, into the worker's
install, and into a frontend acknowledgement. "Refresh confirmed" stops being a
hope and becomes a comparison. Superseded generations coalesce by number rather
than by set membership. A client can ask whether it is current and repair itself
without a reload — which is the operator's actual cure today, and the thing this
campaign has been trying to make unnecessary. The storm gate's oracle then becomes
a cheap invariant check rather than a screenshot difference.

The cost is one header per chunk response, one field on the chunk, and one
comparison in the render path. The migration is additive and safely staged: send
the header and ignore it; then record it and expose it in the probe; then start
enforcing it. Rollback at any stage is to stop enforcing.

---

## 6. Efficiency model

**At 20 commits per second, one client.** Measured, and it holds. The derive is
O(change) rather than O(survey), which was hard-won and is the reason this works
at all.

**At 40 per second.** The unmeasured risk is the coalescing quiet window.
`_BAKE_CATCH_UP_QUIET_S` is 0.25 seconds (`governed.py:69`), so a continuous storm
at any rate above four commits per second never quiets, the background worker never
runs, and the whole bake load rides on page requests. That is by design and it is
the right design — but it means the bake's throughput at 40/s is entirely a
question of how fast `_keep_the_bake_true` can patch under one lock, and nobody has
measured that. This must be benchmarked rather than reasoned about.

**Several clients.** Derives are shared, which is the expensive part, so this
should scale better than intuition suggests. Each client has its own worker and its
own pump, so the pump does not become a shared bottleneck. The real unknown is GPU
and system memory per client, and it interacts with C5.

**Two processes on one store.** C7's cliff: full events read and full-survey dirty
computation per commit.

**What should be benchmarked rather than guessed.** Derive time against survey size
at 40/s. Bake patch time per dirty piece, separated into compose and write. How
many coarse pieces one commit dirties late in a storm — a coarse piece covers
roughly a hundred positions, so consecutive commits late in a survey should be
dirtying the same coarse pieces over and over, which is a coalescing opportunity
nobody appears to have measured. Time from landing to visible, as a distribution
rather than a mean.

---

## 7. Codebase hygiene, ordered by risk reduced per unit effort

1. The oracle problem (C2) — highest value in the review, smallest change.
2. Status semantics at the wire (C1) — small change, closes a real hole, and is
   the first step of the architectural fix.
3. The storm gate's size and its two investigation blocks — extract helpers, move
   the campaign scaffolding to a stress harness.
4. `server.py` at 1,866 lines and `governed.py` at 999 — split the bake patcher
   out first, since it is the most self-contained and the most likely to change.
5. Magic constants with no home: `_BAKE_CATCH_UP_QUIET_S`, the five-second Windows
   bound, `_REFUSED_FOR_SECONDS`, the ten-second Windows lock wait, the brightness
   threshold of 40, the 0.03 tolerance. None is configurable and none is logged
   when it fires, so when one of them is wrong the symptom will be silent.
6. Comments that record incidents rather than invariants. "Review finding D1",
   "that cost a night", "measured at 6,400 positions" — this is genuinely valuable
   history and the writing is unusually good, but it belongs in the `building/`
   notes, with the code left carrying the invariant. A reader currently has to
   reconstruct several campaigns to understand a function.
7. The superseded verdict section in the handover. The document opens by saying
   the resolution supersedes it, which is honest and right, but the older section
   still reads "do not call the branch shippable" in its own voice. Anyone landing
   in the middle of the file will read the wrong conclusion. Mark the superseded
   sections inline.

---

## 8. One unconventional idea, with its honest costs

**Make the bake generation part of the address, and staleness stops being
possible.**

Instead of patching baked files in place and keeping a stamp that says what they
absorbed, publish each bake generation as its own immutable directory —
`baked/000001/`, `baked/000002/` — with a tiny `current` pointer file flipped
atomically when a generation is complete. Unchanged pieces are hard-linked from the
previous generation, so the disk cost is the change rather than the survey, which
is the same economy the derive already achieved for composition.

What this buys is structural rather than incremental.

Serving never has to infer whether the files and the stamp agree, because a
generation directory is either complete and pointed at, or it is not — which is the
prompt's architectural point 5 in its strongest available form. A chunk's URL can
include its generation, which makes every chunk immutable and therefore
indefinitely cacheable; the whole ETag, `no-store` and refresh-race problem class
disappears, because a stale chunk is simply a chunk from an older URL and the
browser is free to keep it forever. Refresh becomes "fetch these keys at the new
generation", and an abandoned request costs nothing at all, because its answer was
never needed by anything — which dissolves the abandoned-work problem that this
campaign spent its hardest hours on, rather than bounding it. And a client can
compare the generation it is drawing with the generation the pointer names, so
"am I stale?" becomes a question it can answer about itself.

The honest costs. It is a larger change than anything the campaign attempted, and
it moves cost from correctness reasoning into disk and garbage collection: old
generations need a collector, and a collector needs to know which generations
clients may still be drawing. Hard-link behaviour differs across filesystems and
this must run on Windows, where the link count and the reader-sharing rules are
exactly the area that has already produced one bug in this campaign. Inode
consumption at survey scale needs measuring before anyone commits to it.

It is falsifiable, and cheaply. Prototype the pointer flip and the hard-linked
generation on an existing store, measure the link cost per commit at 6,400
positions, confirm that a 20/s storm does not exhaust the inode budget, and check
that a reader holding an old generation open does not prevent collection on
Windows. If those four numbers come back well, the design is worth the migration;
if any comes back badly, it dies for a concrete reason rather than a preference.
Rollback is a single atomic write of the pointer file.

I would not propose this to replace a working fix. I propose it because every
measurement in this campaign has been an attempt to prove the *absence* of
staleness, and absence is the hardest thing in the world to prove. This design
makes staleness structurally impossible to express, which is a different and much
cheaper kind of confidence.

---

## 9. A phased validation and migration plan

**Phase 0 — close the oracle gap.** Assert the pixel metrics (C2) and confirm the
gate still passes on the final candidate. Acceptance: missing fraction, changed
fraction and mean absolute error are all zero at every band, enforced by CI rather
than by a debug folder. Rollback: none needed; this only adds assertions.

**Phase 1 — the cheap correctness fixes.** C1, C6, C8, C9, C10, and the dead
`AbortController`. Acceptance: a new focused test induces a derive failure and
confirms the client recovers rather than caching a hole; `npm ci && npm run build`
succeeds from a clean checkout; the focused guards stay green. Rollback: each is
independently revertable.

**Phase 2 — settle C4.** Read the pinned Neuroglancer eviction path on the T400
and answer whether a `GPU_MEMORY` chunk can be freed while `download` writes into
it. If yes, fix it before anything else in this phase and add a test that evicts
under refresh. Acceptance: a stated answer with a file reference, not a hypothesis.

**Phase 3 — the professionalization pass.** Per-key sequencing (C3) and
`installPayload` (C5), one at a time, each with its own A/B against the 20/s gate
so that a regression names its own cause. Acceptance: warm/reload pixel equality
holds, and a new liveness test — one key's response held open indefinitely — shows
unrelated keys still converging. That test is the direct guard for C3 and does not
exist today.

**Phase 4 — the long run.** Before any of this is trusted on a real acquisition,
run one soak: a survey at a realistic rate with the viewer open for hours, sampling
warm-versus-reload equality and the frontend's memory accounting periodically.
Acceptance: no drift in either. This is the single largest gap in the current
evidence and no amount of ninety-second runs closes it.

**Phase 5 — generations.** Only if phases 0 through 4 are green, and staged
additively as described in section 5.

---

## 10. Questions that cannot be answered from the repository or the evidence

1. Can Neuroglancer's queue manager evict, free or recycle a worker-side chunk in
   `GPU_MEMORY` while `source.download` is writing into it? This decides whether
   C4 is a hygiene note or a correctness bug, and it is a short read of the
   installed library on the T400.
2. Does the HTTP kvstore remember a 404 for the session, or will it re-request on
   a later visible-chunk pass? This decides whether C1 leaves a permanent hole or a
   self-healing one.
3. Does `source.getChunk(update)` on the frontend have side effects —
   registration, statistics, a draw from a recycle pool? This decides the severity
   of C5's second point.
4. What is the longest acquisition ZMART must support with a viewer left open, and
   has that ever actually been run? Phase 4 cannot be scoped without this.
5. Is `declare --bake` beside a running server a supported configuration or
   defensive coding? This decides whether C7 is urgent or theoretical.
6. What did the server's own logs show during the abandoned-work episode? The
   client-side evidence that composition continued after the client gave up is
   strong and consistent, but it is inference from timing; the server knows the
   answer directly.
7. Was the final full suite run against the same build as the final acceptance
   run, or a rebuild? The handover records both but does not tie them to one
   artefact, and the campaign's own history includes a night lost to measuring a
   build that did not contain the change.

---

## A closing note on the work itself

Reviewing this branch adversarially was harder than it usually is, because most of
the obvious objections had already been raised and answered somewhere in the
record. The decision to remove the retry policy on evidence rather than keep it on
plausibility, the refusal to accept the small green gate once the operator-scale
run disagreed with it, and the explicit note that the memory-pressure hypothesis
was tested and ruled out rather than quietly dropped are all examples of the
campaign being harder on itself than a reviewer would have been.

The findings above are mostly about the difference between knowing something and
being able to keep knowing it. The fix is good; the guard that would defend it is
weaker than the evidence that produced it. Closing that gap is a smaller job than
the campaign that produced the fix, and it is what would let the next person change
this code without repeating the whole investigation.
