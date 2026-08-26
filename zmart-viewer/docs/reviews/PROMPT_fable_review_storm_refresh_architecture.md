# Prompt for Fable: review the storm fix and rethink the live-view architecture

Review the completed ZMART live-view storm campaign on the 24-core T400
workstation. Be adversarial about correctness first, then ambitious about how
the architecture and codebase could become faster, more professional, easier to
maintain, and cleaner. Creative or unconventional proposals are welcome, but
separate what the evidence proves from what you infer, and attach costs and a
migration path to every substantial redesign.

Do not begin by editing code. Read the implementation, tests, history, and saved
evidence; report findings and proposals. Do not delete or rewrite any fixture.
All `D:\zmart-*` data is evidence and read-only for this review. The deliberately
uncommitted launcher reload-menu change mentioned in older notes belongs to a
different clone and is outside this review.

## Repository and review range

- Clone:
  `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_ladder-codex-demo-20260814-0e2f597f`
- Branch: `codex/diagnose-storm-bake-catchup`
- Compare `f4056177..HEAD` and inspect the final working tree, which should be
  clean after the campaign commit.
- Read first:
  - `zmart-viewer/app/picture/PROMPT_fix_the_storm_bake_catchup.md`
  - `zmart-viewer/app/picture/HANDOVER_codex_storm_bake_and_client_staleness.md`
  - the last storm/catch-up sections of
    `zmart-viewer/app/picture/MEASURED_the_ladder_of_surveys.md`

The central files are:

- `zmart-viewer/app/picture/declare.py`
- `zmart-viewer/app/picture/governed.py`
- `zmart-viewer/app/picture/served.py`
- `zmart-viewer/app/server/server.py`
- `zmart-viewer/app/page/scripts/patch_neuroglancer.mjs`
- `zmart-viewer/app/page/src/engine.js`
- `zmart-viewer/tests/test_a_commit_storm_under_zooming.py`
- `zmart-viewer/tests/test_dirty_pieces_reach_their_level.py`
- `zmart-viewer/app/picture/show_a_run_growing.py`

## Ground truth the review must preserve

At 20 commits/s the old backend bake could advance its stamp past work it had
not repaired, then had no demand-independent driver after the storm stopped.
The fail-closed serving gate consequently blanked a cold client. The committed
backend fix serializes derive -> bake -> install, makes installation forward-only
by folded identity, coalesces announcement-driven catch-up after quiet, and
retries only Windows sharing-shaped atomic replacement failures.

A second, connected-client defect remained after the bake was fixed. The most
important measurements were:

- up to 124 simultaneous downloads of the same mutable worker chunk;
- a fixed 2,000 ms worker deadline repeatedly abandoned useful server work;
- adding an outer 250 ms-to-2 s retry policy increased the run to 3,017 aborted
  requests and 145 simultaneous requests;
- one coarse chunk was abandoned about every two seconds for roughly 100
  seconds, then F5 fetched its completed 398,661-byte form in 95 ms;
- raising browser memory budgets did not move the persistent failure;
- stock frontend object replacement passed the small no-blink tests but failed
  the full 20/s A/B at 72.2% warm coverage versus 100% after F5;
- the final object-preserving frontend plus single-flight/no-deadline worker
  reached exact warm/F5 pixel equality at every tested pyramid level.

The final automated run is preserved under:

`D:\zmart-codex-diagnosis-20260814\automated-20ps-final-proven-combination-20260815-20`

It sustained 19.95 commits/s over 1,456 live commits. Manifest and bake both
ended at 1,600. All six refresh pumps ended `pending=0`, `running=false`, with
zero refresh failures and zero same-key overlap. Warm versus same-view F5 was:

| Zoom | Warm | F5 |
| --- | ---: | ---: |
| 0.15x | 100.000% | 100.000% |
| 0.40x | 100.000% | 100.000% |
| 1.00x | 100.000% | 100.000% |
| 2.50x | 41.026% | 41.026% |

For every band, missing-pixel fraction, changed-pixel fraction, and mean
absolute pixel error were exactly zero. The operator then watched a separate
true outward spiral at measured 20.00 commits/s and reported: "Its very nice,
it does heal."

The one final full suite completed green:

`769 passed, 5 skipped, 3 xfailed, 2 warnings in 1494.90s (0:24:54)`

The two warnings are unrelated Pillow deprecations.

## Part one: correctness and regression review

