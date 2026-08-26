# The watch-list: what the axes chapter must stay paranoid about

> Written 2026-08-17 as the index of standing dangers for the depth and
> (t, c) work — each with its scar or its arithmetic. Everything here is
> also written where it binds (the plans, the test plans, CLAUDE.md); this
> page is the one place to re-read before trusting any green. When a
> review or a measurement names a new danger, it is added here the same
> day.

## Physics-shaped (can sink the design)

1. **The held volume view versus whole-source refresh.** Both reviews'
   top finding: the refetch bill is O(depth) per landing and cannot
   converge under sustained landings at today's shapes. Nothing about
   "3D is smooth" is assumed until the refetch counter's table exists
   and a mitigation is gated.
2. **Declared room must be free.** Three shipped loops walk declared
   depth, not imaged depth; a generous ceiling turns them into an
   O(declared) tax per landing. Guard: the parity rung — declared =
   imaged versus declared ≫ imaged, numbers must match.
3. **RAM in absolute bytes, never shares.** Pins, caches, and the
   browser, sized against the machine actually present and asserted by
   instrument. The workstation's 31 GB is not the operator's laptop.
4. **The synchronous bake inside landing-to-visible.** Depth multiplies
   it; a replacement on a long timelapse multiplies it again.
   Time-to-first-answered-piece during the patch decides shrink-it
   versus move-the-bound.

## Correctness traps (pass every naive test)

5. **Geometry seams.** Ceiling-versus-floor already disagrees across
   three call sites; ragged depths and the shifted-slab-key sabotage
   make an off-by-one-plane visible before an operator meets it.
6. **Symmetric faults.** Anything wrong the same way warm and fresh —
   the contrast window sampled from empty declared room is the known
   one — is invisible to every F5 comparison. Only ground-truth gates
   catch these.
7. **Navigation masking.** Moving repairs staleness, so the station walk
   compares warm against F5 at every stop; the z/t-step-refresh bench
   observation is measured, not assumed — both as masking hazard and as
   a possible refetch-the-world cost bug.
8. **The wire words.** One wrong word cost an evening. The wire stays
   one word, sabotage-tested; no z or t vocabulary joins it.

## Process (how we fool ourselves)

9. **Instruments red for the right reason, screenshots looked at.** A
   metric can be satisfied by the wrong picture; an inspected
   screenshot cannot. Both are standing rules now.
10. **Preserve the failing run's evidence.** Debug folders on the FIRST
    attempt of anything expected to be unreliable — the workstation's
    named-mode lesson: the failure you did not capture is the one you
    chase for a week.
11. **Test economics.** A slow suite stops being run and then guards
    nothing: gates under ninety seconds, the big linked fixture opt-in,
    correctness small and cost on the ladder, never both at once.
12. **Container-versus-bench honesty.** Software rendering proves
    correctness and ratios, never feel; and verify which graphics stack
    actually drew (the ZMART_REAL_GPU lesson) before trusting any GPU
    claim.

## The (t, c) chapter's own

13. **Nothing per-landing scales with timelapse length.** The one
    permitted O(moments) event is the replacement spike, already pinned
    at the record layer.
14. **The both-channels common case.** Channels are viewed together; if
    each landing pays twice (two derives, two bakes, two refetches),
    the storm bar moves — measured, never discovered.

## Data-shape facts the viewer may never assume

15. **Chunk and shard geometry is the data's fact** — read from each
    store's metadata, never hard-coded; gates run at least two
    packings. (Measured 2026-08-17: the slab economy exists in Thy1's
    packing and not in ours.)
16. **Pyramid shape is the data's fact** — x/y-only or x/y/z, per
    acquisition, pinned in the profile; gates run both shapes.
17. **No pyramid ever crosses c or t.** Spatial economy only; every
    (t, c) pair carries its own pyramid.
18. **A refused run must not be a silently empty page.** A run whose
    binding fails — a failed bake, a damaged manifest — is withheld with
    the reason in the registry's errors and the server log, and nothing
    carries it to the operator's screen: they see an empty viewer and no
    explanation. (The time and channel refusals themselves retired
    2026-08-18 — a grown run binds and serves — which narrows this gap
    without closing it.) When any refusal is expected in front of an
    operator, the reason must reach the page; until then this is a known
    gap, not an accepted design.
19. **The axes are proven together.** One combined-axes identity oracle
    (value = 1000·t + 100·c + z) in the default suite; independent-axis
    gates alone close neither chapter.
20. **The named ladder is deleted (2026-08-18).** Its gates kept failing
    (T400 intermittent staleness, then its own delivery gate timing out
    in-container), and the whole-source path passed everything twice
    over. One invalidation remains; see
    docs/open/PLAN_close_the_neuroglancer_chapter.md for the record.
21. **The pointed door's frame rate slid while its gate was dark.** The
    drawing-keeps-up ratio (200 pointed stores against 20) was calibrated
    at 35–40% in the sandbox and measured 22% when the gate was revived
    on 2026-08-17 — it had been uncollectable since a rename, and the
    slide happened unseen during the conversion chapter. The line is
    re-drawn beneath today's number so a further slide is caught; the
    bench decides whether 22% matters on real graphics, and the bisect
    walks the conversion history if it does. The general lesson stands
    beside the specific one: a gate that stops collecting is a gate that
    reports green, so revived suites deserve a collection check.
