# Two ways of showing a picture, and which one the microscope gets

> Decided 2026-08-12, after measuring both ways on one machine on the same
> afternoon and comparing what each was built to assume. This note records the
> division of labour so it is a decision, not a habit.

The repository holds two complete ways of showing many positions as one
seamless picture, grown on two branches toward two different problems.

**Pointing** (`zmart_live`, the linked virtual view): the view stores no
pixels. Every piece of it is answered by handing over bytes a position's own
store already holds, located by byte range, gated by the run manifest. About
half a millisecond a chunk, no decoding, no cache.

**Building** (`viz_studio/building`): the view stores no pixels either, but
each piece is *made* on request — the positions that cover it are decoded,
laid in, and encoded fresh. Tens of milliseconds a piece, tolerant of
anything: fractional offsets, mixed compressions, arrangements chosen by
somebody else's instrument.

## The division

**A live acquisition is shown by pointing. Data that arrived finished is
shown by building. One front door serves both, and the operator never needs
to know which answered.**

## Why pointing is the live one — designed for it, not adapted to it

*The commit gate is the core of it.* Live serving must answer a question that
only exists while a run is growing: the bytes are on disk, but may they be
shown yet? The gateway serves a pixel only when the manifest says that exact
position and moment is published; written-but-withheld ground is
indistinguishable from ground never imaged. The builder has no such notion —
it assumes every byte on disk is fair game, which is only true of finished
data.

*It expects the picture to change under the reader.* Draw order follows
commit order; replacing a moment makes a new generation with a rollback; the
manifest is re-checked on every request; the per-commit metadata rewrites
carry patience for a reader's hold, a lesson paid for when a live run died at
revision 36 of 144 on the lab Windows machine. The builder's caches assume
the opposite: that what was read once is true forever.

*It costs nothing on the machine that is busiest.* Serving is
byte-forwarding. No decode, no cache worth naming, on a computer that is at
the same time acquiring, compressing and writing. The builder's per-request
processor time and its gigabyte of decoded blocks are welcome on an archive
server and unwelcome on an acquisition rig.

*Its tests are live-shaped.* The sabotage campaigns defend serving in commit
order; the browser tests photograph a run while it grows; the parallel-fire
tests hammer a commit landing in the middle of a request storm. The
builder's checks assume the picture holds still — and its own bug history
shows what happens where that assumption is the thing that fails.

## Why building is the import one

A transfer from another microscope was arranged by nobody: the Thy1 set
steps 4547.06 voxels between rows, no chunk size divides that, and its
chunks were cut at somebody else's boundaries before we ever saw them.
Pointing is impossible there, and correctly refused. Building decodes
anyway, so it does not care — and the responsiveness plan
(`viz_studio/PLAN` work on the building branch) records how caching and an
exhaustive coarse warmer make its flexibility stop costing anything an
operator can feel.

## The seam, stated once

The seam between the two is not "live against archived" but **who wrote the
bytes**. Anything our own writer encoded is aligned and uniform by
construction — the profile plans the format, write-time padding lands every
position on the chunk grid wherever biology put the target — so pointing
serves it, live or finished. Anything that arrived already encoded is served
by building, or rewritten once at import into our own form and pointed at
thereafter. Neither mechanism should be stretched across the seam: building
asked to serve a live run must re-earn every consistency guarantee the
gateway already has, and pointing asked to serve a foreign transfer must
refuse, which helps nobody at the microscope.
