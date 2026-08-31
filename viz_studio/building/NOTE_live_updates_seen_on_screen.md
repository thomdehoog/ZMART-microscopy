# Live updates, watched on a screen: what 2026-08-12 evening settled

> Written at the end of a session in which every claim below was watched in a
> real window or measured by a harness, most of them both. The operator sat at
> the machine throughout; "seen" means seen by them.

## The question

A smart run changes while somebody looks at it, and Neuroglancer offers no
public way to say "what you remember about this picture is stale" — the engine
treats a data source as immutable. The session asked: what are the honest ways
to keep the viewer current, do they work, and what do they cost?

## The two mechanisms, both now demonstrated

**In-place refresh** — the address never changes; the page is announced at and
tells the engine to let go of what it decoded, then re-asks. This is the
`wrote_image_in_place` path that already ships in this repository.

- On a plain store it is surgical and quick: squares written into one store
  appeared on screen well inside 700 ms of the announcement, ten out of ten,
  camera untouched (`show_in_place_refresh.py`, scratchpad).
- On the **built one-picture view** it works with one server-side addition —
  the composer's caches must be dropped when the ground changes
  (`served.forget` stood in for that) — and its granularity is the whole
  picture: there is nothing smaller to let go of than the one source. Watched
  consequence: every landing makes every *unchanged* position blink as the
  engine refetches the entire visible screenful, and the sustainable rate
  tops out at **about 2 changes a second** however fast changes are asked for
  (asked 8/s, achieved 1.7/s; `show_positions_landing.py`). Appear **and**
  disappear both work — withhold and rollback were watched happening — and
  the same demonstration ran in the native pywebview window.

**Generation swap** — never mutate a loaded picture; each change produces a
fresh immutable picture at a fresh address, and the page closes the old and
opens the new through the server's own front door (`POST /api/stores/open`,
`/close`, `/announce` — the route `make_server`'s docstring names for
workflows). The engine can have no memory of an address it has never seen, so
nothing needs invalidating and nothing stale can survive. Demonstrated with
four colour-named generations of 100 positions
(`measure_a_fresh_view_each_time.py`); the swap is honest but **cold** — each
generation pays a fresh composer, the overview's deferred opening bill, and a
contrast measurement. The known cure is baking the generations at declare
time; **the `bake=True` rerun of the harness is the one measurement still
owed.**

## The decision this points to

The two compose rather than compete:

- a position landing or being withheld in a live run → **in-place refresh**,
  with change zero's per-piece invalidation replacing today's
  forget-everything;
- a new timepoint, a finished region, a rollback of structure → **generation
  swap**, with the bake **patched per commit** (a landing touches ~one piece
  per pinned level plus the chained pieces above — milliseconds beside the
  commit's ~500 ms), never rebuilt.

The blink on unchanged ground and the 2/s ceiling are the same defect —
whole-picture granularity — and per-piece invalidation is the cure for both:
the composer already indexes which pieces a position falls in, so it can name
exactly what a commit dirtied. That is change zero's cache-counter work seen
from the browser's side.

## Rules found the hard way, all reproduced on this machine

1. **The page owns the layer list; never swap sources underneath it.** A
   harness that replaced layers through the engine's own API fought the
   page's sync pass — several times a second, panel and picture flickering
   without end. Everything from outside goes through the server's API and an
   announcement; the page does the rest.
2. **The composer must release committed tiles at the commit boundary.**
   Windows refuses to replace a chunk file the server holds open (WinError 5
   stopped a landing mid-demo). Writer and server share tiles only if the
   composer closes them when told the ground changed.
3. **Contrast windows come from declarations, never from measuring.** A live
   run opens black, and a window measured from an unimaged picture makes
   every later arrival invisible until a hand fixes it. `make_server`'s
   `window=` (and, properly, the run's declared per-channel windows) is the
   honest source.
4. **Instruments must watch, not intervene.** Polling `page.screenshot` in a
   loop forces the compositor's hand and flashes the operator's window; the
   CDP screencast (`Page.startScreencast`) streams the page's own frames with
   their own timestamps and disturbs nothing. The swap harness carries this
   as `WatchingTheScreen`.

## Files

- `measure_a_fresh_view_each_time.py` (this folder) — the generation-swap
  harness: colour-named generations, page-level swap, screencast watcher,
  per-POST timing split. Loose end: run with baked generations.
- Scratchpad demos (session-local, not kept): `show_in_place_refresh.py`,
  `show_positions_landing.py`, `show_positions_landing_native.py`.