Try to falsify the fix. For every finding, cite the exact file and line, explain
the failing sequence, rank severity and confidence, and state whether existing
evidence already covers it. Pay particular attention to these questions.

### Backend bake and publication

1. Does the derive lock truly cover the complete derive -> patch -> stamp ->
   install transaction without a lock-order deadlock against the catch-up
   thread, serving threads, file lock, manifest writer, or shutdown path?
2. Can a rollback, rewritten history, layout revision, or stale concurrent
   derive still make `baked.json` claim ground the files do not contain?
3. Can announcement coalescing lose the final state during shutdown, server
   startup, handler failure, or an announcement that arrives at the exact point
   the catch-up thread decides it is settled?
4. Are the 250 ms backend quiet period and five-second Windows sharing retry
   bounds justified, observable, and owned by the right layer?
5. Does fail-closed serving distinguish temporary "bake not ready" from real
   absent/sparse ground cleanly enough? Neuroglancer retries 429/503/504, but its
   HTTP kvstore treats 403, 404, and network status 0 as legitimate missing data.
   Determine whether any production path can still translate a temporary fault
   into a successful empty chunk.

### Worker refresh pump

1. Prove or disprove that one pump per source is enough to prevent concurrent
   mutation of the same chunk across the stock Neuroglancer downloader and the
   ZMART refresh path. The ZMART probe reports overlap only inside its own path.
2. The pump waits for all jobs in a batch before beginning the coalesced next
   batch, while delivering each successful chunk immediately. Can one hung key
   starve unrelated later invalidations indefinitely? Would per-key sequencing
   be safer and faster than per-source batch barriers?
3. What happens when `source.download` genuinely rejects after Neuroglancer's
   internal retry budget, decode fails, a source is disposed, navigation evicts
   a chunk, or a later announcement arrives during serialization/freeing?
4. Audit every state transition around `GPU_MEMORY`, `SYSTEM_MEMORY`,
   `SYSTEM_MEMORY_WORKER`, `DOWNLOADING`, and `QUEUED`. Look for detached buffers,
   double frees, stale state capture, failure to schedule a queue update, or a
   result delivered after ownership changed.
5. Is the absence behavior intentional and bounded? Most offered keys are
   absent because navigation changes what the source holds. The fix deliberately
   does not retain or revive them; verify that later normal demand cannot leave a
   stale frontend/GPU chunk disconnected from worker truth.
6. The remaining browser-level `ERR_ABORTED` events come from deliberate wheel
   and drag navigation. Verify they are normal cancellation rather than a hidden
   recurrence of the abandoned-work problem.

### Frontend object preservation

1. The final code frees old GPU memory and then uses
   `Object.assign(chunk, source.getChunk(update))` so render-side references keep
   their object identity. Audit this against Neuroglancer's class invariants,
   prototypes, disposers, reference counts, source ownership, statistics,
   texture lifecycle, and future upstream fields. Is copying enumerable fields
   a sound contract or merely the least-bad patch for this pinned version?
2. Explain why stock replacement left the full storm at 72.2% even though the
   small no-blink test passed. Confirm a causal retained-reference mechanism
   from code, not only correlation from the A/B.
3. Look for a one-frame black interval between `freeGPUMemory`, field assignment,
   `copyToGPU`, and `visibleChunksChanged`. The fixed-navigation and no-blink
   tests were green, but the roaming screenshots are not a valid oracle when the
   camera has panned off specimen.
4. Can the frontend preserve identity without copying a whole foreign object—for
   example, through an explicit payload-install method or immutable GPU resource
   swap? Recommend the safest contract.

### Patch/build mechanics and tests

1. Audit `patch_neuroglancer.mjs` on all three states: clean dependency install,
   an established tree with the legacy 2-second block, and a tree already on the
   final code. The marker must remain code, not a comment, because esbuild strips
   comments. Check that `legacyStart`/`legacyEnd` cannot replace the wrong block,
   duplicate RPC registration, or silently accept a partially patched bundle.
2. Decide whether patching generated upstream files is professionally acceptable.
   If not, propose a reproducible alternative: pinned fork, package patch tool,
   explicit adapter seam, upstream contribution, or build-time verified overlay.
3. Review the 40x40 test for false greens, false reds, timing assumptions,
   navigation-dependent screenshots, port/process leaks, teardown races, and
   excessive runtime. Its warm/F5 comparison must preserve identical navigation.
