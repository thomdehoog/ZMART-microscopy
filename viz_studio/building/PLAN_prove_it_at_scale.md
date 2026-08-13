# Prove it at scale: the claims, the ladder, and the weak point named first

> Written 2026-08-13 at the start of the "prove it" phase, designed around
> claims to falsify rather than demonstrations to admire. The companion
> harness is `measure_a_governed_run_at_scale.py`; the campaign's scenario
> is the operator's own: a survey mostly imaged, growing at its boundary
> while governance replaces positions inside — the shape a real
> smart-microscopy run has.

## The four claims "it scales" actually makes

1. **A landing costs its footprint, not the survey.** Landing-to-visible
   latency and refresh group size must stay flat from a hundred positions
   to 12,800, with the frame recorder holding **zero transients at every
   rung** — the non-negotiable gate.

2. **Serving stays responsive** — piece cost and screenful time flat.
   Proven to 115,200 positions for transfers; unproven for governed runs,
   where every block read passes the presence check and every request
   consults the manifest's fingerprint.

3. **Commit-time work is bounded.** The known weak point, named before the
   first measurement because it is already legible in the code:
   `GovernedRun._compose_the_snapshot` re-reads **every committed tile's
   description on every commit** — at ~0.3 ms a tile that is ~30 ms at a
   hundred positions (invisible), ~0.5 s at 1,600 (felt), ~4 s at 12,800
   (broken). The fix is well-scoped and honest to the design: the snapshot
   already knows exactly which positions changed, and a tile is immutable
   per generation — so the fresh snapshot reuses the previous one's Tile
   objects for everything unchanged and reads only the changed stores.
   Commit cost goes from O(survey) to O(change), the same principle the
   cache inheritance already follows. Measured failing first, then fixed,
   then re-measured — never fixed on faith.

4. **Nothing leaks over a long churn** — browser heap and server memory
   flat over hundreds of landings and replacements.

## The campaign, in order

- **Step 0 — instrument first** (the flicker hunt's law). The harness
  reports, per rung: snapshot derivation time and tiles-re-read (read
  in-process from `GovernedRun.accounting` — the harness runs the server
  in its own thread, so there is no telemetry plumbing to invent),
  landing-to-visible latency from the page's own frame timestamps, the
  recorder's transient count, and the writer's own per-publish cost.

- **The centrepiece rung, ~1,000 positions** (operator's scenario): a
  32×32 survey with its interior pre-published in bulk before the viewer
  opens — which also measures the cold open at weight — then the watched
  churn: boundary landings (planned-but-dark positions lighting up, which
  exercises the fixed world frame) interleaved with interior replacements
  (governance swapping published ground). Striped replacement pixels, so
  whose ground changed is readable by eye as well as by recorder.

- **Rung 1,600 and the fix.** Claim 3's linear term should be plainly
  visible; measure it, build the incremental snapshot, re-measure, and
  only then climb.

- **Rungs 6,400 → 12,800 — plus the cold story.** Governed pictures get
  no bake and no warmer today, so the first zoom-out at 12,800 collects
  the old deferred opening bill. Measure it, then decide whether the
  warmer turns on for governed snapshots — inheritance keeps warmth
  across commits, so it would be paid once per session, not per commit.

- **Fixture economics.** Writing 12,800 governed positions is twenty-odd
  minutes of real writer work — done once into `D:\zmart-scale-runs\`,
  reused across every measurement; only `publish()` drives the churn.

## What stays excluded, and why it is still reported

The writer's own ~500–900 ms per `publish()` is not the viewer's cost and
does not count against these claims — but the harness prints it beside
every change, so whenever a ceiling appears, it is attributable to its
owner rather than argued about.

## What "removing" means here, honestly

The manifest is append-only: governance withdraws published ground by
**replacement** (and whole-history rollback by recovery), never by a
first-class unpublish event. The churn therefore replaces interior
positions rather than deleting them — which is also what a real run does.
