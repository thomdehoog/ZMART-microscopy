# Review of the revised plan, "Viewer delivery after the JPEG-pyramid review"

**Date:** 2026-09-01.
**What was reviewed:** `docs/design/lazy-jpeg-pyramids-for-the-viewer.md` at
commit `f1e7190a` ("revise JPEG viewer plan after review") on branch
`claude/viewer-port-remaining-steps-ofm5qp`, against the brief in
`docs/design/lazy-jpeg-pyramids-revision-review-prompt.md` on the same commit.
**The review it answers:** `docs/reviews/2026-09-01-review-of-the-lazy-jpeg-pyramid-design.md`,
commit `48f72d64` on `claude/lazy-jpeg-pyramids-review-fhz6te`.
**ZMART Viewer inspected:** `thomdehoog/zmart-viewer`, commit `9ff10b0`,
version 0.2.0.
**Verdict, in one line:** accept the stop decision; revise phase 2 before it is
authorised, and fix one ordering problem in phase 0A.

The revision is a genuine improvement. It takes the architectural verdict, it
keeps the parts of the original that were right, and where it declines a
suggestion it says why rather than quietly dropping it — the refusal of a
persistent cache floor is correctly argued and I withdraw that suggestion. What
follows is what is left.

---

## Remaining blockers

### 1. Phase 2 cannot keep its own promise, because the piece address is a Zarr chunk address

This is the one finding that changes the revised plan's shape.

The plan's rule for a conditional 8-bit or JPEG response is that it "must use
the existing piece addresses, geometry, revision, source, and canvas", and that
it "remains another representation of the same addressed piece and revision". In
the architecture as built, that is not something a request can be.

What the piece route actually is, in Viewer 0.2 at `9ff10b0`:

- `the_piece_address` (`zmart_viewer/compose.py:671–684`) parses a path of the
  form `<level>/c/<...>` — that is a Zarr chunk key, not a neutral tile
  coordinate.
- `Composer.values_for` (`compose.py:1383–1405`) composes the piece and encodes
  it by writing it into a one-chunk Zarr array of the picture's own dtype and
  reading the encoded chunk straight back out.
- `codecs_for` (`compose.py:659–665`) chooses the codec chain *from the dtype* —
  a one-byte dtype has no endianness to declare, so it gets a different chain.
- And the composer guards the agreement explicitly (`compose.py:788–796`),
  raising rather than allowing a mismatch, with a comment that is the whole
  point: "the browser would be handed bytes it cannot read, and nothing would
  report it — the window would simply be black".

A Zarr array declares one dtype and one codec chain, once, in its `zarr.json`,
and every client — Viv's `loadOmeZarr`, Neuroglancer's Zarr driver — decodes
every chunk according to that declaration. There is no content negotiation in
that contract and no per-request variation. So:

- **An 8-bit response at the same address is a different declared array.** It
  needs its own `zarr.json` with `dtype: uint8` and its own codec chain, which
  means its own multiscale description — a second source, under a different
  name, which is what the plan forbids in its own list at lines 180–188.
- **JPEG through the piece route is worse.** No Zarr client will accept
  `image/jpeg` as a chunk body. It would need not only a second source
  description but a second loader, which is the second renderer path the plan
  also forbids.

So phase 2 as written would fail the plan's own gate ("adds no second source,
grid, scene, or invalidation contract") on the first day. The brief asks
(question 7) whether either encoded response can reuse the current frontend
source; on this reading of the code, neither can.

**What to do instead, and it is smaller.** The honest version of the experiment
is not a second representation offered alongside the first; it is **one
picture, declared differently**. Compose the source as `uint8` — pixels mapped
once through the resolved acquisition display window — declare it that way in
the one source description, and serve it through the unchanged piece route to
the unchanged client. There is exactly one source at any moment; which one is
chosen when the picture is opened, not negotiated per request. That keeps every
promise the plan makes, needs no loader adapter, and is a change to the
composer's declared dtype rather than a new delivery path.

If it helps to say what that costs: an 8-bit picture cannot serve the 16-bit
scientific view, so the choice becomes a property of how a picture is opened,
and the operator must be able to see which one they have. That is a real design
question, and it is a much smaller one than a second format.

Drop JPEG from phase 2 entirely, or move it out of the piece route and into an
explicitly separate remote-viewing product with its own justification. It cannot
be both "no second source" and "JPEG".

### 2. Phase 0A's step order would reintroduce the near-black picture through a different door

Phase 0A says that when no acquisition-wide window exists, "position stores omit
`start` and `end`; they still record honest `min` and `max`". The intent is
right. Done in that order, against Viewer 0.2 as it stands, it is unsafe.

Follow what the viewer does when nothing declares a window:

