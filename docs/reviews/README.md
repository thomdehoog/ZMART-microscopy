# Review notes

This folder holds the written record of code reviews done on this
repository.

Four documents live at the top level:

- `MAINTAINER_DECISIONS.md` — decisions the maintainer has made about how
  the code should behave. Code and tests cite these decisions by section
  number, so this file is the one to check when you wonder *why* something
  works the way it does.
- `2026-07-13-branch-review-findings-and-next-steps.md` — the July 13
  full review of the branch, with its open next-steps list.
- `2026-07-19-leica-driver-review.md` — the Leica driver review: how the
  driver is organized, the limits model, the reorganization that followed,
  and the quirk catalog with what is resolved and what remains.
- `2026-08-09-live-position-timepoint-publication-review.md` — an
  independent review of the live OME-Zarr publication branch
  (`agent/live-position-timepoint-publication`). It says which of that
  branch's promises were tested by running them, which held up, and which
  did not. The important one for anybody imaging a region that is not a
  plain rectangle: on such a mosaic the code currently lets two tiles own
  the same piece of specimen, so objects there are counted twice.

Everything in `archive/` is history: earlier review rounds, the prompts
that were used to run them, and progress snapshots from along the way.
They are kept for reference but you should not need them for day-to-day
work at the microscope.
