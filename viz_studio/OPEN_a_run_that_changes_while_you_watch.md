# Open question: what happens when a run changes while somebody is watching it

Written 5 August 2026, for a later session. Nothing here is built. This is a
question that came up once the fast path for *adding a tile* existed, and it is
written down now because the answer needs deciding before more is built on top.

---

## What is already settled

**A new position is a new tile, and that works.** A run being acquired holds its
view open with `start_a_growing_view` in `zmart_storage/linked.py` and adds tiles as
they land. Adding one costs the same whether it is the first of the run or the ten
thousandth, and the viewer answers for it immediately — measured, and covered by
`viz_studio/tests/test_a_growing_view_is_read_as_it_grows.py`, which checks after
*every* tile rather than once at the end.

The way that works is worth knowing before reading the rest. The list of pointers
is a file the viewer's server reads and then remembers, and it notices the list has
grown by watching the file's **length**. A tile landing makes the file longer, so
the next request re-reads it and the tile appears.

## The question

A run does not only gain positions. It can also gain **a colour, a moment, or more
depth** — a timelapse taking its next round, a second laser switched on partway
through, a stack going deeper than planned. And it can **re-image a position it has
already imaged**, which a targetscan does by design.

Neither of those is a new tile, and neither works today.

**Gaining a colour, a moment or depth.** A view settles what it is when it is
opened: how many moments, how many colours, how deep, read from the first tile it
is shown. Every tile added later has to match, and one that does not is refused —
deliberately, because a view that quietly accepted a different shape would be
handing the viewer bytes described as something they are not. Depth is the mildest
of the three, because the room is declared up front and a run that declares enough
is fine. Moments and colours have no such escape: the number is fixed at the start.

**Re-imaging a position.** This one is worse, and it is the reason this document
exists. When a tile is written over in place, **nothing changes that anything is
watching.** The pointer still points at the same file, the list of pointers is
exactly as long as it was, and the file's length is what the reader uses to notice
a change. So the viewer keeps answering with what it has: the operator is shown the
old picture, the run has moved on, and nothing anywhere says so. Two further things
are stale at the same moment — the zoomed-out copies, which were written from the
tile's old pixels, and whatever the browser has already cached.

## The shape of the answer, and the choice inside it

The choice is between the run **telling** the viewer that something changed, and the
viewer **asking**. Both are ordinary; they fail differently.

**Asking** is what happens today, and it is cheap because there is a single small
file to look at. Its weakness is exactly the case above: a change that leaves the
file the same length is invisible. That is fixable — a counter in the view that goes
up whenever anything changes, including a tile rewritten in place, would give the
reader something to watch that always moves. Then re-imaging a position is noticed
the same way a new one is.

**Telling** means the writer says outright what changed, which the viewer already
has a way to carry: `ARCHITECTURE.md` records that it sends announcements to the
browser. That is more direct and more exact — it could name the affected part of the
picture rather than making the reader work it out — and it is more to build and more
to keep right, because a message that goes missing leaves the two out of step with
nothing to correct it.

**A sensible middle**, and the one to weigh first: let the counter be the truth and
the announcement be the hurry-up. The reader can always work out what it has to do
by looking; being told simply means it looks sooner. Then a lost message costs a
moment's delay rather than a wrong picture, which is the right way round for
something an operator is watching to make decisions.

Whichever is chosen, two things have to be settled with it:

- **The zoomed-out copies of a re-imaged position have to be written again.** They
  hold that tile's old pixels, and unlike the full-size picture they cannot be
  pointed at.
- **The browser has to be persuaded to ask again** for pieces it already has. It
  caches them, reasonably, and a piece that has changed under the same address is
  precisely what a cache is not expecting.

## Where to look

| | |
| --- | --- |
| `zmart_storage/linked.py` | `GrowingLinkedView`, and `_put_the_list_where_the_viewer_looks` |
| `viz_studio/backend/linking.py` | `the_bytes_behind`, which is where "has it changed" is decided today |
| `viz_studio/tests/test_a_growing_view_is_read_as_it_grows.py` | what is already guaranteed about a tile landing |
| `ARCHITECTURE.md` | the announcements the viewer already has |