- `contrast._omero_window` (`zmart_viewer/contrast.py:32–49`) returns a window
  only when **both** `start` and `end` are present and `end > start`; otherwise
  `None`.
- With `None`, the viewer measures, walking from the coarsest level down and
  skipping any level that holds no pixels yet
  (`contrast.py:168–170`, `_level_holds_pixels` at `:64`).
- And when nothing at all can be read, `display_window` returns
  **`0.0, 65535.0`** (`contrast.py:551–556`), and `measure` returns the same
  pair for both its windows (`contrast.py:315–325`).

`0.0, 65535.0` is the camera range. It is the exact value this plan says must
never become a display window, and the exact fault behind the "very nearly
black" picture recorded in `viz_studio/options/contract.md` §6 and in
`application/parts/storage/zarr_positions.py:125–129`.

The state that reaches it is not exotic. An unbaked composed picture at the
start of a live run has no written pixels in its levels, which is precisely when
an operator opens the canvas. Today the per-position window — clumsy, and
correctly identified as the thing to replace — is what keeps that path from
being taken.

**What to do.** Order the work so the guarantee is never absent:

1. First, make the composed/linked source carry one acquisition window (declared
   from the preset, or measured once and recorded with its provenance).
2. Only then stop the position writer from stamping its own.
3. Separately, in the Viewer repository, change those two `0.0, 65535.0`
   fallbacks to mean "no window yet" rather than "the whole camera", so that a
   picture with nothing measurable says so instead of opening black. That is a
   viewer-side change and belongs in the joint schema conversation the plan
   already calls for.

Until step 3 lands, step 2 must not.

### 3. The storage accounting misses the roots the Viewer writes to outside any run folder

The eight categories are a good improvement, and the insistence that scientific
working data is not disposable merely because someone called it a cache is
right. The list is organised by *kind* of byte, though, and the caps are
enforced against roots. Two roots are missing.

`zmart_viewer/server.py:1110–1124` composes into
`~/.zmart-viewer/scenes/session-XXXXXX`, made on first use, and there is a
matching `replays` folder. Both are removed on a clean shutdown
(`server.py:1531–1535`) and therefore survive a crash, a kill, or a power cut on
the microscope PC. They sit in the operator's home directory, under neither the
run folder nor any cache root, so neither the ten-per-cent rule nor the 5 GiB
all-runs ceiling can see them, and the "one process-wide eviction service" the
plan asks for has nothing pointed at them.