4. The test file gained substantial diagnostic machinery. Identify what belongs
   in reusable helpers, a dedicated stress harness, structured evidence objects,
   or an opt-in soak suite rather than one monolithic regression.
5. Check that the `--rate` scheduler in `show_a_run_growing.py` measures actual
   commit cadence without creating a catch-up burst when one iteration is late.

## Part two: architecture and refactoring review

Step back from this patch. Describe the architecture you would want if ZMART had
to support long real acquisitions, many viewers, higher rates, and engineers who
did not live through this campaign. Optimize for explicit ownership, bounded
work, observability, testability, efficiency, and maintainability—not merely for
the smallest diff.

At minimum, assess these possible directions and propose better ones if you see
them:

1. **Revision-aware acknowledgements.** Instead of invalidating a key and hoping
   a later body is current, carry a manifest/bake generation through announcement,
   HTTP response, worker install, and frontend acknowledgement. Define what
   "refresh confirmed" means and how superseded generations coalesce.
2. **Immutable download results.** Stop letting concurrent operations mutate a
   shared chunk during I/O. Download/decode into an immutable result or staging
   object, then atomically install it if its generation is still wanted.
3. **Per-key actors or sequence numbers.** Give each visible chunk a small state
   machine with at most one in-flight request and latest-wins intent, rather than
   a source-wide batch barrier. Include disposal, cancellation, retry, backoff,
   and fairness semantics.
4. **Backpressure across acquisition, bake, server, and clients.** Define where
   work may coalesce, what must never be dropped, how lag is measured, and how a
   system degrades when 20/s becomes 40/s or a compose takes seconds.
5. **Separate truth from acceleration.** Clarify the manifest as truth, the bake
   as a versioned derived cache, and serving as a reader of one published bake
   generation. Consider double-buffered bake generations, copy-on-write chunks,
   or a small transactional publication index so the gate never has to infer
   whether files and stamp agree.
6. **Status semantics.** Make sparse absent ground, unpublished ground, bake lag,
   damaged committed ground, transient server overload, and terminal errors
   distinct in types, logs, metrics, and HTTP responses.
7. **Observability as a product feature.** Replace ad-hoc probes with bounded,
   structured counters and traces: manifest revision, bake revision/lag, dirty
   queue depth, per-key in-flight count, coalesced generations, response age,
   install age, retry reason, and time-to-visible.
8. **Upstream integration boundary.** Minimize fragile knowledge of Neuroglancer
   internals. Identify the smallest stable interface ZMART needs and whether it
   should live in an upstreamable plugin/fork rather than text grafts.
9. **Test architecture.** Build deterministic model/state-machine tests for
   generation ordering and ownership, focused browser gates for visual promises,
   and separate rate/soak tests. Suggest how to make the 20/s regression faster
   without weakening its oracle.
10. **Codebase hygiene.** Identify large modules, duplicated state machines,
    ambiguous names, stale historical documentation, encoding damage, weak type
    contracts, magic time constants, hidden globals, teardown leaks, and places
    where comments describe incidents rather than durable invariants. Propose a
    realistic cleanup order that preserves behavior.

Look for a genuinely high-leverage design the campaign did not consider. A
"genius" proposal is welcome if it simplifies multiple failure classes at once,
but make it falsifiable: give the invariant, data flow, expected performance,
failure modes, prototype boundary, benchmark, and rollback strategy.

## Required output

Return a self-contained review with these sections:

1. Executive verdict: ship, ship with follow-ups, or block.
2. Correctness findings ordered by severity, each with file/line evidence and a
   concrete failing sequence.
3. What the current tests prove, what they do not prove, and any flaky oracle.
4. Architecture diagnosis: the deepest ownership and data-flow problems.
5. Three refactoring horizons:
   - immediate hardening that is safe before merge;
   - a medium-sized professionalization pass;
   - an ambitious redesign for the best long-term system.
6. Efficiency model with likely bottlenecks at 20/s, 40/s, and multiple clients;
   state what must be benchmarked rather than guessed.
7. Codebase-hygiene backlog, prioritized by risk reduction per unit effort.
8. One or more unconventional high-leverage ideas, with honest tradeoffs.
9. A phased validation and migration plan with acceptance metrics and rollback
   points.
10. Questions that cannot be answered from the repository or evidence alone.

Do not praise complexity merely because it is sophisticated, and do not demand a
rewrite merely because the present implementation is patched. Prefer the
simplest architecture that makes ownership, freshness, bounded work, and failure
semantics explicit.
