# Review notes

This folder holds the written record of code reviews done on this
repository.

Three documents live at the top level:

- `MAINTAINER_DECISIONS.md` — decisions the maintainer has made about how
  the code should behave. Code and tests cite these decisions by section
  number, so this file is the one to check when you wonder *why* something
  works the way it does.
- `2026-07-13-branch-review-findings-and-next-steps.md` — the July 13
  full review of the branch, with its open next-steps list.
- `2026-07-19-leica-driver-review.md` — the Leica driver review: how the
  driver is organized, the limits model, the reorganization that followed,
  and the quirk catalog with what is resolved and what remains.
- `2026-09-01-review-of-the-lazy-jpeg-pyramid-design.md` — a review of the
  proposal to build a display-only JPEG pyramid for the browser viewer. The
  design itself lives on another branch; this note names the commit it read,
  and the reasoning applies more widely than that one proposal.

Everything in `archive/` is history: earlier review rounds, the prompts
that were used to run them, and progress snapshots from along the way.
They are kept for reference but you should not need them for day-to-day
work at the microscope.
