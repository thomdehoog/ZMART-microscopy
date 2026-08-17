# Test plan: the picture grows a z-axis

> The companion of `PLAN_the_picture_grows_a_z_axis.md`, written 2026-08-17
> the same night. The plan says what is to be built; this says how it will be
> held to account, in what order, and on what data. The order is the campaign's
> standing one: gates first, bake-free, on synthetic data cheap enough to
> compare every voxel; measurement second, on the ladder; the real acquisition
> last, at the bench, as validation rather than as a test bed. Every browser
> gate is seen red through a named sabotage before its green is trusted —
> tonight's wire-word hunt is the standing reminder of why.

## The two kinds of data, and what each is for

**Synthetic deep tiles carry the whole correctness campaign.** The flat suite's
fixture (`_write_a_tile` in `test_a_transfer_is_built_into_one_picture.py`)
grows a real depth: a handful of planes — eight to thirty-two, enough for
several slabs — with **every plane stamped with its own index** (a per-plane
brightness step, or the plane number written into a corner of the values). The
stamp is the point: a piece served from the wrong slab, or a slab built off by
one plane, then *decodes to visibly wrong numbers* instead of passing because
all planes look alike. Tiles stay small (tens of kilobytes), so every test can
afford to compare every voxel against ground truth laid out by hand — the
suite's existing discipline, grown one axis.

**The Thy1 blocks are the bench rung, not a test bed.** The junction scripts
(`show_thy1_spiralling.py`, `show_thy1_one_source.py`) turn one real tile into
a growing survey for 195 KB, with real chunk sizes, real compression, real
anisotropy and the real z-halving pyramid. That is where claims are *validated*
— never where they are debugged, because a red on 120 MB chunks says "somewhere
in a minute of composing" where the same red on a stamped synthetic tile names
the slab and the plane.

## Stage 1 — geometry gates (no browser, minutes to run)

- **The room is declared whole.** A declared deep picture's description covers
  the full (t, c, z, y, x) room from the profile before any position lands,
  and a landing never changes the description: declare, land, re-declare, and
  the two `zarr.json` files must be byte-identical. (The shape-pinned corner
  trick tonight's gate uses becomes unnecessary the day this holds; the gate
  keeps it until then.)
- **Slab addresses bound-checked.** In-bounds slab addresses answer; out-of-
  bounds answer absent; the five-part address form is unchanged.
- **The halving decision, whichever way it lands, is pinned.** The open
  decision in the plan is decided by measurement; the moment it is decided, a
  geometry test asserts the per-level depths so the choice cannot drift.

## Stage 2 — composed slabs are correct (no browser, bake-free)

- **Every piece equals ground truth.** `_laid_out_by_hand` grows a z axis and
  every served slab piece is compared voxel-for-voxel — the long way, on
  purpose, so a helper shared with the code under test cannot repeat its
  mistakes.
- **Pieces asked for all at once are not muddled.** The parallel-encoder trap
  was found on the flat picture (13 to 22 of 25 pieces came back as somebody
  else's); the same test runs again in depth, because slab state is new shared
  state.
- **A landing dirties exactly its footprint.** Land one position; byte-compare
  every piece of every level before and after. Pieces inside the landing's
  (slabs × rows × columns) footprint change; every piece outside it is
  byte-identical. This is the surgical-cost claim made falsifiable.
- **A replacement in one moment leaves other moments alone** (the day t
  exists): the manifest-layer test the chapter plan already calls for, pinning
  the O(moments) dirty spike of a whole-position replacement.

## Stage 3 — browser gates (bake-free, synthetic, the held-view discipline)

All built on tonight's `test_a_built_picture_grows_while_watched.py` pattern:
open, settle, hold perfectly still, change the world behind the picture, and
require the screen to follow — then require a reload to reveal nothing the
held page was not already showing.

- **A landing appears at a held plane, in depth**: the view held on a plane in
  a *middle* slab (never slab zero — off-by-slab errors hide there), a block
  lands, it appears; warm ≥ fresh.
- **The revisited plane shows current truth**: visit a plane, move away, land
  a block there, come back — the frozen-plane fault of 2026-08-17,
  generalised: no plane may show older truth than the youngest announcement.
- **The held volume view follows**: the same gate with the 3-D view toggled
  on. Its census compares mean brightness as well as lit fraction, warm
  against fresh — which is also the instrument that decides the open FAULTS
  observation that the volume view can sit brighter warm than after a reload.
- **Zero transients throughout**, by the flat suite's per-frame recorder: held
  ground never dips dark and returns, on any plane, during any landing.

Each gate's red is produced by a named sabotage before its green counts: the
wire-word sabotage for the announcement chain (rehearsed tonight, red in 19
seconds), a skipped re-declare for the serving side, a deliberately shifted
slab key for delivery. A gate nobody has watched fail is a comment.

## Stage 4 — the regression floor

The entire existing suite stays green after every step — the flat browser
gates, the storm gate, the transfer tests — because depth must be an
extension, not a rewrite. Any flat test that has to change to accommodate
depth is a design smell to stop on, not to patch through.

## Stage 5 — measurement (the ladder, real shapes, the T400)

Only after stages 1–4 are green, and separately from them:

- the ladder's landing / derive / visible / bake columns re-measured on deep
  fixtures, against the flat baselines;
- the bake dial (nothing + RAM-pin / coarsest-only / pinned-share) measured as
  per-piece compose time by level against cold-open time, which sets the dial
  and closes the plan's open bake question;
- the z-halving decision's numbers, both ways, behind its switch;
- zero transients at every rung, as always — a faster number that flickers
  loses.

## Stage 6 — the bench rung: real Thy1, once, during development

This stage is **not a standing test and joins no suite**. It is run by hand,
once, when the feature is believed done — and again only after a rework big
enough to re-open the question. The recurring suites are synthetic-only, on
purpose: they must be green on any machine, and nothing in them may depend on
a particular acquisition sitting on a particular disk. Thy1's role is the
development-time proof that the synthetic gates modelled the real world
honestly; the record of this rung passing, with its numbers, goes into the
MEASURED document and that is where its duty ends.

Hands on the workstation, using the committed junction scripts against
`Thy1_Mag25x_Ch561.ome.zarr`:

- the growing one-source spiral, held-view and held-volume, by eye and by the
  probe script — the operator's own checks from 2026-08-17, now expected
  clean;
- warm-versus-F5 at several planes and zooms on the finished survey;
- the display window sanity the declared-room script warns about: the
  contrast chosen for the deep picture must describe imaged ground, not
  declared emptiness (Thy1's specimen sits at 319–13,471; a window that comes
  out near zero has sampled the room, not the brain);
- one long watch — the small sibling of the chapter plan's soak — with the
  spiral dripped slowly and the viewer left open through it.

Green here, with the numbers written beside the flat baselines, is the
feature's definition of done — the plan's acceptance section, made into a
checklist somebody can actually run.
