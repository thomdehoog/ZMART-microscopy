# Hand-over: building becomes the main serving path

> Written 2026-08-12, at the end of the night the decision was made, for
> whoever opens this branch next — most likely tomorrow morning. Everything
> here has a longer form elsewhere; this page says where, and what to do
> first.

## Why any of this exists — the crux, first

**Neuroglancer cannot take many tiles as many sources.** Hand the viewer
one source per position and every cost grows with the count: the engine
manages, fetches, prioritises and refines each source separately, and at
hundreds of positions — let alone the ten thousand a survey produces — the
viewer collapses under its own layer machinery long before the pixels are
the problem. That is the root requirement behind everything in this
folder and on the live branch alike: **many tiles must reach the viewer as
one image.** The seamless view — virtual, whether pointed at or built — is
that one image. Every argument that followed (pointing against building,
the gate, the caches, the warmer) is about *how* to make one image out of
many tiles; that it must be one image was never in question, and is the
measure every future design change has to answer to first.

## The one-paragraph situation

The repository grew two complete ways of showing many positions as one
picture: **pointing** (the zero-copy linked view in `zmart_live`, on the
live branch) and **building** (this folder — each piece decoded, laid,
encoded on request). After measuring both on one machine and pressing the
padding trick until it bent, the decision went to building for the seamless
view — live runs included — because dense arbitrary placement is what smart
microscopy exists for, and pointing's alignment conditions compound against
it. Pointing's storage-and-governance layer survives whole: positions as
complete OME-Zarrs at true float coordinates are still the system of
record, and the manifest — the ledger of what is committed — still decides
what may be shown. **Opus's engine, inside Fable's governance**: this
folder draws; the ledger rules.

## The two branches, and what to take from each

- **This branch** (`agent/server-builds-the-picture-opus-5`): the engine
  (`mosaic.py`, `composer.py`, `served.py`), the plan
  (`docs/open/PLAN_responsiveness.md`), and the independent review of what must
  change (`docs/reviews/REVIEW_the_composer_meets_the_live_role.md`). Start with those
  two documents, in that order.
- **The live branch** (`claude/live-plus-viewer-gui-push-a68d9m`): the
  architecture decision with its reasons
  (`docs/design/pointing-and-building.md`, the superseding note at the
  top), and the governance machinery the gate work ports from:
  `zmart_live/gateway.py` (the reference implementation of gate-then-serve,
  fail-closed, generation-aware), `manifest.fingerprint()` (the cheap
  change signal), `CommittedState.by_store` (the per-position counter for
  cache keys), `events()` (commit order for the draw sort), and the test
  discipline — sabotage campaigns and the parallel-fire gateway tests.

**Mind the skew:** this branch carries its own, older copy of `zmart_live`.
The current one — later-wins overlap model, the parallel-fire tests, the
refreshed campaigns — lives on the live branch. Before starting the gate
work, bring this branch's `zmart_live` up to the live branch's (merge or
take their tree), or the port will copy from a superseded reference.

## What to do, in order

1. **Read** `docs/open/PLAN_responsiveness.md` (the plan, including change zero) and
   `docs/reviews/REVIEW_the_composer_meets_the_live_role.md` (ten findings, most severe
   first — it is the checklist for the gate work, and its closing section
   lists what NOT to re-litigate).
2. **Change zero — the composer learns the gate.** Sources from the
   manifest and layout, never `glob`; draw in commit order, later commit on
   top; fail closed on absent chunks of committed ground; the view change
   counter in every cache key. The review's findings 1-9 are the work
   items; the gateway is the working example of every rule.
3. **The quick wins beside it:** the slab finish and the disk cache
   (changes 1-2), which serve finished transfers immediately and need no
   gate.
4. **Then the coarse warmer** — the fix for the one slowness an operator
   actually reported (zooming out), with the one-percent pin rule.
5. **Checks throughout, repo style:** every fix watched failing first;
   composer faults added to the sabotage campaigns; the parallel-fire storm
   aimed at built answers; byte-equality against a lone polite build.

## Measured numbers to keep in your head

A fresh piece: 26-42 ms on a 4-core sandbox, flat from 64 to 1024 tiles.
A pointer answer, for comparison: ~0.5 ms — that gap is what the disk
cache and warmer exist to close, and caching closes it for everything
visited twice. Zoom-out is where slowness is felt, because a coarse piece
meets many positions and collects the deferred opening bill. The warmer's
floor is one visit to every position: seconds at 24 tiles, minutes at ten
thousand — paid once, in the background, coarsest first.