**What to do.** Name the *roots* alongside the categories, add the viewer's
session scratch as its own line with its lifecycle stated ("removed on clean
shutdown; leaked on a kill"), and make "sweep orphaned session folders at
start-up" an explicit item rather than something eviction is assumed to cover.

---

## Corrections to the revised architecture

1. **Say what "one source" means when the dtype can change.** With blocker 1's
   correction, the single-source rule needs one more sentence: there is one
   source *description live at a time*, chosen when the picture is opened, and
   the operator can see which. Without that, "one source" and "an 8-bit option"
   read as contradictory.

2. **The area-averaging qualification is correct, with one thing to verify
   rather than assert.** It is true that a reducer other than decimation can be
   registered with an explicit per-level translation — OME-NGFF allows a
   translation beside the scale in each level's coordinate transformations, so
   this is within the format. Two costs should be named beside it. First,
   whether the installed engines honour a per-level translation is a check, not
   a given, and it should be made before the possibility is relied on. Second,
   decimation is not only a registration convention: it is what lets a composed
   view *point at* the positions' own smaller copies instead of writing its own
   (`zmart_storage/positions.py:139–142`, and the same rule in the Viewer's
   `docs/how_it_works/HOW_OURS_DIFFERS_FROM_OME_ZARR.md:83–91`). A different
   reducer costs that arrangement too, not just an extra transform.

3. **Phase 0A's test list should add the legacy case as a test, not only as
   prose.** The plan says in the "Writer and view behaviour" section that a
   legacy folder whose positions disagree must not silently take the first
   store's value. That is the right rule and it is the one most likely to be
   broken by accident; put it in the list of things tests must prove.

4. **Name where the `z=0` / `z=0.5` evidence goes** (their question 7). The
   cheapest committed form already exists: the step-by-step Playwright walk
   photographs the window (`the-window-step-by-step.spec.js`), and
   `which-layer-draws.spec.js` records what each layer was asked for and what
   came back. A one-plane source photographed at both sampling positions, in
   that suite, turns a debugging report into a test that fails if the convention
   flips. That is a small addition and it closes the last open item in the Z
   section.

5. **The small-run consequence of refusing a floor should be stated.** The
   refusal is correct — a floor cannot be allowed to breach the ten-per-cent
   rule, and transient RAM is the right answer. But it follows that on a 200 MB
   run the automatic delivery cache is about 20 MB and effectively off, so a
   phase-2 measurement on a small fixture will show no persistence benefit. Say
   so in the plan, or somebody will later read that as the encoding failing.

---

## A proposed display-window schema and authority chain

The revision's `zmart.displayWindows` block is close. Three changes.

**One authority, named, and it is the composed view.** The acquisition record is
where a window is *decided*; the one Viewer source description is where it is
*read from*. The embedded canvas and the standalone viewer must read the same
place, or they will disagree the first time a legacy run is opened. Position
stores mirror it for the benefit of napari and Fiji, and are never consulted by
the canvas.

**Carry it as ordinary OME `start`/`end` plus ZMART provenance beside it**, as
the revision proposes — so a foreign reader gets a sensible picture and a ZMART
reader can tell where the numbers came from.

```json
{
  "zmart": {
    "displayWindows": [
      {
        "channelKey": "488",
        "start": 300,
        "end": 4200,
        "method": "preset",
        "algorithm": null,
        "sampleCount": 0,
        "resolvedAtRevision": 0,
        "resolvedFrom": "acquisition-record"
      }
    ]
  }
}
```

`resolvedFrom` is the one addition: it names which of the four steps produced
the pair, so a later reader can tell a preset from a measurement without
inferring it from `method` being null.

**The authority chain, with the absent case made explicit:**

```text
acquisition preset or protocol
    -> operator-approved window recorded for this run and channel
    -> one deterministic measurement over the composed acquisition,
       recorded with its algorithm, sample set, and revision
    -> no declared window
```

and then, for each consumer of the last case:

- the 16-bit viewer measures a provisional range and marks it provisional;
- the panel shows it as measured, not declared;
- an 8-bit or JPEG encoder **refuses the channel**;
- and nothing anywhere substitutes `min`/`max`.

That last line needs the viewer change in blocker 2 to be true today.

**One benefit worth claiming, because it is measurable now.** The Viewer's own
`measure/measure_cold_open.py` exists to count how many stores must have their
pixels read merely to decide how a picture should first be shown. A declared
acquisition window removes that read entirely. Run that harness before and after
phase 0A and the contract pays for itself in a number rather than in principle.

---

## Phase 0 measurements, and the harnesses that already exist

Reuse before writing. In the Viewer repository (`measure/`):

- `measure_cold_open.py` — cold open cost and how many stores are read to
  decide the opening brightness; the before/after for phase 0A.
- `measure_one_more_position.py` — landing-to-visible, the flat-with-survey-size
  claim.
- `measure_the_four_ways_of_serving.py` — baked against composed, cold first
  answer and warm median per piece.
- `measure_the_relinked_row.py` — zero-copy pointer serving after a re-link.
- `measure_loading_per_format.py` — the smallest existing extension point for
  response bytes per format, which is what a phase-2 gate needs.
- `measure_compression_cost.py` — already establishes that zstd costs about
  1.4× an uncompressed store when slots line up and about 2.0× when they do not,
  which is the baseline any byte-reduction claim is measured against.
- `app/picture/measure_a_ladder_of_surveys.py` — the 64-to-32,761 ladder, to be
  repeated only at the sizes that matter on the real machine.

In this repository:

- `viz_studio/options/measure/run.py --option all` — the photograph-based
  three-engine comparison that produces `RESULTS.md`.
- The Playwright walks: `every-tile-is-filled.spec.js` (each field measured
  separately, which is the one that catches "twenty of fifty-four drawn"),
  `a-whole-96-well-plate.spec.js`, `which-layer-draws.spec.js`, and
  `the-window-step-by-step.spec.js`.
- `application/draw_the_plate.py` for a mid-run picture.

**Two gaps to plan for, because no existing harness covers them.**

First, browser decoded-image and GPU memory. Nothing in either repository
measures it today, and the plan's memory gate depends on it. Decide the
defensible proxy before the trace, not after.

Second, and this one is prerequisite work rather than a gap to note: the options
rig **cannot currently be pointed at a foreign store**. `viz_studio/options/RESULTS.md`
says so itself — `--data` says where the rig *writes* its own acquisitions, not
where to find somebody else's, and it records that every finding from the 75 GB
real acquisition was invisible to a suite that only opens stores it wrote. Phase
0B is built entirely on real ZMART runs, so "let the rig open a run it did not
write" is a named task inside phase 0B, not an assumption.

---

## Gates that are arbitrary, unmeasurable, or gameable

- **"A useful whole-acquisition picture appears within 2 seconds" is not yet
  measurable**, because "useful" and "scientifically recognisable" are not
  defined. Give it a mechanical definition — for example, every visible piece at
  the opening level has answered, or a stated fraction of the visible area is
  non-empty — or it becomes the one gate that can be argued either way after the
  result is known.

- **The 2-second threshold may already be known to fail, which makes phase 0's
  outcome partly pre-decided.** `docs/open/MEASURED_the_four_ways_of_serving.md`
  records a cold first answer at 10,000 positions of 3.4 s baked and 13.1 s
  unbaked on that machine. Either the threshold applies only to a warm open, or
  it applies to cold and phase 0 will fail at large sizes for reasons the plan
  has already diagnosed (bake and warm). Say which, before measuring.

- **"Fivefold fewer bytes" is gameable by choosing what to count.** Fix it now:
  all bytes over the wire for the whole scripted trace, descriptions and
  revalidation included, not image chunk bodies only. Otherwise a format that
  halves image bytes and triples description traffic can be made to look like a
  win.

- **"Memory reaches a stable bound during repeated navigation" has no number.**
  Stable against what, over how many cycles? Give it a figure and a cycle count,
  even a provisional one, since the whole point of the revision's threshold
  section is that gates must be able to fail.

- **"No position-count-proportional browser request pattern appears" cannot
  fail** in the current architecture — the composed path already has that
  property, and it is the finding that produced the stop decision. It is
  worth keeping as a regression check, but it should not be counted among the
  gates that decide anything.

- Two gates are well formed and worth saying so: the ten-per-cent
  no-regression bound on navigation time, and the cross-engine registration
  requirement. Both can return "no", and neither can be argued away.

---

## Short answers to the brief's ten questions

1. **Does a second path remain under a different name?** Not in phases 0 and 1,
   which are clean. It returns in phase 2: an encoded response at the same piece
   address is necessarily a second declared source, because the address is a
   Zarr chunk address (blocker 1).
2. **Is acquisition-level metadata the right authority?** For *deciding*, yes.
   For *reading*, the authority must be the one composed Viewer source, or the
   canvas and the standalone viewer will disagree on legacy runs. Add
   `resolvedFrom`; keep the four-step precedence, which is otherwise correct.
3. **Is omitting per-position `start`/`end` compatible with the composed and
   linked paths?** Compatible in principle — `_omero_window` simply returns
   `None` and the viewer measures — but not safe in the order the plan gives
   it, because the no-samples path returns the camera range (blocker 2).
4. **Does the storage accounting distinguish the categories correctly?** The
   categories are right; the roots are incomplete. `~/.zmart-viewer/scenes` and
   `replays` are unaccounted and leak on an unclean shutdown (blocker 3).
5. **Are the limits right?** Two are provisionally reasonable (500 ms
   navigation, the ten-per-cent regression bound). Three need work before
   measuring: "2 seconds to a useful picture" needs a mechanical definition and
   a stated warm/cold scope, "fivefold" needs its byte set fixed, and the memory
   gate needs a number. The 10% and 5 GiB caps are sound as a policy; state the
   small-run consequence.
6. **What is the smallest response-size experiment?** Not JPEG, and not 8-bit
   offered alongside 16-bit. It is declaring the one composed picture as
   `uint8`, mapped once through the resolved window, and serving it through the
   unchanged route — one source at a time, chosen at open (blocker 1).
7. **Can either encoded response reuse the current frontend source?** No. Both
   require a second declared array and, for JPEG, a second loader.
8. **Is the area-reduction qualification correct?** Yes, as stated. Add that
   engine support for a per-level translation is a check rather than a given,
   and that decimation also buys the pointing arrangement, not only
   registration.
9. **Does the Z section now separate verified fact from reported evidence?**
   Yes, and it now uses the existing `theMiddlePlaneOf` rule. The remaining step
   is naming where the evidence gets recorded — see correction 4.
10. **Smallest phase-0 patch, and who owns what?** In ZMART-microscopy:
    the acquisition record grows a channel-description block, and
    `position_store_from_record` in
    `application/parts/storage/zarr_positions.py` takes those descriptions
    instead of calling `_a_window_onto` per position. In ZMART Viewer: the
    composed source description carries the acquisition window once, and
    `contrast.display_window` and `contrast.measure` stop returning
    `0.0, 65535.0` for "nothing measurable yet". Nothing else in phase 0 is a
    code change; the rest is harness work.

---

## Verdict

**Accept the stop decision. Revise phase 2 before it is authorised, and reorder
phase 0A.**

Phases 0A, 0B and 1 are sound and can proceed once blocker 2's ordering is
fixed — the viewer's camera-range fallback has to become "no window yet" before
the position writer stops declaring one. Phase 2 should be rewritten as a
wholesale `uint8` declaration experiment rather than a second representation at
the same address, and JPEG should either leave the piece route or leave the
plan.

I do not recommend retaining a separate JPEG experiment now. The revision's own
stop conditions are the right ones, and the first of them — that Viewer 0.2
already meets the operator thresholds — has not been tested yet on the machine
that matters.
